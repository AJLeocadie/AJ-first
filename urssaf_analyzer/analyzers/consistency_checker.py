"""Verificateur de coherence inter-documents.

Detecte les incoherences entre :
- Declarations DSN et documents comptables
- Masse salariale declaree vs calculee
- Effectifs declares vs employes identifies
- Cotisations entre periodes successives
- Reconciliation employe par NIR entre DSN et paie
- Cotisations par type et par employe
- Conformite des taux reglementaires
- Totaux et sous-totaux
- Controles specifiques DSN (CTP, blocs, SIRET)
"""

import json
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from urssaf_analyzer.analyzers.base_analyzer import BaseAnalyzer
from urssaf_analyzer.config.constants import (
    ContributionType,
    FindingCategory,
    PASS_MENSUEL,
    Severity,
    TOLERANCE_ARRONDI_PCT,
    TOLERANCE_MONTANT,
    TOLERANCE_TAUX,
)
from urssaf_analyzer.models.documents import (
    Cotisation,
    Declaration,
    Employe,
    Finding,
)
from urssaf_analyzer.rules.contribution_rules import ContributionRules
from urssaf_analyzer.utils.number_utils import ecart_relatif, formater_montant


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _annee_periode(decl: Declaration) -> tuple[str, str]:
    """Extrait l'annee et la periode sous forme lisible."""
    if decl.periode:
        annee = str(decl.periode.debut.year)
        periode = f"{decl.periode.debut.isoformat()} - {decl.periode.fin.isoformat()}"
    else:
        annee = ""
        periode = ""
    return annee, periode


def _details_technique(
    *,
    annee: str = "",
    periode: str = "",
    document: str = "",
    rubrique: str = "",
    extra: Optional[dict] = None,
) -> str:
    """Construit un bloc details_technique structure (JSON) pour le Finding."""
    data: dict = {}
    if annee:
        data["annee"] = annee
    if periode:
        data["periode"] = periode
    if document:
        data["document"] = document
    if rubrique:
        data["rubrique"] = rubrique
    if extra:
        data.update(extra)
    return json.dumps(data, ensure_ascii=False) if data else ""


def _doc_label(decl: Declaration) -> str:
    """Retourne un label lisible pour un document source."""
    parts = []
    if decl.type_declaration:
        parts.append(decl.type_declaration)
    if decl.reference:
        parts.append(decl.reference)
    if decl.source_document_id:
        parts.append(decl.source_document_id)
    return " / ".join(parts) if parts else decl.id


def _build_nir_index(decl: Declaration) -> dict[str, Employe]:
    """Index des employes par NIR pour une declaration."""
    idx: dict[str, Employe] = {}
    for emp in decl.employes:
        if emp.nir:
            idx[emp.nir] = emp
    return idx


def _cotisations_par_employe(decl: Declaration) -> dict[str, list[Cotisation]]:
    """Regroupe les cotisations par employe_id."""
    index: dict[str, list[Cotisation]] = defaultdict(list)
    for c in decl.cotisations:
        if c.employe_id:
            index[c.employe_id].append(c)
    return dict(index)


def _employe_id_to_nir(decl: Declaration) -> dict[str, str]:
    """Mappe employe.id -> employe.nir."""
    return {e.id: e.nir for e in decl.employes if e.nir}


def _nir_to_employe_id(decl: Declaration) -> dict[str, str]:
    """Mappe employe.nir -> employe.id."""
    return {e.nir: e.id for e in decl.employes if e.nir}


# Codes CTP obligatoires les plus courants en DSN mensuelle
_CTP_OBLIGATOIRES = {
    "100",   # RG cas general
    "430",   # Vieillesse plafonnee
    "100A",  # Cotisations AT
}

# Blocs DSN obligatoires (noms conventionnels)
_BLOCS_DSN_OBLIGATOIRES = {
    "S10",  # Emetteur
    "S20",  # Entreprise
    "S21.G00.06",  # Etablissement
    "S21.G00.11",  # Individu (au moins un)
    "S21.G00.30",  # Individu – identification
    "S21.G00.40",  # Contrat
    "S21.G00.51",  # Remuneration
    "S21.G00.78",  # Base assujettie
    "S21.G00.81",  # Cotisation individuelle
    "S21.G00.22",  # Cotisation agregee
    "S21.G00.23",  # Bordereau de cotisation due
}


class ConsistencyChecker(BaseAnalyzer):
    """Verifie la coherence entre les differents documents.

    Controles effectues :
    - Coherence interne de chaque declaration
    - Reconciliation inter-documents par NIR
    - Comparaison des cotisations par type et par employe
    - Validation des taux reglementaires (ContributionRules)
    - Comparaison des bases brutes par employe
    - Verification des totaux / sous-totaux
    - Controles specifiques DSN (CTP, blocs, SIRET)
    - Coherence temporelle entre periodes successives
    """

    @property
    def nom(self) -> str:
        return "Verificateur de coherence"

    # =================================================================
    # Point d'entree principal
    # =================================================================

    def analyser(self, declarations: list[Declaration]) -> list[Finding]:
        findings: list[Finding] = []

        for decl in declarations:
            findings.extend(self._verifier_coherence_interne(decl))
            findings.extend(self._verifier_taux_reglementaires(decl))
            findings.extend(self._verifier_totaux_sous_totaux(decl))
            if decl.type_declaration and decl.type_declaration.upper() in ("DSN", "DSN MENSUELLE", "DSN EVENEMENTIELLE"):
                findings.extend(self._verifier_dsn_specifique(decl))

        if len(declarations) > 1:
            findings.extend(self._verifier_coherence_inter_documents(declarations))
            findings.extend(self._reconcilier_employes_inter_documents(declarations))
            findings.extend(self._comparer_cotisations_par_type(declarations))
            findings.extend(self._comparer_bases_par_employe(declarations))
            findings.extend(self._verifier_coherence_temporelle(declarations))
            findings.extend(self._comparer_siret_inter_documents(declarations))
            findings.extend(self._comparer_taux_at_inter_documents(declarations))
            findings.extend(self._comparer_employe_details_inter_documents(declarations))
            findings.extend(self._comparer_totaux_patronaux_inter_documents(declarations))
            findings.extend(self._comparer_exonerations_inter_documents(declarations))
            findings.extend(self._verifier_exonerations_temporelles(declarations))

        # Coherence assiettes plafonnees/deplafonnees (intra-document)
        for decl in declarations:
            findings.extend(self._verifier_coherence_assiettes_plafonnees(decl))

        return findings

    # =================================================================
    # 1. Coherence interne (existant, ameliore)
    # =================================================================

    def _verifier_coherence_interne(self, decl: Declaration) -> list[Finding]:
        """Verifie la coherence interne d'une declaration."""
        findings: list[Finding] = []
        annee, periode = _annee_periode(decl)
        doc_label = _doc_label(decl)

        # 1. Masse salariale declaree vs somme des bases brutes
        if decl.cotisations and decl.masse_salariale_brute > 0:
            somme_bases = sum(c.base_brute for c in decl.cotisations if c.base_brute > 0)
            if somme_bases > 0:
                bases_uniques = set()
                for c in decl.cotisations:
                    if c.base_brute > 0:
                        bases_uniques.add(c.base_brute)

                if bases_uniques:
                    max_base = max(bases_uniques)
                    if decl.masse_salariale_brute > max_base * Decimal("1.5"):
                        ecart = decl.masse_salariale_brute - max_base
                        findings.append(Finding(
                            categorie=FindingCategory.INCOHERENCE,
                            severite=Severity.MOYENNE,
                            titre=f"Ecart masse salariale / bases de cotisations ({doc_label})",
                            description=(
                                f"La masse salariale declaree ({formater_montant(decl.masse_salariale_brute)}) "
                                f"est significativement superieure aux bases de cotisation "
                                f"(max : {formater_montant(max_base)}). Ecart : {formater_montant(ecart)}."
                            ),
                            montant_impact=ecart,
                            score_risque=55,
                            recommandation=(
                                "Verifier la coherence entre la masse salariale declaree "
                                "et les lignes de cotisations. Corriger l'assiette ou la masse "
                                "salariale dans le document source."
                            ),
                            detecte_par=self.nom,
                            documents_concernes=[decl.source_document_id],
                            details_technique=_details_technique(
                                annee=annee, periode=periode, document=doc_label,
                                rubrique="Masse salariale brute",
                            ),
                        ))

        # 2. Effectif declare vs employes identifies
        if decl.effectif_declare > 0 and decl.employes:
            nb_employes = len(decl.employes)
            if nb_employes != decl.effectif_declare:
                ecart = abs(nb_employes - decl.effectif_declare)
                severite = Severity.HAUTE if ecart > 5 else Severity.MOYENNE
                findings.append(Finding(
                    categorie=FindingCategory.INCOHERENCE,
                    severite=severite,
                    titre=f"Ecart effectif declare ({decl.effectif_declare}) / identifie ({nb_employes})",
                    description=(
                        f"L'effectif declare ({decl.effectif_declare}) ne correspond pas "
                        f"au nombre d'employes identifies ({nb_employes}). "
                        f"Ecart : {ecart}."
                    ),
                    valeur_constatee=str(nb_employes),
                    valeur_attendue=str(decl.effectif_declare),
                    score_risque=65,
                    recommandation=(
                        "Verifier la completude des declarations individuelles. "
                        "Un ecart peut indiquer des salaries non declares ou un effectif errone."
                    ),
                    detecte_par=self.nom,
                    documents_concernes=[decl.source_document_id],
                    reference_legale="Art. L242-1 CSS",
                    details_technique=_details_technique(
                        annee=annee, periode=periode, document=doc_label,
                        rubrique="Effectif",
                    ),
                ))

        # 3. Cotisations sans base ou sans montant
        for c in decl.cotisations:
            if c.base_brute > 0 and c.montant_patronal == 0 and c.taux_patronal > 0:
                impact = c.base_brute * c.taux_patronal
                findings.append(Finding(
                    categorie=FindingCategory.INCOHERENCE,
                    severite=Severity.MOYENNE,
                    titre=f"Cotisation {c.type_cotisation.value} : base presente mais montant nul",
                    description=(
                        f"La cotisation {c.type_cotisation.value} a une base "
                        f"de {formater_montant(c.base_brute)} et un taux de {c.taux_patronal} "
                        f"mais un montant patronal de 0. Montant attendu : {formater_montant(impact)}."
                    ),
                    montant_impact=impact,
                    score_risque=50,
                    recommandation=(
                        "Verifier si une exoneration s'applique a cette cotisation. "
                        "Sinon, corriger le montant patronal."
                    ),
                    detecte_par=self.nom,
                    documents_concernes=[c.source_document_id],
                    details_technique=_details_technique(
                        annee=annee, periode=periode, document=doc_label,
                        rubrique=c.type_cotisation.value,
                    ),
                ))

        return findings

    # =================================================================
    # 2. Reconciliation employes par NIR (inter-documents)
    # =================================================================

    def _reconcilier_employes_inter_documents(
        self, declarations: list[Declaration],
    ) -> list[Finding]:
        """Compare les employes entre documents de meme periode par NIR.

        Detecte :
        - Employes presents dans un document mais absents d'un autre
        - Employes avec des informations divergentes (nom, statut)
        """
        findings: list[Finding] = []
        par_periode = self._regrouper_par_periode(declarations)

        for periode_key, decls in par_periode.items():
            if len(decls) < 2:
                continue

            for i in range(len(decls)):
                for j in range(i + 1, len(decls)):
                    d1, d2 = decls[i], decls[j]
                    if not d1.employes or not d2.employes:
                        continue

                    annee1, per1 = _annee_periode(d1)
                    label1, label2 = _doc_label(d1), _doc_label(d2)

                    nir_d1 = _build_nir_index(d1)
                    nir_d2 = _build_nir_index(d2)
                    all_nirs = set(nir_d1.keys()) | set(nir_d2.keys())

                    # Employes manquants dans d2
                    manquants_d2 = set(nir_d1.keys()) - set(nir_d2.keys())
                    if manquants_d2:
                        nirs_list = ", ".join(sorted(manquants_d2)[:10])
                        suffix = f" (et {len(manquants_d2) - 10} autres)" if len(manquants_d2) > 10 else ""
                        findings.append(Finding(
                            categorie=FindingCategory.INCOHERENCE,
                            severite=Severity.HAUTE,
                            titre=f"{len(manquants_d2)} employe(s) dans {d1.type_declaration} absent(s) de {d2.type_declaration}",
                            description=(
                                f"{len(manquants_d2)} employe(s) identifies par NIR dans "
                                f"{label1} ne figurent pas dans {label2} pour la "
                                f"meme periode ({per1}). NIR concernes : {nirs_list}{suffix}."
                            ),
                            score_risque=70,
                            montant_impact=Decimal("0"),
                            recommandation=(
                                "Verifier que tous les salaries declares dans la DSN "
                                "figurent egalement dans le journal de paie et vice versa. "
                                "Corriger les declarations individuelles manquantes."
                            ),
                            detecte_par=self.nom,
                            documents_concernes=[d1.source_document_id, d2.source_document_id],
                            reference_legale="Art. R243-14 CSS (DSN individuelle obligatoire)",
                            details_technique=_details_technique(
                                annee=annee1, periode=per1,
                                document=f"{label1} vs {label2}",
                                rubrique="Employes (NIR)",
                                extra={"nir_manquants": sorted(manquants_d2)},
                            ),
                        ))

                    # Employes manquants dans d1
                    manquants_d1 = set(nir_d2.keys()) - set(nir_d1.keys())
                    if manquants_d1:
                        nirs_list = ", ".join(sorted(manquants_d1)[:10])
                        suffix = f" (et {len(manquants_d1) - 10} autres)" if len(manquants_d1) > 10 else ""
                        findings.append(Finding(
                            categorie=FindingCategory.INCOHERENCE,
                            severite=Severity.HAUTE,
                            titre=f"{len(manquants_d1)} employe(s) dans {d2.type_declaration} absent(s) de {d1.type_declaration}",
                            description=(
                                f"{len(manquants_d1)} employe(s) identifies par NIR dans "
                                f"{label2} ne figurent pas dans {label1} pour la "
                                f"meme periode ({per1}). NIR concernes : {nirs_list}{suffix}."
                            ),
                            score_risque=70,
                            montant_impact=Decimal("0"),
                            recommandation=(
                                "Verifier que tous les salaries declares dans le journal de paie "
                                "figurent egalement dans la DSN et vice versa."
                            ),
                            detecte_par=self.nom,
                            documents_concernes=[d2.source_document_id, d1.source_document_id],
                            reference_legale="Art. R243-14 CSS",
                            details_technique=_details_technique(
                                annee=annee1, periode=per1,
                                document=f"{label2} vs {label1}",
                                rubrique="Employes (NIR)",
                                extra={"nir_manquants": sorted(manquants_d1)},
                            ),
                        ))

                    # Employes presents dans les deux : verifier coherence nom/statut
                    nirs_communs = set(nir_d1.keys()) & set(nir_d2.keys())
                    for nir in nirs_communs:
                        e1, e2 = nir_d1[nir], nir_d2[nir]
                        if e1.nom and e2.nom and e1.nom.upper() != e2.nom.upper():
                            findings.append(Finding(
                                categorie=FindingCategory.INCOHERENCE,
                                severite=Severity.FAIBLE,
                                titre=f"Nom divergent pour NIR {nir[:5]}... entre documents",
                                description=(
                                    f"L'employe NIR {nir} a un nom different entre "
                                    f"{label1} ('{e1.nom} {e1.prenom}') et "
                                    f"{label2} ('{e2.nom} {e2.prenom}')."
                                ),
                                montant_impact=Decimal("0"),
                                score_risque=25,
                                recommandation="Harmoniser les noms entre les systemes source.",
                                detecte_par=self.nom,
                                documents_concernes=[d1.source_document_id, d2.source_document_id],
                                details_technique=_details_technique(
                                    annee=annee1, periode=per1,
                                    document=f"{label1} vs {label2}",
                                    rubrique=f"Employe NIR {nir}",
                                ),
                            ))

        return findings

    # =================================================================
    # 3. Cotisation-type matching entre documents
    # =================================================================

    def _comparer_cotisations_par_type(
        self, declarations: list[Declaration],
    ) -> list[Finding]:
        """Pour chaque employe commun (par NIR), compare les cotisations
        par type entre deux documents de meme periode."""
        findings: list[Finding] = []
        par_periode = self._regrouper_par_periode(declarations)

        for _, decls in par_periode.items():
            if len(decls) < 2:
                continue

            for i in range(len(decls)):
                for j in range(i + 1, len(decls)):
                    d1, d2 = decls[i], decls[j]
                    findings.extend(self._comparer_cotisations_paire(d1, d2))

        return findings

    def _comparer_cotisations_paire(
        self, d1: Declaration, d2: Declaration,
    ) -> list[Finding]:
        """Compare les cotisations entre deux declarations pour les employes communs."""
        findings: list[Finding] = []
        annee, per = _annee_periode(d1)
        label1, label2 = _doc_label(d1), _doc_label(d2)

        nir_to_id_d1 = _nir_to_employe_id(d1)
        nir_to_id_d2 = _nir_to_employe_id(d2)
        cots_d1 = _cotisations_par_employe(d1)
        cots_d2 = _cotisations_par_employe(d2)

        nirs_communs = set(nir_to_id_d1.keys()) & set(nir_to_id_d2.keys())

        for nir in nirs_communs:
            eid1 = nir_to_id_d1[nir]
            eid2 = nir_to_id_d2[nir]
            cots1 = {c.type_cotisation: c for c in cots_d1.get(eid1, [])}
            cots2 = {c.type_cotisation: c for c in cots_d2.get(eid2, [])}

            all_types = set(cots1.keys()) | set(cots2.keys())

            for ct in all_types:
                c1 = cots1.get(ct)
                c2 = cots2.get(ct)

                # Type present dans un seul document
                if c1 and not c2:
                    findings.append(Finding(
                        categorie=FindingCategory.DONNEE_MANQUANTE,
                        severite=Severity.MOYENNE,
                        titre=f"Cotisation {ct.value} pour NIR {nir[:5]}... absente de {d2.type_declaration}",
                        description=(
                            f"La cotisation {ct.value} est presente dans {label1} "
                            f"(montant patronal : {formater_montant(c1.montant_patronal)}) "
                            f"mais absente de {label2} pour le NIR {nir}."
                        ),
                        montant_impact=c1.montant_patronal,
                        score_risque=55,
                        recommandation=(
                            f"Verifier pourquoi la cotisation {ct.value} n'apparait pas "
                            f"dans {label2}. Ajouter la ligne si necessaire."
                        ),
                        detecte_par=self.nom,
                        documents_concernes=[d1.source_document_id, d2.source_document_id],
                        details_technique=_details_technique(
                            annee=annee, periode=per,
                            document=f"{label1} vs {label2}",
                            rubrique=ct.value,
                            extra={"nir": nir},
                        ),
                    ))
                    continue

                if c2 and not c1:
                    findings.append(Finding(
                        categorie=FindingCategory.DONNEE_MANQUANTE,
                        severite=Severity.MOYENNE,
                        titre=f"Cotisation {ct.value} pour NIR {nir[:5]}... absente de {d1.type_declaration}",
                        description=(
                            f"La cotisation {ct.value} est presente dans {label2} "
                            f"(montant patronal : {formater_montant(c2.montant_patronal)}) "
                            f"mais absente de {label1} pour le NIR {nir}."
                        ),
                        montant_impact=c2.montant_patronal,
                        score_risque=55,
                        recommandation=(
                            f"Verifier pourquoi la cotisation {ct.value} n'apparait pas "
                            f"dans {label1}. Ajouter la ligne si necessaire."
                        ),
                        detecte_par=self.nom,
                        documents_concernes=[d2.source_document_id, d1.source_document_id],
                        details_technique=_details_technique(
                            annee=annee, periode=per,
                            document=f"{label2} vs {label1}",
                            rubrique=ct.value,
                            extra={"nir": nir},
                        ),
                    ))
                    continue

                # Present dans les deux : comparer taux et montants
                assert c1 is not None and c2 is not None
                self._comparer_taux_et_montants(
                    findings, c1, c2, nir, ct, d1, d2,
                    annee, per, label1, label2,
                )

        return findings

    def _comparer_taux_et_montants(
        self,
        findings: list[Finding],
        c1: Cotisation,
        c2: Cotisation,
        nir: str,
        ct: ContributionType,
        d1: Declaration,
        d2: Declaration,
        annee: str,
        per: str,
        label1: str,
        label2: str,
    ) -> None:
        """Compare taux patronal et montant patronal entre deux cotisations."""

        # Comparer taux patronal
        if c1.taux_patronal > 0 and c2.taux_patronal > 0:
            ecart_taux = abs(c1.taux_patronal - c2.taux_patronal)
            if ecart_taux > TOLERANCE_TAUX:
                findings.append(Finding(
                    categorie=FindingCategory.INCOHERENCE,
                    severite=Severity.HAUTE,
                    titre=f"Ecart taux patronal {ct.value} entre documents (NIR {nir[:5]}...)",
                    description=(
                        f"Taux patronal {ct.value} pour NIR {nir} : "
                        f"{c1.taux_patronal} dans {label1} vs "
                        f"{c2.taux_patronal} dans {label2}. "
                        f"Ecart : {ecart_taux}."
                    ),
                    valeur_constatee=str(c1.taux_patronal),
                    valeur_attendue=str(c2.taux_patronal),
                    montant_impact=abs(c1.montant_patronal - c2.montant_patronal),
                    score_risque=65,
                    recommandation=(
                        f"Identifier le taux patronal correct pour {ct.value} et "
                        f"harmoniser entre les deux documents."
                    ),
                    detecte_par=self.nom,
                    documents_concernes=[d1.source_document_id, d2.source_document_id],
                    details_technique=_details_technique(
                        annee=annee, periode=per,
                        document=f"{label1} vs {label2}",
                        rubrique=ct.value,
                        extra={"nir": nir},
                    ),
                ))

        # Comparer taux salarial
        if c1.taux_salarial > 0 and c2.taux_salarial > 0:
            ecart_taux_s = abs(c1.taux_salarial - c2.taux_salarial)
            if ecart_taux_s > TOLERANCE_TAUX:
                findings.append(Finding(
                    categorie=FindingCategory.INCOHERENCE,
                    severite=Severity.HAUTE,
                    titre=f"Ecart taux salarial {ct.value} entre documents (NIR {nir[:5]}...)",
                    description=(
                        f"Taux salarial {ct.value} pour NIR {nir} : "
                        f"{c1.taux_salarial} dans {label1} vs "
                        f"{c2.taux_salarial} dans {label2}. "
                        f"Ecart : {ecart_taux_s}."
                    ),
                    valeur_constatee=str(c1.taux_salarial),
                    valeur_attendue=str(c2.taux_salarial),
                    montant_impact=abs(c1.montant_salarial - c2.montant_salarial),
                    score_risque=65,
                    recommandation=(
                        f"Identifier le taux salarial correct pour {ct.value} et "
                        f"harmoniser entre les deux documents."
                    ),
                    detecte_par=self.nom,
                    documents_concernes=[d1.source_document_id, d2.source_document_id],
                    details_technique=_details_technique(
                        annee=annee, periode=per,
                        document=f"{label1} vs {label2}",
                        rubrique=ct.value,
                        extra={"nir": nir, "type_taux": "salarial"},
                    ),
                ))

        # Comparer montant patronal
        if c1.montant_patronal > 0 or c2.montant_patronal > 0:
            ecart_montant = abs(c1.montant_patronal - c2.montant_patronal)
            if ecart_montant > TOLERANCE_MONTANT:
                ref = max(c1.montant_patronal, c2.montant_patronal)
                ecart_pct = ecart_relatif(c1.montant_patronal, c2.montant_patronal)
                if ecart_pct > TOLERANCE_ARRONDI_PCT:
                    findings.append(Finding(
                        categorie=FindingCategory.INCOHERENCE,
                        severite=Severity.HAUTE if ecart_montant > Decimal("50") else Severity.MOYENNE,
                        titre=f"Ecart montant patronal {ct.value} entre documents (NIR {nir[:5]}...)",
                        description=(
                            f"Montant patronal {ct.value} pour NIR {nir} : "
                            f"{formater_montant(c1.montant_patronal)} dans {label1} vs "
                            f"{formater_montant(c2.montant_patronal)} dans {label2}. "
                            f"Ecart : {formater_montant(ecart_montant)} ({ecart_pct:.2%})."
                        ),
                        valeur_constatee=str(c1.montant_patronal),
                        valeur_attendue=str(c2.montant_patronal),
                        montant_impact=ecart_montant,
                        score_risque=60,
                        recommandation=(
                            f"Reconcilier le montant patronal de {ct.value}. "
                            f"Verifier base, taux et calcul dans les deux sources."
                        ),
                        detecte_par=self.nom,
                        documents_concernes=[d1.source_document_id, d2.source_document_id],
                        details_technique=_details_technique(
                            annee=annee, periode=per,
                            document=f"{label1} vs {label2}",
                            rubrique=ct.value,
                            extra={"nir": nir},
                        ),
                    ))

    # =================================================================
    # 4. Validation des taux reglementaires (ContributionRules)
    # =================================================================

    def _verifier_taux_reglementaires(self, decl: Declaration) -> list[Finding]:
        """Verifie chaque cotisation contre les taux reglementaires."""
        findings: list[Finding] = []
        annee, per = _annee_periode(decl)
        doc_label = _doc_label(decl)

        # Construire les ContributionRules avec les donnees employeur si dispo
        effectif = 0
        taux_at = Decimal("0.0208")
        if decl.employeur:
            effectif = decl.employeur.effectif or 0
            if decl.employeur.taux_at > 0:
                taux_at = decl.employeur.taux_at

        rules = ContributionRules(
            effectif_entreprise=effectif,
            taux_at=taux_at,
        )

        for c in decl.cotisations:
            # Taux patronal
            if c.taux_patronal > 0:
                conforme, taux_attendu = rules.verifier_taux(
                    c.type_cotisation, c.taux_patronal,
                    salaire_brut=c.base_brute, est_patronal=True,
                )
                if not conforme and taux_attendu is not None:
                    ecart = abs(c.taux_patronal - taux_attendu)
                    impact = c.base_brute * ecart if c.base_brute > 0 else Decimal("0")
                    findings.append(Finding(
                        categorie=FindingCategory.ANOMALIE,
                        severite=Severity.HAUTE,
                        titre=f"Taux patronal non conforme : {c.type_cotisation.value} ({c.taux_patronal} vs {taux_attendu})",
                        description=(
                            f"Le taux patronal de {c.type_cotisation.value} est de "
                            f"{c.taux_patronal} alors que le taux reglementaire attendu est "
                            f"{taux_attendu}. Ecart : {ecart}."
                        ),
                        valeur_constatee=str(c.taux_patronal),
                        valeur_attendue=str(taux_attendu),
                        montant_impact=impact.quantize(Decimal("0.01"), ROUND_HALF_UP),
                        score_risque=75,
                        recommandation=(
                            f"Corriger le taux patronal de {c.type_cotisation.value} "
                            f"pour appliquer le taux reglementaire de {taux_attendu}. "
                            f"Impact estime : {formater_montant(impact)}."
                        ),
                        detecte_par=self.nom,
                        documents_concernes=[decl.source_document_id],
                        reference_legale="CSS art. L241-1 et suivants",
                        details_technique=_details_technique(
                            annee=annee, periode=per, document=doc_label,
                            rubrique=c.type_cotisation.value,
                            extra={
                                "taux_constate": str(c.taux_patronal),
                                "taux_attendu": str(taux_attendu),
                                "employe_id": c.employe_id,
                            },
                        ),
                    ))

            # Taux salarial
            if c.taux_salarial > 0:
                conforme_s, taux_attendu_s = rules.verifier_taux(
                    c.type_cotisation, c.taux_salarial,
                    salaire_brut=c.base_brute, est_patronal=False,
                )
                if not conforme_s and taux_attendu_s is not None:
                    ecart_s = abs(c.taux_salarial - taux_attendu_s)
                    impact_s = c.base_brute * ecart_s if c.base_brute > 0 else Decimal("0")
                    findings.append(Finding(
                        categorie=FindingCategory.ANOMALIE,
                        severite=Severity.HAUTE,
                        titre=f"Taux salarial non conforme : {c.type_cotisation.value} ({c.taux_salarial} vs {taux_attendu_s})",
                        description=(
                            f"Le taux salarial de {c.type_cotisation.value} est de "
                            f"{c.taux_salarial} alors que le taux reglementaire attendu est "
                            f"{taux_attendu_s}. Ecart : {ecart_s}."
                        ),
                        valeur_constatee=str(c.taux_salarial),
                        valeur_attendue=str(taux_attendu_s),
                        montant_impact=impact_s.quantize(Decimal("0.01"), ROUND_HALF_UP),
                        score_risque=75,
                        recommandation=(
                            f"Corriger le taux salarial de {c.type_cotisation.value} "
                            f"pour appliquer le taux reglementaire de {taux_attendu_s}."
                        ),
                        detecte_par=self.nom,
                        documents_concernes=[decl.source_document_id],
                        reference_legale="CSS art. L241-1 et suivants",
                        details_technique=_details_technique(
                            annee=annee, periode=per, document=doc_label,
                            rubrique=c.type_cotisation.value,
                            extra={
                                "taux_constate": str(c.taux_salarial),
                                "taux_attendu": str(taux_attendu_s),
                                "employe_id": c.employe_id,
                            },
                        ),
                    ))

        return findings

    # =================================================================
    # 5. Comparaison des bases brutes par employe
    # =================================================================

    def _comparer_bases_par_employe(
        self, declarations: list[Declaration],
    ) -> list[Finding]:
        """Compare la base brute par employe (NIR) entre documents de meme periode."""
        findings: list[Finding] = []
        par_periode = self._regrouper_par_periode(declarations)

        for _, decls in par_periode.items():
            if len(decls) < 2:
                continue

            for i in range(len(decls)):
                for j in range(i + 1, len(decls)):
                    d1, d2 = decls[i], decls[j]
                    annee, per = _annee_periode(d1)
                    label1, label2 = _doc_label(d1), _doc_label(d2)

                    nir_to_id_d1 = _nir_to_employe_id(d1)
                    nir_to_id_d2 = _nir_to_employe_id(d2)
                    cots_d1 = _cotisations_par_employe(d1)
                    cots_d2 = _cotisations_par_employe(d2)

                    nirs_communs = set(nir_to_id_d1.keys()) & set(nir_to_id_d2.keys())

                    for nir in nirs_communs:
                        eid1 = nir_to_id_d1[nir]
                        eid2 = nir_to_id_d2[nir]

                        # Compute max base_brute per employee in each doc
                        bases1 = [c.base_brute for c in cots_d1.get(eid1, []) if c.base_brute > 0]
                        bases2 = [c.base_brute for c in cots_d2.get(eid2, []) if c.base_brute > 0]

                        if not bases1 or not bases2:
                            continue

                        # Use the largest base (usually = brut mensuel for deplafonnees)
                        max_b1 = max(bases1)
                        max_b2 = max(bases2)
                        ecart = abs(max_b1 - max_b2)

                        if ecart > TOLERANCE_MONTANT:
                            ecart_pct = ecart_relatif(max_b1, max_b2)
                            if ecart_pct > TOLERANCE_ARRONDI_PCT:
                                findings.append(Finding(
                                    categorie=FindingCategory.INCOHERENCE,
                                    severite=Severity.HAUTE if ecart > Decimal("100") else Severity.MOYENNE,
                                    titre=f"Base brute divergente pour NIR {nir[:5]}... entre documents",
                                    description=(
                                        f"La base brute maximale pour le NIR {nir} differe : "
                                        f"{formater_montant(max_b1)} dans {label1} vs "
                                        f"{formater_montant(max_b2)} dans {label2}. "
                                        f"Ecart : {formater_montant(ecart)} ({ecart_pct:.2%})."
                                    ),
                                    valeur_constatee=str(max_b1),
                                    valeur_attendue=str(max_b2),
                                    montant_impact=ecart,
                                    score_risque=60,
                                    recommandation=(
                                        "Verifier la base brute de cet employe dans les deux "
                                        "systemes (paie et DSN). Corriger la source en ecart."
                                    ),
                                    detecte_par=self.nom,
                                    documents_concernes=[d1.source_document_id, d2.source_document_id],
                                    details_technique=_details_technique(
                                        annee=annee, periode=per,
                                        document=f"{label1} vs {label2}",
                                        rubrique="Base brute employe",
                                        extra={"nir": nir},
                                    ),
                                ))

        return findings

    # =================================================================
    # 6. Totaux et sous-totaux
    # =================================================================

    def _verifier_totaux_sous_totaux(self, decl: Declaration) -> list[Finding]:
        """Verifie que la somme des cotisations individuelles correspond
        aux totaux declares (masse salariale, montant total patronal, etc.)."""
        findings: list[Finding] = []
        annee, per = _annee_periode(decl)
        doc_label = _doc_label(decl)

        if not decl.cotisations:
            return findings

        # -- Somme des montants patronaux par type de cotisation --
        par_type: dict[ContributionType, list[Cotisation]] = defaultdict(list)
        for c in decl.cotisations:
            par_type[c.type_cotisation].append(c)

        # Verification : base brute * taux = montant (pour chaque cotisation)
        for c in decl.cotisations:
            if c.base_brute > 0 and c.taux_patronal > 0 and c.montant_patronal > 0:
                montant_calcule = (c.base_brute * c.taux_patronal).quantize(
                    Decimal("0.01"), ROUND_HALF_UP,
                )
                ecart = abs(montant_calcule - c.montant_patronal)
                # Allow slightly more tolerance for rounding
                if ecart > Decimal("1.00"):
                    findings.append(Finding(
                        categorie=FindingCategory.INCOHERENCE,
                        severite=Severity.MOYENNE,
                        titre=f"Ecart calcul cotisation {c.type_cotisation.value} (base x taux != montant)",
                        description=(
                            f"Pour {c.type_cotisation.value} : base {formater_montant(c.base_brute)} "
                            f"x taux {c.taux_patronal} = {formater_montant(montant_calcule)}, "
                            f"mais montant declare = {formater_montant(c.montant_patronal)}. "
                            f"Ecart : {formater_montant(ecart)}."
                        ),
                        valeur_constatee=str(c.montant_patronal),
                        valeur_attendue=str(montant_calcule),
                        montant_impact=ecart,
                        score_risque=50,
                        recommandation=(
                            f"Verifier le calcul de la cotisation {c.type_cotisation.value}. "
                            f"S'assurer que base x taux = montant declare."
                        ),
                        detecte_par=self.nom,
                        documents_concernes=[decl.source_document_id],
                        details_technique=_details_technique(
                            annee=annee, periode=per, document=doc_label,
                            rubrique=c.type_cotisation.value,
                            extra={"employe_id": c.employe_id},
                        ),
                    ))

        # -- Verification : somme individuelle = masse salariale --
        # Approche : somme des bases brutes uniques par employe devrait ~ masse salariale
        if decl.masse_salariale_brute > 0 and decl.employes:
            cots_emp = _cotisations_par_employe(decl)
            somme_bases_employes = Decimal("0")
            for eid, cots_list in cots_emp.items():
                bases_emp = [c.base_brute for c in cots_list if c.base_brute > 0]
                if bases_emp:
                    # The max base per employee represents the brut mensuel
                    somme_bases_employes += max(bases_emp)

            if somme_bases_employes > 0:
                ecart = abs(decl.masse_salariale_brute - somme_bases_employes)
                ecart_pct = ecart_relatif(decl.masse_salariale_brute, somme_bases_employes)
                if ecart_pct > TOLERANCE_ARRONDI_PCT and ecart > Decimal("10"):
                    findings.append(Finding(
                        categorie=FindingCategory.INCOHERENCE,
                        severite=Severity.HAUTE if ecart_pct > Decimal("0.05") else Severity.MOYENNE,
                        titre=f"Ecart masse salariale vs somme bases individuelles ({doc_label})",
                        description=(
                            f"Masse salariale declaree : {formater_montant(decl.masse_salariale_brute)}. "
                            f"Somme des bases brutes individuelles : {formater_montant(somme_bases_employes)}. "
                            f"Ecart : {formater_montant(ecart)} ({ecart_pct:.2%})."
                        ),
                        valeur_constatee=str(decl.masse_salariale_brute),
                        valeur_attendue=str(somme_bases_employes),
                        montant_impact=ecart,
                        score_risque=65,
                        recommandation=(
                            "Verifier que la masse salariale brute declaree correspond "
                            "bien a la somme des salaires bruts individuels."
                        ),
                        detecte_par=self.nom,
                        documents_concernes=[decl.source_document_id],
                        details_technique=_details_technique(
                            annee=annee, periode=per, document=doc_label,
                            rubrique="Masse salariale vs bases individuelles",
                        ),
                    ))

        # -- Somme montants patronaux par type --
        total_patronal_global = sum(
            c.montant_patronal for c in decl.cotisations if c.montant_patronal > 0
        )
        total_salarial_global = sum(
            c.montant_salarial for c in decl.cotisations if c.montant_salarial > 0
        )

        # Cross-check : for each contribution type, sum of individual cotisations
        for ct, cots_list in par_type.items():
            if len(cots_list) < 2:
                continue
            somme_patronal_type = sum(c.montant_patronal for c in cots_list)
            somme_salarial_type = sum(c.montant_salarial for c in cots_list)

            # Check if any single cotisation in this type has a suspiciously
            # large share (might be a total line mixed with individual lines)
            for c in cots_list:
                if c.montant_patronal > 0 and somme_patronal_type > 0:
                    ratio = c.montant_patronal / somme_patronal_type
                    # If one line represents > 45% and there are 3+ lines,
                    # it may be a total mixed with individuals
                    if ratio > Decimal("0.45") and len(cots_list) >= 3:
                        remaining = somme_patronal_type - c.montant_patronal
                        ecart_vs_total = abs(c.montant_patronal - remaining)
                        if ecart_vs_total < c.montant_patronal * Decimal("0.1"):
                            findings.append(Finding(
                                categorie=FindingCategory.ANOMALIE,
                                severite=Severity.MOYENNE,
                                titre=f"Doublon possible total/detail pour {ct.value}",
                                description=(
                                    f"Une ligne {ct.value} ({formater_montant(c.montant_patronal)}) "
                                    f"semble etre un total alors que d'autres lignes du meme type "
                                    f"existent (somme restante : {formater_montant(remaining)}). "
                                    f"Risque de double comptage."
                                ),
                                montant_impact=c.montant_patronal,
                                score_risque=55,
                                recommandation=(
                                    f"Verifier s'il y a une ligne de total melangee aux lignes "
                                    f"individuelles pour {ct.value}. Retirer le doublon le cas echeant."
                                ),
                                detecte_par=self.nom,
                                documents_concernes=[decl.source_document_id],
                                details_technique=_details_technique(
                                    annee=annee, periode=per, document=doc_label,
                                    rubrique=ct.value,
                                ),
                            ))
                            break  # one finding per type

        # -- Verification S89 : totaux declares vs totaux calcules --
        meta = getattr(decl, "metadata", {}) or {}
        s89_cot = meta.get("s89_total_cotisations")
        s89_brut = meta.get("s89_total_brut")

        if s89_cot is not None and total_patronal_global > 0:
            s89_cot_dec = Decimal(str(s89_cot))
            ecart_cot = abs(s89_cot_dec - total_patronal_global)
            if ecart_cot > Decimal("1.00"):
                ecart_pct = ecart_relatif(s89_cot_dec, total_patronal_global)
                findings.append(Finding(
                    categorie=FindingCategory.INCOHERENCE,
                    severite=Severity.HAUTE if ecart_pct > Decimal("0.05") else Severity.MOYENNE,
                    titre=f"Ecart total S89 cotisations vs somme individuelle ({doc_label})",
                    description=(
                        f"Total cotisations declare (S89) : {formater_montant(s89_cot_dec)}. "
                        f"Somme des cotisations individuelles (S81) : {formater_montant(total_patronal_global)}. "
                        f"Ecart : {formater_montant(ecart_cot)} ({ecart_pct:.2%})."
                    ),
                    valeur_constatee=str(s89_cot_dec),
                    valeur_attendue=str(total_patronal_global),
                    montant_impact=ecart_cot,
                    score_risque=70,
                    recommandation=(
                        "Verifier la coherence entre le total de cotisations "
                        "du bloc S89 et la somme des cotisations individuelles S81."
                    ),
                    detecte_par=self.nom,
                    documents_concernes=[decl.source_document_id],
                    details_technique=_details_technique(
                        annee=annee, periode=per, document=doc_label,
                        rubrique="S89 vs S81 totaux cotisations",
                    ),
                ))

        if s89_brut is not None and decl.masse_salariale_brute > 0:
            s89_brut_dec = Decimal(str(s89_brut))
            ecart_brut = abs(s89_brut_dec - decl.masse_salariale_brute)
            if ecart_brut > Decimal("10.00"):
                ecart_pct = ecart_relatif(s89_brut_dec, decl.masse_salariale_brute)
                findings.append(Finding(
                    categorie=FindingCategory.INCOHERENCE,
                    severite=Severity.HAUTE if ecart_pct > Decimal("0.05") else Severity.MOYENNE,
                    titre=f"Ecart total S89 brut vs masse salariale ({doc_label})",
                    description=(
                        f"Total brut declare (S89) : {formater_montant(s89_brut_dec)}. "
                        f"Masse salariale calculee : {formater_montant(decl.masse_salariale_brute)}. "
                        f"Ecart : {formater_montant(ecart_brut)} ({ecart_pct:.2%})."
                    ),
                    valeur_constatee=str(s89_brut_dec),
                    valeur_attendue=str(decl.masse_salariale_brute),
                    montant_impact=ecart_brut,
                    score_risque=70,
                    recommandation=(
                        "Verifier la coherence entre le total brut declare "
                        "dans le bloc S89 et la masse salariale calculee."
                    ),
                    detecte_par=self.nom,
                    documents_concernes=[decl.source_document_id],
                    details_technique=_details_technique(
                        annee=annee, periode=per, document=doc_label,
                        rubrique="S89 vs masse salariale brute",
                    ),
                ))

        return findings

    # =================================================================
    # 7. Controles specifiques DSN
    # =================================================================

    def _verifier_dsn_specifique(self, decl: Declaration) -> list[Finding]:
        """Controles propres aux declarations DSN :
        - Verification des codes CTP
        - Blocs obligatoires
        - Coherence SIRET
        """
        findings: list[Finding] = []
        annee, per = _annee_periode(decl)
        doc_label = _doc_label(decl)

        # -- SIRET coherence + Luhn --
        if decl.employeur and decl.employeur.siret:
            from urssaf_analyzer.utils.number_utils import valider_siret
            siret = decl.employeur.siret.replace(" ", "")
            # SIRET = 14 digits
            if len(siret) != 14 or not siret.isdigit():
                findings.append(Finding(
                    categorie=FindingCategory.ANOMALIE,
                    severite=Severity.HAUTE,
                    titre=f"SIRET invalide dans la DSN : {siret}",
                    description=(
                        f"Le SIRET '{siret}' ne respecte pas le format attendu "
                        f"(14 chiffres). Longueur constatee : {len(siret)}."
                    ),
                    valeur_constatee=siret,
                    valeur_attendue="14 chiffres",
                    montant_impact=Decimal("0"),
                    score_risque=80,
                    recommandation=(
                        "Corriger le SIRET dans la DSN. Un SIRET invalide "
                        "entraine un rejet par l'URSSAF."
                    ),
                    detecte_par=self.nom,
                    documents_concernes=[decl.source_document_id],
                    reference_legale="Art. R243-14 CSS",
                    details_technique=_details_technique(
                        annee=annee, periode=per, document=doc_label,
                        rubrique="SIRET employeur",
                    ),
                ))
            elif not valider_siret(siret):
                findings.append(Finding(
                    categorie=FindingCategory.ANOMALIE,
                    severite=Severity.HAUTE,
                    titre=f"SIRET invalide (cle Luhn) : {siret}",
                    description=(
                        f"Le SIRET '{siret}' echoue a la validation Luhn. "
                        f"La somme de controle est incorrecte, ce qui indique "
                        f"une erreur de saisie."
                    ),
                    valeur_constatee=siret,
                    valeur_attendue="SIRET avec cle Luhn valide",
                    montant_impact=Decimal("0"),
                    score_risque=80,
                    recommandation=(
                        "Verifier le SIRET sur societe.com ou annuaire-entreprises.data.gouv.fr. "
                        "Un SIRET invalide entraine un rejet DSN."
                    ),
                    detecte_par=self.nom,
                    documents_concernes=[decl.source_document_id],
                    reference_legale="Art. R243-14 CSS - Decret SIRET (INSEE)",
                    details_technique=_details_technique(
                        annee=annee, periode=per, document=doc_label,
                        rubrique="SIRET employeur",
                    ),
                ))

            # SIREN coherence : first 9 digits of SIRET should match SIREN
            if decl.employeur.siren:
                siren = decl.employeur.siren.replace(" ", "")
                if len(siret) >= 9 and siren and siret[:9] != siren:
                    findings.append(Finding(
                        categorie=FindingCategory.INCOHERENCE,
                        severite=Severity.HAUTE,
                        titre="Incoherence SIREN / SIRET dans la DSN",
                        description=(
                            f"Le SIREN ({siren}) ne correspond pas aux 9 premiers "
                            f"chiffres du SIRET ({siret[:9]}). "
                            f"Ces deux identifiants doivent etre coherents."
                        ),
                        valeur_constatee=siret[:9],
                        valeur_attendue=siren,
                        montant_impact=Decimal("0"),
                        score_risque=85,
                        recommandation=(
                            "Corriger le SIREN ou le SIRET pour assurer la coherence. "
                            "Verifier l'inscription au repertoire SIRENE."
                        ),
                        detecte_par=self.nom,
                        documents_concernes=[decl.source_document_id],
                        details_technique=_details_technique(
                            annee=annee, periode=per, document=doc_label,
                            rubrique="SIREN / SIRET",
                        ),
                    ))

        # -- SIRET coherence entre cotisations et employeur --
        if decl.employeur and decl.employeur.siret:
            emp_siret = decl.employeur.siret.replace(" ", "")
            for c in decl.cotisations:
                if c.employeur_id and c.employeur_id != decl.employeur.id:
                    # Different employeur_id on a cotisation -> potential multi-etablissement issue
                    findings.append(Finding(
                        categorie=FindingCategory.ANOMALIE,
                        severite=Severity.MOYENNE,
                        titre=f"Cotisation {c.type_cotisation.value} rattachee a un autre employeur",
                        description=(
                            f"La cotisation {c.type_cotisation.value} est rattachee a "
                            f"l'employeur {c.employeur_id} alors que la declaration "
                            f"est emise par {decl.employeur.id} (SIRET {emp_siret})."
                        ),
                        montant_impact=c.montant_patronal,
                        score_risque=50,
                        recommandation=(
                            "Verifier le rattachement des cotisations a l'etablissement "
                            "correct (SIRET). En multi-etablissement, chaque DSN doit "
                            "etre emise par le bon etablissement."
                        ),
                        detecte_par=self.nom,
                        documents_concernes=[decl.source_document_id],
                        details_technique=_details_technique(
                            annee=annee, periode=per, document=doc_label,
                            rubrique=c.type_cotisation.value,
                        ),
                    ))

        # -- Blocs obligatoires (via metadata + inference from data) --
        blocs_presents = set()
        if hasattr(decl, "metadata") and isinstance(getattr(decl, "metadata", None), dict):
            blocs_presents = set(decl.metadata.get("blocs_dsn", []))

        # Infer present blocs from actual declaration data
        if decl.employeur and decl.employeur.siret:
            blocs_presents.add("S20")  # Entreprise present
            blocs_presents.add("S21.G00.06")  # Etablissement (SIRET present)
        if decl.employes:
            blocs_presents.add("S21.G00.30")  # Individu (employes present)
            for emp_dsn in decl.employes:
                if emp_dsn.date_embauche or emp_dsn.statut:
                    blocs_presents.add("S21.G00.40")  # Contrat
                    break
        if decl.cotisations:
            blocs_presents.add("S21.G00.81")  # Cotisation individuelle
            blocs_presents.add("S21.G00.78")  # Base assujettie
            blocs_presents.add("S21.G00.22")  # Cotisation agregee
        if decl.masse_salariale_brute > 0:
            blocs_presents.add("S21.G00.51")  # Remuneration
            blocs_presents.add("S89")  # Totaux

        if blocs_presents:
            blocs_manquants = _BLOCS_DSN_OBLIGATOIRES - blocs_presents
            if blocs_manquants:
                findings.append(Finding(
                    categorie=FindingCategory.DONNEE_MANQUANTE,
                    severite=Severity.HAUTE,
                    titre=f"Blocs DSN obligatoires manquants ({len(blocs_manquants)})",
                    description=(
                        f"Les blocs DSN suivants sont obligatoires mais absents : "
                        f"{', '.join(sorted(blocs_manquants))}."
                    ),
                    montant_impact=Decimal("0"),
                    score_risque=80,
                    recommandation=(
                        "Completer la DSN avec les blocs obligatoires manquants "
                        "avant envoi. Une DSN incomplete sera rejetee par Net-Entreprises."
                    ),
                    detecte_par=self.nom,
                    documents_concernes=[decl.source_document_id],
                    reference_legale="Cahier technique DSN (norme NEODeS)",
                    details_technique=_details_technique(
                        annee=annee, periode=per, document=doc_label,
                        rubrique="Blocs DSN",
                        extra={"blocs_manquants": sorted(blocs_manquants)},
                    ),
                ))

        # -- CTP codes : check metadata for CTP information --
        ctp_codes = set()
        if hasattr(decl, "metadata") and isinstance(getattr(decl, "metadata", None), dict):
            ctp_codes = set(decl.metadata.get("codes_ctp", []))

        if ctp_codes:
            # Validate CTP format : 3 digits or 3 digits + letter
            for ctp in ctp_codes:
                ctp_str = str(ctp).strip()
                if not (
                    (len(ctp_str) == 3 and ctp_str.isdigit())
                    or (len(ctp_str) == 4 and ctp_str[:3].isdigit() and ctp_str[3].isalpha())
                ):
                    findings.append(Finding(
                        categorie=FindingCategory.ANOMALIE,
                        severite=Severity.MOYENNE,
                        titre=f"Code CTP invalide : {ctp_str}",
                        description=(
                            f"Le code CTP '{ctp_str}' ne respecte pas le format attendu "
                            f"(3 chiffres ou 3 chiffres + 1 lettre)."
                        ),
                        valeur_constatee=ctp_str,
                        montant_impact=Decimal("0"),
                        score_risque=60,
                        recommandation=(
                            "Corriger le code CTP. Consulter la table des CTP "
                            "sur net-entreprises.fr pour le code applicable."
                        ),
                        detecte_par=self.nom,
                        documents_concernes=[decl.source_document_id],
                        reference_legale="Cahier technique DSN - Table CTP",
                        details_technique=_details_technique(
                            annee=annee, periode=per, document=doc_label,
                            rubrique=f"Code CTP {ctp_str}",
                        ),
                    ))

        # -- Presence d'au moins un employe dans une DSN mensuelle --
        if not decl.employes:
            findings.append(Finding(
                categorie=FindingCategory.DONNEE_MANQUANTE,
                severite=Severity.HAUTE,
                titre="DSN sans aucun employe declare",
                description=(
                    f"La declaration DSN {doc_label} ne contient aucun bloc "
                    f"individuel (employe). Une DSN mensuelle doit contenir "
                    f"au moins un salarie."
                ),
                montant_impact=Decimal("0"),
                score_risque=85,
                recommandation=(
                    "Ajouter les blocs individuels (S21.G00.30 et suivants) "
                    "pour chaque salarie de l'etablissement."
                ),
                detecte_par=self.nom,
                documents_concernes=[decl.source_document_id],
                reference_legale="Art. R243-14 CSS, Cahier technique DSN",
                details_technique=_details_technique(
                    annee=annee, periode=per, document=doc_label,
                    rubrique="Blocs individuels DSN",
                ),
            ))

        # -- Presence de cotisations dans une DSN --
        if not decl.cotisations:
            findings.append(Finding(
                categorie=FindingCategory.DONNEE_MANQUANTE,
                severite=Severity.HAUTE,
                titre="DSN sans aucune cotisation declaree",
                description=(
                    f"La declaration DSN {doc_label} ne contient aucune "
                    f"cotisation (ni individuelle, ni agregee). "
                    f"Cela est anormal pour une DSN mensuelle."
                ),
                montant_impact=Decimal("0"),
                score_risque=80,
                recommandation=(
                    "Verifier l'extraction / le parsing de la DSN. "
                    "Completer les blocs S21.G00.78, S21.G00.81, S21.G00.22, S21.G00.23."
                ),
                detecte_par=self.nom,
                documents_concernes=[decl.source_document_id],
                details_technique=_details_technique(
                    annee=annee, periode=per, document=doc_label,
                    rubrique="Cotisations DSN",
                ),
            ))

        # -- CTP obligatoires : CTP 100 (cas general) doit etre present --
        _CTP_OBLIGATOIRES = {"100"}  # CTP 100 = cas general regime general
        if ctp_codes and _CTP_OBLIGATOIRES - ctp_codes:
            ctp_manquants = _CTP_OBLIGATOIRES - ctp_codes
            findings.append(Finding(
                categorie=FindingCategory.DONNEE_MANQUANTE,
                severite=Severity.MOYENNE,
                titre=f"CTP obligatoire(s) manquant(s) : {', '.join(sorted(ctp_manquants))}",
                description=(
                    f"Le CTP 100 (regime general - cas general) est le code de base "
                    f"pour toute DSN mensuelle. Son absence peut indiquer une erreur "
                    f"de parametrage dans le logiciel de paie."
                ),
                montant_impact=Decimal("0"),
                score_risque=65,
                recommandation=(
                    "Verifier les codes CTP declares dans la DSN. "
                    "Le CTP 100 doit etre present pour les cotisations regime general."
                ),
                detecte_par=self.nom,
                documents_concernes=[decl.source_document_id],
                reference_legale="Table des CTP URSSAF - net-entreprises.fr",
                details_technique=_details_technique(
                    annee=annee, periode=per, document=doc_label,
                    rubrique="CTP obligatoires",
                    extra={"ctp_manquants": sorted(ctp_manquants), "ctp_presents": sorted(str(c) for c in ctp_codes)},
                ),
            ))

        # -- Coherence employe / contrat : date embauche vs periode DSN --
        for emp in decl.employes:
            if emp.date_embauche and decl.periode:
                try:
                    from datetime import date as dt_date
                    if isinstance(emp.date_embauche, str):
                        dh = dt_date.fromisoformat(emp.date_embauche)
                    else:
                        dh = emp.date_embauche
                    # Parse periode (YYYY-MM format)
                    per_str = str(decl.periode).strip()
                    if len(per_str) >= 7:
                        per_year = int(per_str[:4])
                        per_month = int(per_str[5:7])
                        # Si date embauche > fin de la periode declaree, incoherence
                        import calendar
                        _, dernier_jour = calendar.monthrange(per_year, per_month)
                        fin_periode = dt_date(per_year, per_month, dernier_jour)
                        if dh > fin_periode:
                            findings.append(Finding(
                                categorie=FindingCategory.INCOHERENCE,
                                severite=Severity.HAUTE,
                                titre=f"Date embauche future dans DSN ({emp.prenom} {emp.nom})",
                                description=(
                                    f"Le salarie {emp.prenom} {emp.nom} a une date d'embauche "
                                    f"({dh.isoformat()}) posterieure a la fin de la periode "
                                    f"declaree ({fin_periode.isoformat()}).\\n\\n"
                                    f"Un salarie ne peut pas apparaitre dans une DSN "
                                    f"pour une periode anterieure a son embauche."
                                ),
                                valeur_constatee=dh.isoformat(),
                                valeur_attendue=f"<= {fin_periode.isoformat()}",
                                montant_impact=Decimal("0"),
                                score_risque=75,
                                recommandation=(
                                    "Verifier la date d'embauche du salarie et la periode "
                                    "de la DSN. Corriger l'une ou l'autre si necessaire."
                                ),
                                detecte_par=self.nom,
                                documents_concernes=[decl.source_document_id],
                                reference_legale="Cahier technique DSN - Bloc S21.G00.40",
                                details_technique=_details_technique(
                                    annee=annee, periode=per, document=doc_label,
                                    rubrique=f"Date embauche {emp.prenom} {emp.nom}",
                                ),
                            ))
                except (ValueError, TypeError, AttributeError):
                    pass

        # -- Coherence base assujettie S78 / cotisation individuelle S81 --
        # Verifier que le total des cotisations par employe correspond a une base coherente
        if decl.employes and decl.cotisations:
            for emp in decl.employes:
                emp_cots = [c for c in decl.cotisations if c.employe_id == emp.id]
                if len(emp_cots) >= 2:
                    bases = [c.base_brute for c in emp_cots if c.base_brute > 0]
                    if bases:
                        base_max = max(bases)
                        base_min = min(bases)
                        # Les bases doivent etre coherentes (hors plafonnement)
                        # Si ecart > 3x la plus petite, signaler
                        if base_min > 0 and base_max > base_min * 3 and base_max > PASS_MENSUEL:
                            findings.append(Finding(
                                categorie=FindingCategory.INCOHERENCE,
                                severite=Severity.MOYENNE,
                                titre=f"Bases assujetties incoherentes ({emp.prenom} {emp.nom})",
                                description=(
                                    f"Pour {emp.prenom} {emp.nom}, les bases de cotisations "
                                    f"presentent un ecart important : "
                                    f"min={base_min:.2f} EUR, max={base_max:.2f} EUR.\\n\\n"
                                    f"Cet ecart peut etre normal (plafonnement PASS) "
                                    f"mais merite verification."
                                ),
                                valeur_constatee=f"min={base_min:.2f}, max={base_max:.2f}",
                                montant_impact=Decimal("0"),
                                score_risque=45,
                                recommandation=(
                                    "Verifier les assiettes de cotisations. L'ecart peut etre "
                                    "lie au plafonnement PASS ou a une erreur de parametrage."
                                ),
                                detecte_par=self.nom,
                                documents_concernes=[decl.source_document_id],
                                reference_legale="Art. L242-1 CSS - Cahier technique DSN bloc S21.G00.78/S21.G00.81",
                                details_technique=_details_technique(
                                    annee=annee, periode=per, document=doc_label,
                                    rubrique=f"Bases cotisations {emp.prenom} {emp.nom}",
                                ),
                            ))

        return findings

    def _verifier_coherence_inter_documents(self, declarations: list[Declaration]) -> list[Finding]:
        """Compare les declarations entre elles."""
        findings: list[Finding] = []

        par_periode = self._regrouper_par_periode(declarations)

        for periode_key, decls in par_periode.items():
            if len(decls) < 2:
                continue

            # Comparer les masses salariales entre documents de meme periode
            masses = [(d, d.masse_salariale_brute) for d in decls if d.masse_salariale_brute > 0]
            if len(masses) >= 2:
                for i in range(len(masses)):
                    for j in range(i + 1, len(masses)):
                        d1, m1 = masses[i]
                        d2, m2 = masses[j]
                        annee, per = _annee_periode(d1)
                        label1, label2 = _doc_label(d1), _doc_label(d2)
                        ecart = ecart_relatif(m1, m2)
                        if ecart > TOLERANCE_ARRONDI_PCT:
                            montant_ecart = abs(m1 - m2)
                            findings.append(Finding(
                                categorie=FindingCategory.INCOHERENCE,
                                severite=Severity.HAUTE,
                                titre=f"Masse salariale incoherente : {label1} vs {label2}",
                                description=(
                                    f"Ecart de {ecart:.1%} entre les masses salariales "
                                    f"declarees pour la meme periode ({per}). "
                                    f"{label1} : {formater_montant(m1)}, "
                                    f"{label2} : {formater_montant(m2)}. "
                                    f"Ecart : {formater_montant(montant_ecart)}."
                                ),
                                montant_impact=montant_ecart,
                                score_risque=75,
                                recommandation=(
                                    "Identifier la source de l'ecart entre les deux documents et "
                                    "reconcilier les declarations. Verifier les primes, "
                                    "heures supplementaires ou elements variables."
                                ),
                                detecte_par=self.nom,
                                documents_concernes=[d1.source_document_id, d2.source_document_id],
                                details_technique=_details_technique(
                                    annee=annee, periode=per,
                                    document=f"{label1} vs {label2}",
                                    rubrique="Masse salariale brute",
                                ),
                            ))

            # Comparer les effectifs entre documents de meme periode
            effectifs = [
                (d, d.effectif_declare)
                for d in decls
                if d.effectif_declare > 0
            ]
            if len(effectifs) >= 2:
                for i in range(len(effectifs)):
                    for j in range(i + 1, len(effectifs)):
                        d1, e1 = effectifs[i]
                        d2, e2 = effectifs[j]
                        if e1 != e2:
                            annee, per = _annee_periode(d1)
                            label1, label2 = _doc_label(d1), _doc_label(d2)
                            findings.append(Finding(
                                categorie=FindingCategory.INCOHERENCE,
                                severite=Severity.MOYENNE,
                                titre=f"Effectif divergent : {label1} ({e1}) vs {label2} ({e2})",
                                description=(
                                    f"L'effectif declare differe entre {label1} ({e1}) "
                                    f"et {label2} ({e2}) pour la meme periode ({per})."
                                ),
                                valeur_constatee=str(e1),
                                valeur_attendue=str(e2),
                                montant_impact=Decimal("0"),
                                score_risque=50,
                                recommandation=(
                                    "Harmoniser l'effectif declare entre les documents. "
                                    "L'effectif doit correspondre aux salaries effectivement presents."
                                ),
                                detecte_par=self.nom,
                                documents_concernes=[d1.source_document_id, d2.source_document_id],
                                details_technique=_details_technique(
                                    annee=annee, periode=per,
                                    document=f"{label1} vs {label2}",
                                    rubrique="Effectif declare",
                                ),
                            ))

        return findings

    # =================================================================
    # Coherence temporelle (existant, ameliore)
    # =================================================================

    def _verifier_coherence_temporelle(self, declarations: list[Declaration]) -> list[Finding]:
        """Verifie la coherence entre periodes successives."""
        findings: list[Finding] = []

        decls_triees = sorted(
            [d for d in declarations if d.periode],
            key=lambda d: d.periode.debut,
        )

        for i in range(1, len(decls_triees)):
            prev = decls_triees[i - 1]
            curr = decls_triees[i]
            annee, per_curr = _annee_periode(curr)
            _, per_prev = _annee_periode(prev)
            label_prev, label_curr = _doc_label(prev), _doc_label(curr)

            if prev.masse_salariale_brute > 0 and curr.masse_salariale_brute > 0:
                variation = ecart_relatif(curr.masse_salariale_brute, prev.masse_salariale_brute)
                if variation > Decimal("0.5"):  # Variation > 50%
                    ecart_abs = abs(curr.masse_salariale_brute - prev.masse_salariale_brute)
                    findings.append(Finding(
                        categorie=FindingCategory.ANOMALIE,
                        severite=Severity.MOYENNE,
                        titre=f"Variation masse salariale {variation:.0%} entre periodes",
                        description=(
                            f"La masse salariale varie de {variation:.1%} entre "
                            f"{per_prev} ({formater_montant(prev.masse_salariale_brute)}) et "
                            f"{per_curr} ({formater_montant(curr.masse_salariale_brute)}). "
                            f"Ecart absolu : {formater_montant(ecart_abs)}."
                        ),
                        montant_impact=ecart_abs,
                        score_risque=45,
                        recommandation=(
                            "Verifier si cette variation est justifiee (embauches, licenciements, "
                            "primes exceptionnelles, regularisations)."
                        ),
                        detecte_par=self.nom,
                        documents_concernes=[prev.source_document_id, curr.source_document_id],
                        details_technique=_details_technique(
                            annee=annee, periode=f"{per_prev} -> {per_curr}",
                            document=f"{label_prev} -> {label_curr}",
                            rubrique="Masse salariale brute",
                        ),
                    ))

            # Effectif variation
            if prev.effectif_declare > 0 and curr.effectif_declare > 0:
                eff_variation = abs(curr.effectif_declare - prev.effectif_declare)
                eff_pct = Decimal(str(eff_variation)) / Decimal(str(prev.effectif_declare))
                if eff_pct > Decimal("0.3") and eff_variation > 3:
                    findings.append(Finding(
                        categorie=FindingCategory.ANOMALIE,
                        severite=Severity.MOYENNE,
                        titre=f"Variation effectif {eff_pct:.0%} entre periodes ({eff_variation} personnes)",
                        description=(
                            f"L'effectif passe de {prev.effectif_declare} a "
                            f"{curr.effectif_declare} entre {per_prev} et {per_curr} "
                            f"(variation de {eff_variation} personnes, {eff_pct:.1%})."
                        ),
                        valeur_constatee=str(curr.effectif_declare),
                        valeur_attendue=str(prev.effectif_declare),
                        montant_impact=Decimal("0"),
                        score_risque=40,
                        recommandation=(
                            "Verifier si cette variation d'effectif est justifiee "
                            "(plan social, recrutement massif, saisonnalite)."
                        ),
                        detecte_par=self.nom,
                        documents_concernes=[prev.source_document_id, curr.source_document_id],
                        details_technique=_details_technique(
                            annee=annee, periode=f"{per_prev} -> {per_curr}",
                            document=f"{label_prev} -> {label_curr}",
                            rubrique="Effectif declare",
                        ),
                    ))

        return findings

    # =================================================================
    # 8. SIRET/SIREN cross-document
    # =================================================================

    def _comparer_siret_inter_documents(
        self, declarations: list[Declaration],
    ) -> list[Finding]:
        """Detecte les SIRET/SIREN differents entre documents de meme periode."""
        findings: list[Finding] = []
        par_periode = self._regrouper_par_periode(declarations)

        for _, decls in par_periode.items():
            if len(decls) < 2:
                continue

            sirets_vus: dict[str, Declaration] = {}
            for decl in decls:
                if not decl.employeur or not decl.employeur.siret:
                    continue
                siret = decl.employeur.siret.replace(" ", "")
                if sirets_vus and siret not in sirets_vus:
                    # SIRET different d'un document deja vu pour la meme periode
                    premier_decl = next(iter(sirets_vus.values()))
                    premier_siret = next(iter(sirets_vus.keys()))
                    annee, per = _annee_periode(decl)
                    findings.append(Finding(
                        categorie=FindingCategory.INCOHERENCE,
                        severite=Severity.HAUTE,
                        titre="SIRET divergent entre documents de meme periode",
                        description=(
                            f"Le SIRET differe entre {_doc_label(premier_decl)} "
                            f"({premier_siret}) et {_doc_label(decl)} ({siret}) "
                            f"pour la meme periode ({per}). Les deux documents "
                            f"devraient concerner le meme etablissement."
                        ),
                        valeur_constatee=siret,
                        valeur_attendue=premier_siret,
                        montant_impact=Decimal("0"),
                        score_risque=80,
                        recommandation=(
                            "Verifier que les documents concernent le meme "
                            "etablissement. Si multi-etablissement, separer les "
                            "analyses par SIRET."
                        ),
                        detecte_par=self.nom,
                        documents_concernes=[
                            premier_decl.source_document_id,
                            decl.source_document_id,
                        ],
                        reference_legale="Art. R243-14 CSS - Identification de l'etablissement",
                        details_technique=_details_technique(
                            annee=annee, periode=per,
                            document=f"{_doc_label(premier_decl)} vs {_doc_label(decl)}",
                            rubrique="SIRET employeur",
                        ),
                    ))
                sirets_vus[siret] = decl

        return findings

    # =================================================================
    # 9. Taux AT/MP cross-document
    # =================================================================

    def _comparer_taux_at_inter_documents(
        self, declarations: list[Declaration],
    ) -> list[Finding]:
        """Detecte un taux AT/MP different entre documents de meme periode."""
        findings: list[Finding] = []
        par_periode = self._regrouper_par_periode(declarations)

        for _, decls in par_periode.items():
            if len(decls) < 2:
                continue

            taux_at_vus: list[tuple[Decimal, Declaration]] = []
            for decl in decls:
                if decl.employeur and decl.employeur.taux_at > 0:
                    taux_at_vus.append((decl.employeur.taux_at, decl))

            if len(taux_at_vus) < 2:
                continue

            for i in range(len(taux_at_vus)):
                for j in range(i + 1, len(taux_at_vus)):
                    t1, d1 = taux_at_vus[i]
                    t2, d2 = taux_at_vus[j]
                    if abs(t1 - t2) > TOLERANCE_TAUX:
                        annee, per = _annee_periode(d1)
                        label1, label2 = _doc_label(d1), _doc_label(d2)
                        findings.append(Finding(
                            categorie=FindingCategory.INCOHERENCE,
                            severite=Severity.HAUTE,
                            titre=f"Taux AT/MP divergent entre documents ({t1} vs {t2})",
                            description=(
                                f"Le taux AT/MP differe entre {label1} "
                                f"({float(t1)*100:.2f}%) et {label2} "
                                f"({float(t2)*100:.2f}%) pour la meme periode. "
                                f"Le taux AT/MP est fixe par la CARSAT pour "
                                f"chaque etablissement et doit etre identique "
                                f"sur tous les documents d'une meme periode."
                            ),
                            valeur_constatee=f"{float(t1)*100:.2f}%",
                            valeur_attendue=f"{float(t2)*100:.2f}%",
                            montant_impact=Decimal("0"),
                            score_risque=70,
                            recommandation=(
                                "Verifier le taux AT/MP sur la notification "
                                "annuelle de la CARSAT et harmoniser les documents."
                            ),
                            detecte_par=self.nom,
                            documents_concernes=[
                                d1.source_document_id, d2.source_document_id,
                            ],
                            reference_legale="CSS art. D242-6-1 - Taux AT/MP notifie",
                            details_technique=_details_technique(
                                annee=annee, periode=per,
                                document=f"{label1} vs {label2}",
                                rubrique="Taux AT/MP employeur",
                            ),
                        ))

        return findings

    # =================================================================
    # 10. Employe details cross-document (temps travail, embauche, convention)
    # =================================================================

    def _comparer_employe_details_inter_documents(
        self, declarations: list[Declaration],
    ) -> list[Finding]:
        """Compare les donnees individuelles des employes entre documents."""
        findings: list[Finding] = []
        par_periode = self._regrouper_par_periode(declarations)

        for _, decls in par_periode.items():
            if len(decls) < 2:
                continue

            for i in range(len(decls)):
                for j in range(i + 1, len(decls)):
                    d1, d2 = decls[i], decls[j]
                    if not d1.employes or not d2.employes:
                        continue

                    nir_d1 = _build_nir_index(d1)
                    nir_d2 = _build_nir_index(d2)
                    nirs_communs = set(nir_d1.keys()) & set(nir_d2.keys())
                    annee, per = _annee_periode(d1)
                    label1, label2 = _doc_label(d1), _doc_label(d2)

                    for nir in nirs_communs:
                        e1, e2 = nir_d1[nir], nir_d2[nir]
                        nom_emp = f"{e1.prenom} {e1.nom}" if e1.nom else f"NIR {nir[:5]}..."

                        # Temps de travail
                        if (e1.temps_travail > 0 and e2.temps_travail > 0
                                and abs(e1.temps_travail - e2.temps_travail) > Decimal("0.01")):
                            findings.append(Finding(
                                categorie=FindingCategory.INCOHERENCE,
                                severite=Severity.HAUTE,
                                titre=f"Temps de travail divergent ({nom_emp})",
                                description=(
                                    f"Le temps de travail de {nom_emp} differe entre "
                                    f"{label1} ({float(e1.temps_travail)*100:.0f}%) et "
                                    f"{label2} ({float(e2.temps_travail)*100:.0f}%). "
                                    f"Cette incoherence impacte le plafonnement PASS, "
                                    f"la proratisation du SMIC, et le calcul des "
                                    f"cotisations plafonnees."
                                ),
                                valeur_constatee=f"{float(e1.temps_travail)*100:.0f}%",
                                valeur_attendue=f"{float(e2.temps_travail)*100:.0f}%",
                                montant_impact=Decimal("0"),
                                score_risque=70,
                                recommandation=(
                                    "Harmoniser le temps de travail entre les documents. "
                                    "Ce parametre impacte le plafonnement PASS et le SMIC."
                                ),
                                detecte_par=self.nom,
                                documents_concernes=[
                                    d1.source_document_id, d2.source_document_id,
                                ],
                                reference_legale="Art. L242-8 CSS - Proratisation du plafond",
                                details_technique=_details_technique(
                                    annee=annee, periode=per,
                                    document=f"{label1} vs {label2}",
                                    rubrique=f"Temps travail {nom_emp}",
                                    extra={"nir": nir},
                                ),
                            ))

                        # Date d'embauche
                        if (e1.date_embauche and e2.date_embauche
                                and e1.date_embauche != e2.date_embauche):
                            findings.append(Finding(
                                categorie=FindingCategory.INCOHERENCE,
                                severite=Severity.MOYENNE,
                                titre=f"Date embauche divergente ({nom_emp})",
                                description=(
                                    f"La date d'embauche de {nom_emp} differe : "
                                    f"{e1.date_embauche} dans {label1} vs "
                                    f"{e2.date_embauche} dans {label2}."
                                ),
                                valeur_constatee=str(e1.date_embauche),
                                valeur_attendue=str(e2.date_embauche),
                                montant_impact=Decimal("0"),
                                score_risque=45,
                                recommandation=(
                                    "Harmoniser la date d'embauche. L'anciennete "
                                    "impacte certains droits et exonerations."
                                ),
                                detecte_par=self.nom,
                                documents_concernes=[
                                    d1.source_document_id, d2.source_document_id,
                                ],
                                details_technique=_details_technique(
                                    annee=annee, periode=per,
                                    document=f"{label1} vs {label2}",
                                    rubrique=f"Date embauche {nom_emp}",
                                    extra={"nir": nir},
                                ),
                            ))

                        # Convention collective
                        if (e1.convention_collective and e2.convention_collective
                                and e1.convention_collective.strip().upper()
                                != e2.convention_collective.strip().upper()):
                            findings.append(Finding(
                                categorie=FindingCategory.INCOHERENCE,
                                severite=Severity.HAUTE,
                                titre=f"Convention collective divergente ({nom_emp})",
                                description=(
                                    f"La convention collective de {nom_emp} differe : "
                                    f"'{e1.convention_collective}' dans {label1} vs "
                                    f"'{e2.convention_collective}' dans {label2}. "
                                    f"La convention collective determine les minima salariaux, "
                                    f"les taux de prevoyance, et d'autres obligations."
                                ),
                                valeur_constatee=e1.convention_collective,
                                valeur_attendue=e2.convention_collective,
                                montant_impact=Decimal("0"),
                                score_risque=65,
                                recommandation=(
                                    "Harmoniser la convention collective entre les "
                                    "documents. Verifier le code IDCC applicable."
                                ),
                                detecte_par=self.nom,
                                documents_concernes=[
                                    d1.source_document_id, d2.source_document_id,
                                ],
                                reference_legale="Art. L2261-2 Code du travail - Convention collective applicable",
                                details_technique=_details_technique(
                                    annee=annee, periode=per,
                                    document=f"{label1} vs {label2}",
                                    rubrique=f"Convention collective {nom_emp}",
                                    extra={"nir": nir},
                                ),
                            ))

                        # Statut (cadre/non-cadre)
                        if (e1.statut and e2.statut
                                and e1.statut.strip().lower() != e2.statut.strip().lower()):
                            findings.append(Finding(
                                categorie=FindingCategory.INCOHERENCE,
                                severite=Severity.HAUTE,
                                titre=f"Statut divergent ({nom_emp})",
                                description=(
                                    f"Le statut de {nom_emp} differe : "
                                    f"'{e1.statut}' dans {label1} vs "
                                    f"'{e2.statut}' dans {label2}. "
                                    f"Le statut cadre/non-cadre impacte les cotisations "
                                    f"de prevoyance (ANI art. 7) et la retraite "
                                    f"complementaire (T1/T2)."
                                ),
                                valeur_constatee=e1.statut,
                                valeur_attendue=e2.statut,
                                montant_impact=Decimal("0"),
                                score_risque=70,
                                recommandation=(
                                    "Verifier le statut reel du salarie et harmoniser. "
                                    "Le statut impacte prevoyance et retraite complementaire."
                                ),
                                detecte_par=self.nom,
                                documents_concernes=[
                                    d1.source_document_id, d2.source_document_id,
                                ],
                                reference_legale="ANI du 17/11/2017 - Classification cadre/non-cadre",
                                details_technique=_details_technique(
                                    annee=annee, periode=per,
                                    document=f"{label1} vs {label2}",
                                    rubrique=f"Statut {nom_emp}",
                                    extra={"nir": nir},
                                ),
                            ))

        return findings

    # =================================================================
    # 11. Totaux patronaux cross-document
    # =================================================================

    def _comparer_totaux_patronaux_inter_documents(
        self, declarations: list[Declaration],
    ) -> list[Finding]:
        """Compare le total des cotisations patronales entre documents."""
        findings: list[Finding] = []
        par_periode = self._regrouper_par_periode(declarations)

        for _, decls in par_periode.items():
            if len(decls) < 2:
                continue

            totaux = []
            for d in decls:
                total_pat = sum(
                    c.montant_patronal for c in d.cotisations
                    if c.montant_patronal > 0
                )
                if total_pat > 0:
                    totaux.append((d, total_pat))

            if len(totaux) < 2:
                continue

            for i in range(len(totaux)):
                for j in range(i + 1, len(totaux)):
                    d1, t1 = totaux[i]
                    d2, t2 = totaux[j]
                    ecart = abs(t1 - t2)
                    if ecart > TOLERANCE_MONTANT:
                        ecart_pct = ecart_relatif(t1, t2)
                        if ecart_pct > TOLERANCE_ARRONDI_PCT:
                            annee, per = _annee_periode(d1)
                            label1, label2 = _doc_label(d1), _doc_label(d2)
                            findings.append(Finding(
                                categorie=FindingCategory.INCOHERENCE,
                                severite=Severity.HAUTE if ecart > Decimal("100") else Severity.MOYENNE,
                                titre=f"Total patronal divergent entre documents",
                                description=(
                                    f"Le total des cotisations patronales differe : "
                                    f"{formater_montant(t1)} dans {label1} vs "
                                    f"{formater_montant(t2)} dans {label2}. "
                                    f"Ecart : {formater_montant(ecart)} ({ecart_pct:.2%})."
                                ),
                                valeur_constatee=str(t1),
                                valeur_attendue=str(t2),
                                montant_impact=ecart,
                                score_risque=70,
                                recommandation=(
                                    "Reconcilier le total des cotisations patronales "
                                    "entre les documents. Verifier les lignes manquantes "
                                    "ou en double."
                                ),
                                detecte_par=self.nom,
                                documents_concernes=[
                                    d1.source_document_id, d2.source_document_id,
                                ],
                                details_technique=_details_technique(
                                    annee=annee, periode=per,
                                    document=f"{label1} vs {label2}",
                                    rubrique="Total cotisations patronales",
                                ),
                            ))

        return findings

    # =================================================================
    # 12. Exonerations cross-document (RGDU, Fillon)
    # =================================================================

    def _comparer_exonerations_inter_documents(
        self, declarations: list[Declaration],
    ) -> list[Finding]:
        """Detecte les incoherences d'exonerations entre documents."""
        findings: list[Finding] = []
        par_periode = self._regrouper_par_periode(declarations)
        exo_types = {ContributionType.RGDU, ContributionType.LOI_FILLON}

        for _, decls in par_periode.items():
            if len(decls) < 2:
                continue

            for i in range(len(decls)):
                for j in range(i + 1, len(decls)):
                    d1, d2 = decls[i], decls[j]
                    nir_to_id_d1 = _nir_to_employe_id(d1)
                    nir_to_id_d2 = _nir_to_employe_id(d2)
                    cots_d1 = _cotisations_par_employe(d1)
                    cots_d2 = _cotisations_par_employe(d2)

                    nirs_communs = set(nir_to_id_d1.keys()) & set(nir_to_id_d2.keys())
                    annee, per = _annee_periode(d1)
                    label1, label2 = _doc_label(d1), _doc_label(d2)

                    for nir in nirs_communs:
                        eid1 = nir_to_id_d1[nir]
                        eid2 = nir_to_id_d2[nir]
                        cots1 = cots_d1.get(eid1, [])
                        cots2 = cots_d2.get(eid2, [])

                        has_exo_d1 = any(
                            c.type_cotisation in exo_types
                            and (abs(c.montant_patronal) + abs(c.montant_salarial)) > TOLERANCE_MONTANT
                            for c in cots1
                        )
                        has_exo_d2 = any(
                            c.type_cotisation in exo_types
                            and (abs(c.montant_patronal) + abs(c.montant_salarial)) > TOLERANCE_MONTANT
                            for c in cots2
                        )

                        if has_exo_d1 != has_exo_d2:
                            doc_avec = label1 if has_exo_d1 else label2
                            doc_sans = label2 if has_exo_d1 else label1
                            # Trouver le montant de l'exoneration
                            exo_cots = cots1 if has_exo_d1 else cots2
                            montant_exo = sum(
                                abs(c.montant_patronal) + abs(c.montant_salarial)
                                for c in exo_cots
                                if c.type_cotisation in exo_types
                            )
                            findings.append(Finding(
                                categorie=FindingCategory.INCOHERENCE,
                                severite=Severity.HAUTE,
                                titre=f"Exoneration RGDU/Fillon presente dans un seul document (NIR {nir[:5]}...)",
                                description=(
                                    f"Pour le NIR {nir}, une exoneration RGDU/Fillon "
                                    f"de {formater_montant(montant_exo)} est presente "
                                    f"dans {doc_avec} mais absente de {doc_sans}. "
                                    f"Cette incoherence impacte directement le montant "
                                    f"des cotisations dues."
                                ),
                                montant_impact=montant_exo,
                                score_risque=75,
                                recommandation=(
                                    "Verifier l'eligibilite a la RGDU pour ce salarie "
                                    "et harmoniser les documents. L'exoneration doit "
                                    "apparaitre dans tous les documents."
                                ),
                                detecte_par=self.nom,
                                documents_concernes=[
                                    d1.source_document_id, d2.source_document_id,
                                ],
                                reference_legale="CSS art. L241-13 - RGDU",
                                details_technique=_details_technique(
                                    annee=annee, periode=per,
                                    document=f"{label1} vs {label2}",
                                    rubrique="Exonerations RGDU/Fillon",
                                    extra={"nir": nir},
                                ),
                            ))

        return findings

    # =================================================================
    # Cour des Comptes : Controle exonerations ACRE temporellement bornees
    # =================================================================

    def _verifier_exonerations_temporelles(
        self, declarations: list[Declaration],
    ) -> list[Finding]:
        """Cour des Comptes : verifie que les exonerations temporaires
        (ACRE, ZRR, ZFU) ne depassent pas leur duree legale.

        - ACRE : 12 mois max (CSS art. L131-6-4)
        - ZRR : 12 mois taux plein + 12 mois degressif (CSS art. L131-4-2)
        - ZFU : 5 ans + 3 a 9 ans degressif
        """
        findings: list[Finding] = []

        exo_types_temporaires = {
            ContributionType.ACRE,
            ContributionType.EXONERATION_ZRR,
            ContributionType.EXONERATION_ZFU,
        }

        # Pour chaque employe, trouver les periodes d'exoneration
        employe_exo_periodes: dict[str, list[tuple]] = defaultdict(list)

        for decl in declarations:
            if not decl.periode:
                continue
            nir_map = _employe_id_to_nir(decl)
            for c in decl.cotisations:
                if c.type_cotisation in exo_types_temporaires:
                    montant_exo = abs(c.montant_patronal) + abs(c.montant_salarial)
                    if montant_exo > TOLERANCE_MONTANT:
                        nir = nir_map.get(c.employe_id, c.employe_id)
                        employe_exo_periodes[nir].append((
                            decl.periode.debut,
                            decl.periode.fin,
                            c.type_cotisation,
                            montant_exo,
                            decl.source_document_id,
                        ))

        # Verifier la duree totale d'exoneration par employe
        for nir, periodes in employe_exo_periodes.items():
            if not periodes:
                continue
            # Trier par date de debut
            periodes_triees = sorted(periodes, key=lambda p: p[0])
            premiere_date = periodes_triees[0][0]
            derniere_date = periodes_triees[-1][1]
            duree_mois = (derniere_date.year - premiere_date.year) * 12 + (derniere_date.month - premiere_date.month)
            type_exo = periodes_triees[0][2]
            total_exo = sum(p[3] for p in periodes_triees)

            # Duree max selon type
            duree_max = 12  # ACRE par defaut
            if type_exo == ContributionType.EXONERATION_ZRR:
                duree_max = 24  # 12 plein + 12 degressif
            elif type_exo == ContributionType.EXONERATION_ZFU:
                duree_max = 60  # 5 ans

            if duree_mois > duree_max:
                doc_ids = list(set(p[4] for p in periodes_triees))
                findings.append(Finding(
                    categorie=FindingCategory.ANOMALIE,
                    severite=Severity.HAUTE,
                    titre=f"Exoneration {type_exo.value} au-dela de la duree legale (NIR {nir[:5]}...)",
                    description=(
                        f"L'exoneration {type_exo.value} est appliquee depuis "
                        f"{duree_mois} mois (du {premiere_date.isoformat()} au "
                        f"{derniere_date.isoformat()}) pour le NIR {nir}. "
                        f"La duree maximale legale est de {duree_max} mois.\\n\\n"
                        f"Total exonere sur la periode : {formater_montant(total_exo)}.\\n\\n"
                        f"Point Cour des Comptes : les exonerations temporaires doivent "
                        f"etre arretees a l'echeance. Leur prolongation indue constitue "
                        f"une perte de recettes pour les organismes sociaux.\\n"
                        f"Point URSSAF : recuperation possible sur 3 ans avec majorations."
                    ),
                    montant_impact=total_exo,
                    score_risque=85,
                    recommandation=(
                        f"Supprimer l'exoneration {type_exo.value} qui a depasse sa "
                        f"duree legale de {duree_max} mois. Regulariser les cotisations "
                        f"pour les periodes au-dela de la limite."
                    ),
                    detecte_par=self.nom,
                    documents_concernes=doc_ids[:5],
                    reference_legale=(
                        "CSS art. L131-6-4 (ACRE 12 mois), "
                        "CSS art. L131-4-2 (ZRR), "
                        "CGI art. 44 octies (ZFU)"
                    ),
                ))

        return findings

    # =================================================================
    # 13. Coherence assiettes plafonnees / deplafonnees (intra-doc)
    # =================================================================

    def _verifier_coherence_assiettes_plafonnees(
        self, decl: Declaration,
    ) -> list[Finding]:
        """Verifie la coherence entre bases plafonnees et deplafonnees par employe."""
        findings: list[Finding] = []
        annee, per = _annee_periode(decl)
        doc_label = _doc_label(decl)

        for emp in decl.employes:
            emp_cots = [c for c in decl.cotisations if c.employe_id == emp.id]
            if not emp_cots:
                continue

            nom_emp = f"{emp.prenom} {emp.nom}" if emp.nom else f"NIR {emp.nir[:5]}..." if emp.nir else emp.id

            # Trouver la base deplafonnee (vieillesse deplafonnee, maladie)
            bases_deplafonnees = [
                c.assiette for c in emp_cots
                if c.type_cotisation in (
                    ContributionType.VIEILLESSE_DEPLAFONNEE,
                    ContributionType.MALADIE,
                )
                and c.assiette > 0
            ]
            # Trouver la base plafonnee (vieillesse plafonnee)
            bases_plafonnees = [
                c.assiette for c in emp_cots
                if c.type_cotisation == ContributionType.VIEILLESSE_PLAFONNEE
                and c.assiette > 0
            ]

            if not bases_deplafonnees or not bases_plafonnees:
                continue

            base_deplaf = max(bases_deplafonnees)
            base_plaf = max(bases_plafonnees)

            # La base plafonnee ne peut pas depasser la base deplafonnee
            if base_plaf > base_deplaf + TOLERANCE_MONTANT:
                ecart = base_plaf - base_deplaf
                findings.append(Finding(
                    categorie=FindingCategory.INCOHERENCE,
                    severite=Severity.HAUTE,
                    titre=f"Base plafonnee > base deplafonnee ({nom_emp})",
                    description=(
                        f"Pour {nom_emp}, la base plafonnee "
                        f"({formater_montant(base_plaf)}) est superieure a la base "
                        f"deplafonnee ({formater_montant(base_deplaf)}). "
                        f"La base plafonnee = min(salaire, PASS), elle ne peut "
                        f"pas depasser la base deplafonnee = salaire total."
                    ),
                    valeur_constatee=f"plafonnee={formater_montant(base_plaf)}",
                    valeur_attendue=f"<= deplafonnee={formater_montant(base_deplaf)}",
                    montant_impact=ecart,
                    score_risque=75,
                    recommandation=(
                        "Corriger les assiettes de cotisations. La base plafonnee "
                        "doit etre inferieure ou egale a la base deplafonnee."
                    ),
                    detecte_par=self.nom,
                    documents_concernes=[decl.source_document_id],
                    reference_legale="Art. L242-1 CSS, Art. L241-3 CSS - Plafonnement PASS",
                    details_technique=_details_technique(
                        annee=annee, periode=per, document=doc_label,
                        rubrique=f"Assiettes plafonnees {nom_emp}",
                    ),
                ))

            # La base plafonnee ne peut pas depasser le PASS
            if base_plaf > PASS_MENSUEL + TOLERANCE_MONTANT:
                # Deja detecte par AnomalyDetector, mais doublon voulu pour coherence
                pass

            # Si salaire > PASS, la base plafonnee devrait etre = PASS
            if base_deplaf > PASS_MENSUEL + Decimal("10"):
                ecart_vs_pass = abs(base_plaf - PASS_MENSUEL)
                # Tolerance pour temps partiel (proratisation)
                temps_travail = emp.temps_travail if emp.temps_travail > 0 else Decimal("1")
                pass_proratise = PASS_MENSUEL * temps_travail
                ecart_vs_pass_proratise = abs(base_plaf - pass_proratise)

                if ecart_vs_pass > Decimal("10") and ecart_vs_pass_proratise > Decimal("10"):
                    findings.append(Finding(
                        categorie=FindingCategory.INCOHERENCE,
                        severite=Severity.MOYENNE,
                        titre=f"Base plafonnee != PASS pour salaire > PASS ({nom_emp})",
                        description=(
                            f"Le salaire de {nom_emp} ({formater_montant(base_deplaf)}) "
                            f"depasse le PASS ({formater_montant(PASS_MENSUEL)}), "
                            f"mais la base plafonnee ({formater_montant(base_plaf)}) "
                            f"ne correspond ni au PASS ni au PASS proratise "
                            f"({formater_montant(pass_proratise)})."
                        ),
                        valeur_constatee=formater_montant(base_plaf),
                        valeur_attendue=formater_montant(pass_proratise),
                        montant_impact=abs(base_plaf - pass_proratise),
                        score_risque=60,
                        recommandation=(
                            "Verifier le plafonnement de la base de cotisation. "
                            "Pour un salaire superieur au PASS, la base plafonnee "
                            "devrait etre egale au PASS (ou au PASS proratise en "
                            "cas de temps partiel)."
                        ),
                        detecte_par=self.nom,
                        documents_concernes=[decl.source_document_id],
                        reference_legale="Art. L241-3 CSS - Plafond de securite sociale",
                        details_technique=_details_technique(
                            annee=annee, periode=per, document=doc_label,
                            rubrique=f"Plafonnement {nom_emp}",
                        ),
                    ))

        return findings

    # =================================================================
    # Utilitaires
    # =================================================================

    @staticmethod
    def _regrouper_par_periode(
        declarations: list[Declaration],
    ) -> dict[tuple, list[Declaration]]:
        """Regroupe les declarations par periode compatible.

        Deux declarations sont regroupees si elles couvrent le meme mois
        (meme annee et meme mois de debut), meme si les bornes exactes
        different legerement (ex: 01/01 - 31/01 vs 01/01 - 30/01).
        """
        par_periode: dict[tuple, list[Declaration]] = {}
        for decl in declarations:
            if decl.periode:
                # Cle = (annee, mois) du debut pour regroupement souple
                key = (decl.periode.debut.year, decl.periode.debut.month)
                if key not in par_periode:
                    par_periode[key] = []
                par_periode[key].append(decl)
        return par_periode
