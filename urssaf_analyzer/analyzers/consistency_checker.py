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

        # -- SIRET coherence --
        if decl.employeur and decl.employeur.siret:
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

        return findings

    # =================================================================
    # Coherence inter-documents (existant, ameliore)
    # =================================================================

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
    # Utilitaires
    # =================================================================

    @staticmethod
    def _regrouper_par_periode(
        declarations: list[Declaration],
    ) -> dict[tuple, list[Declaration]]:
        """Regroupe les declarations par (debut, fin) de periode."""
        par_periode: dict[tuple, list[Declaration]] = {}
        for decl in declarations:
            if decl.periode:
                key = (decl.periode.debut, decl.periode.fin)
                if key not in par_periode:
                    par_periode[key] = []
                par_periode[key].append(decl)
        return par_periode
