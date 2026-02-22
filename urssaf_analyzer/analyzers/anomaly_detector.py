"""Detecteur d'anomalies dans les cotisations sociales.

Detecte :
- Taux de cotisation incorrects par rapport a la reglementation 2026
- Erreurs de calcul (base * taux != montant)
- Assiettes de cotisation aberrantes (negatives, excessives)
- Plafonnement PASS non applique ou mal applique
- Gestion des cas particuliers : apprentis, contrats aides
"""

from decimal import Decimal, ROUND_HALF_UP

from urssaf_analyzer.analyzers.base_analyzer import BaseAnalyzer
from urssaf_analyzer.config.constants import (
    ContributionType, Severity, FindingCategory,
    TOLERANCE_MONTANT, TOLERANCE_TAUX, PASS_MENSUEL, SMIC_MENSUEL_BRUT,
    SEUIL_EFFECTIF_11, SEUIL_EFFECTIF_20, SEUIL_EFFECTIF_50,
    SEUIL_EFFECTIF_250,
)
from urssaf_analyzer.models.documents import Declaration, Finding, Cotisation, Employe
from urssaf_analyzer.rules.contribution_rules import ContributionRules

# Mots-cles identifiant un apprenti dans le champ statut
_APPRENTI_KEYWORDS = ("apprenti", "apprentissage", "alternance", "alternant",
                       "contrat pro", "professionnalisation")


def _est_apprenti(employe: Employe | None) -> bool:
    """Determine si un employe est en contrat d'apprentissage ou alternance."""
    if not employe:
        return False
    s = employe.statut.lower()
    return any(kw in s for kw in _APPRENTI_KEYWORDS)


class AnomalyDetector(BaseAnalyzer):
    """Detecte les anomalies dans les montants et taux de cotisations."""

    @property
    def nom(self) -> str:
        return "Detecteur d'anomalies"

    def __init__(self, effectif: int = 0, taux_at: Decimal = Decimal("0.0208")):
        self.rules = ContributionRules(effectif, taux_at)

    # Cotisations obligatoires pour TOUT employeur (regime general)
    COTISATIONS_UNIVERSELLES = [
        ContributionType.MALADIE,
        ContributionType.VIEILLESSE_PLAFONNEE,
        ContributionType.VIEILLESSE_DEPLAFONNEE,
        ContributionType.ALLOCATIONS_FAMILIALES,
        ContributionType.ACCIDENT_TRAVAIL,
        ContributionType.CSG_DEDUCTIBLE,
        ContributionType.CRDS,
        ContributionType.ASSURANCE_CHOMAGE,
        ContributionType.AGS,
        ContributionType.RETRAITE_COMPLEMENTAIRE_T1,
        ContributionType.FNAL,
        ContributionType.CONTRIBUTION_SOLIDARITE_AUTONOMIE,
        ContributionType.FORMATION_PROFESSIONNELLE,
        ContributionType.TAXE_APPRENTISSAGE,
    ]

    # Cotisations conditionnelles par seuil d'effectif
    COTISATIONS_PAR_SEUIL = [
        (SEUIL_EFFECTIF_11, ContributionType.VERSEMENT_MOBILITE,
         "Art. L2333-64 CGCT", "Versement mobilite obligatoire >= 11 salaries (zone avec AOM)"),
        (SEUIL_EFFECTIF_20, ContributionType.PEEC,
         "Art. L313-1 Code construction", "Participation effort construction obligatoire >= 20 salaries"),
    ]

    def analyser(self, declarations: list[Declaration]) -> list[Finding]:
        findings = []
        for decl in declarations:
            effectif = decl.employeur.effectif if decl.employeur else 0
            if effectif > 0:
                self.rules = ContributionRules(effectif, self.rules.taux_at)

            # Index des employes par id pour lookup rapide
            employes_par_id = {e.id: e for e in decl.employes}

            for cotisation in decl.cotisations:
                employe = employes_par_id.get(cotisation.employe_id)
                findings.extend(self._verifier_cotisation(cotisation, decl, employe))

            # Verifier les cotisations obligatoires manquantes
            if decl.cotisations and len(decl.cotisations) >= 3:
                findings.extend(self._verifier_cotisations_obligatoires(decl))

            # Verifier les employes (NIR, SMIC, net>brut) - toujours executer
            if decl.employes:
                findings.extend(self._verifier_employes(decl))
        return findings

    def _verifier_cotisations_obligatoires(self, decl: Declaration) -> list[Finding]:
        """Detecte les cotisations obligatoires manquantes dans une declaration.

        C'est le controle le plus important : verifier que toutes les
        cotisations requises par la legislation sont effectivement presentes
        selon l'effectif de l'entreprise.
        """
        findings = []
        effectif = decl.employeur.effectif if decl.employeur else 0
        types_presents = {c.type_cotisation for c in decl.cotisations}
        ref_doc = decl.reference or decl.id
        doc_type = (decl.type_declaration or "").lower()

        # Ne verifier que les declarations de type bulletin ou DSN
        # (pas les factures, contrats, etc.)
        if doc_type in ("facture", "contrat", "interessement", "participation", "attestation"):
            return findings

        # --- Cotisations universelles ---
        for ct in self.COTISATIONS_UNIVERSELLES:
            if ct not in types_presents:
                ct_label = ct.value.replace("_", " ").title()
                # CSG peut etre regroupee, pas de faux positif si CSG non deductible manque
                if ct == ContributionType.CSG_DEDUCTIBLE and ContributionType.CSG_NON_DEDUCTIBLE in types_presents:
                    continue
                if ct == ContributionType.CRDS and ContributionType.CSG_DEDUCTIBLE in types_presents:
                    continue  # CRDS souvent regroupee avec CSG
                # Retraite T1 peut apparaitre comme "retraite complementaire" generique
                if ct == ContributionType.RETRAITE_COMPLEMENTAIRE_T1 and ContributionType.RETRAITE_COMPLEMENTAIRE_T2 in types_presents:
                    continue
                # FNAL et CSA souvent non detailles sur bulletins simplifies
                if ct in (ContributionType.FNAL, ContributionType.CONTRIBUTION_SOLIDARITE_AUTONOMIE):
                    severity = Severity.FAIBLE
                    score = 30
                else:
                    severity = Severity.MOYENNE
                    score = 50
                findings.append(Finding(
                    categorie=FindingCategory.DONNEE_MANQUANTE,
                    severite=severity,
                    titre=f"Cotisation obligatoire absente : {ct_label}",
                    description=(
                        f"La cotisation {ct_label} n'apparait pas dans le document "
                        f"'{ref_doc}'. Cette cotisation est obligatoire pour tout "
                        f"employeur du regime general.\\n\\n"
                        f"Cela peut indiquer :\\n"
                        f"- Une cotisation regroupee sous un autre libelle\\n"
                        f"- Un oubli dans le logiciel de paie\\n"
                        f"- Un document incomplet ou tronque\\n\\n"
                        f"Que faire ?\\n"
                        f"Verifier que cette cotisation est bien declaree, "
                        f"eventuellement sous un libelle different."
                    ),
                    score_risque=score,
                    recommandation=f"Verifier la presence de la cotisation {ct_label} dans les declarations.",
                    detecte_par=self.nom,
                    documents_concernes=[decl.source_document_id or decl.id],
                    reference_legale="Art. L242-1 CSS - Assiette des cotisations",
                ))

        # --- Cotisations conditionnelles par effectif ---
        if effectif > 0:
            for seuil, ct, ref_legale, description in self.COTISATIONS_PAR_SEUIL:
                if effectif >= seuil and ct not in types_presents:
                    ct_label = ct.value.replace("_", " ").title()
                    findings.append(Finding(
                        categorie=FindingCategory.DONNEE_MANQUANTE,
                        severite=Severity.HAUTE,
                        titre=f"Cotisation obligatoire manquante : {ct_label} (effectif {effectif})",
                        description=(
                            f"L'entreprise declare un effectif de {effectif} salaries. "
                            f"A partir de {seuil} salaries, la cotisation {ct_label} "
                            f"est obligatoire.\\n\\n"
                            f"{description}.\\n\\n"
                            f"Cette cotisation n'apparait dans aucune ligne du document "
                            f"'{ref_doc}'.\\n\\n"
                            f"Impact potentiel :\\n"
                            f"En cas de controle URSSAF, l'absence de cette cotisation "
                            f"entrainera un redressement sur les 3 derniers exercices "
                            f"avec application de majorations de retard (5% + 0.4%/mois).\\n\\n"
                            f"Que faire ?\\n"
                            f"1. Verifier dans le logiciel de paie que cette cotisation est parametree\\n"
                            f"2. Si applicable, regulariser les periodes anterieures\\n"
                            f"3. Contacter l'URSSAF pour une mise en conformite volontaire"
                        ),
                        score_risque=85,
                        recommandation=(
                            f"Ajouter la cotisation {ct_label} dans le parametrage de paie. "
                            f"Regulariser les periodes anterieures si necessaire."
                        ),
                        detecte_par=self.nom,
                        documents_concernes=[decl.source_document_id or decl.id],
                        reference_legale=ref_legale,
                    ))

            # FNAL : verifier le taux exact selon effectif
            if ContributionType.FNAL in types_presents:
                fnal_cots = [c for c in decl.cotisations if c.type_cotisation == ContributionType.FNAL]
                for fc in fnal_cots:
                    if fc.taux_patronal > 0:
                        if effectif >= SEUIL_EFFECTIF_50:
                            # >= 50 : doit etre 0.50% deplafonne
                            taux_attendu = Decimal("0.005")
                            if abs(fc.taux_patronal - taux_attendu) > TOLERANCE_TAUX:
                                findings.append(Finding(
                                    categorie=FindingCategory.ANOMALIE,
                                    severite=Severity.HAUTE,
                                    titre="FNAL : taux incorrect pour effectif >= 50",
                                    description=(
                                        f"L'entreprise a {effectif} salaries (>= 50). "
                                        f"Le FNAL doit etre calcule au taux deplafonne de 0.50% "
                                        f"sur la totalite du salaire.\\n\\n"
                                        f"Taux constate : {float(fc.taux_patronal)*100:.2f}%\\n"
                                        f"Taux attendu : 0.50% (deplafonne)\\n\\n"
                                        f"Impact : ecart systematique de cotisations."
                                    ),
                                    valeur_constatee=f"{float(fc.taux_patronal)*100:.2f}%",
                                    valeur_attendue="0.50%",
                                    score_risque=80,
                                    recommandation="Corriger le taux FNAL a 0.50% deplafonne pour effectif >= 50.",
                                    detecte_par=self.nom,
                                    documents_concernes=[decl.source_document_id or decl.id],
                                    reference_legale="Art. L834-1 CSS - FNAL deplafonne >= 50 salaries",
                                ))
                        else:
                            # < 50 : doit etre 0.10% plafonne au PASS
                            taux_attendu = Decimal("0.001")
                            if abs(fc.taux_patronal - taux_attendu) > TOLERANCE_TAUX:
                                findings.append(Finding(
                                    categorie=FindingCategory.ANOMALIE,
                                    severite=Severity.MOYENNE,
                                    titre="FNAL : taux incorrect pour effectif < 50",
                                    description=(
                                        f"L'entreprise a {effectif} salaries (< 50). "
                                        f"Le FNAL doit etre calcule au taux de 0.10% "
                                        f"plafonne au PASS ({PASS_MENSUEL} EUR/mois).\\n\\n"
                                        f"Taux constate : {float(fc.taux_patronal)*100:.2f}%\\n"
                                        f"Taux attendu : 0.10% (plafonne PASS)"
                                    ),
                                    valeur_constatee=f"{float(fc.taux_patronal)*100:.2f}%",
                                    valeur_attendue="0.10%",
                                    score_risque=60,
                                    recommandation="Corriger le taux FNAL a 0.10% plafonne au PASS pour effectif < 50.",
                                    detecte_par=self.nom,
                                    documents_concernes=[decl.source_document_id or decl.id],
                                    reference_legale="Art. L834-1 CSS - FNAL plafonne < 50 salaries",
                                ))

        return findings

    def _verifier_employes(self, decl: Declaration) -> list[Finding]:
        """Verifie les donnees individuelles des employes (NIR, SMIC, etc.).

        Separe de _verifier_cotisations_obligatoires pour s'executer
        meme quand il y a peu de cotisations (ex: DSN avec 1-2 lignes).
        """
        findings = []

        # Verification NIR format (13 chiffres + 2 cle)
        for emp in decl.employes:
            if emp.nir and emp.nir.strip():
                nir = emp.nir.strip().replace(" ", "")
                if len(nir) >= 13:
                    nir_base = nir[:13]
                    if not nir_base.isdigit():
                        findings.append(Finding(
                            categorie=FindingCategory.ANOMALIE,
                            severite=Severity.HAUTE,
                            titre=f"NIR invalide : format incorrect ({emp.prenom} {emp.nom})",
                            description=(
                                f"Le NIR de {emp.prenom} {emp.nom} ne contient pas "
                                f"uniquement des chiffres : '{nir[:5]}...'.\\n\\n"
                                f"Le NIR (numero de securite sociale) doit etre compose "
                                f"de 13 chiffres + 2 chiffres de cle de controle."
                            ),
                            valeur_constatee=f"{nir[:5]}...",
                            valeur_attendue="13 chiffres + 2 cle",
                            score_risque=75,
                            recommandation="Verifier et corriger le NIR du salarie.",
                            detecte_par=self.nom,
                            documents_concernes=[decl.source_document_id or decl.id],
                            reference_legale="Art. R.114-7 CSS - NIR",
                        ))
                    elif len(nir) >= 15:
                        # Verification cle de controle (97 - NIR mod 97)
                        try:
                            nir_num = int(nir_base)
                            cle = int(nir[13:15])
                            cle_attendue = 97 - (nir_num % 97)
                            if cle != cle_attendue:
                                findings.append(Finding(
                                    categorie=FindingCategory.ANOMALIE,
                                    severite=Severity.HAUTE,
                                    titre=f"NIR invalide : cle de controle ({emp.prenom} {emp.nom})",
                                    description=(
                                        f"La cle de controle du NIR de {emp.prenom} {emp.nom} "
                                        f"est incorrecte.\\n"
                                        f"Cle constatee : {cle:02d}\\n"
                                        f"Cle attendue : {cle_attendue:02d}\\n\\n"
                                        f"Une erreur de saisie du NIR entrainera le rejet "
                                        f"de la DSN par Net-Entreprises."
                                    ),
                                    valeur_constatee=f"cle {cle:02d}",
                                    valeur_attendue=f"cle {cle_attendue:02d}",
                                    score_risque=80,
                                    recommandation="Corriger le NIR. Verifier aupres du salarie avec sa carte vitale.",
                                    detecte_par=self.nom,
                                    documents_concernes=[decl.source_document_id or decl.id],
                                    reference_legale="Decret 92-556 - Format NIR",
                                ))
                        except (ValueError, IndexError):
                            pass

        # Verification net > brut (anomalie logique)
        for emp in decl.employes:
            emp_cots = [c for c in decl.cotisations if c.employe_id == emp.id]
            if emp_cots:
                brut = max((c.base_brute for c in emp_cots), default=Decimal("0"))
                total_salarial = sum((c.montant_salarial for c in emp_cots if c.montant_salarial > 0), Decimal("0"))
                net_estime = brut - total_salarial
                if brut > 0 and net_estime > brut:
                    findings.append(Finding(
                        categorie=FindingCategory.ANOMALIE,
                        severite=Severity.HAUTE,
                        titre=f"Net superieur au brut ({emp.prenom} {emp.nom})",
                        description=(
                            f"Le net estime pour {emp.prenom} {emp.nom} est superieur "
                            f"au brut : net estime {net_estime:.2f} EUR > brut {brut:.2f} EUR.\\n\\n"
                            f"C'est impossible en paie standard : les cotisations salariales "
                            f"reduisent toujours le brut pour obtenir le net."
                        ),
                        valeur_constatee=f"net {net_estime:.2f} EUR",
                        valeur_attendue=f"< brut {brut:.2f} EUR",
                        score_risque=90,
                        recommandation="Verifier la coherence des montants de cotisations salariales.",
                        detecte_par=self.nom,
                        documents_concernes=[decl.source_document_id or decl.id],
                        reference_legale="Art. L3243-2 Code du travail - Bulletin de paie",
                    ))

        # Verification SMIC (salaire minimum)
        for emp in decl.employes:
            emp_cots = [c for c in decl.cotisations if c.employe_id == emp.id]
            if emp_cots:
                brut = max((c.base_brute for c in emp_cots), default=Decimal("0"))
                if Decimal("0") < brut < SMIC_MENSUEL_BRUT:
                    # Verifier si temps partiel
                    temps_travail = emp.temps_travail if emp.temps_travail > 0 else Decimal("1.0")
                    smic_proratis = SMIC_MENSUEL_BRUT * temps_travail
                    if brut < smic_proratis - TOLERANCE_MONTANT:
                        est_apprenti_emp = _est_apprenti(emp)
                        if est_apprenti_emp:
                            severity = Severity.FAIBLE
                            note = " (apprenti : SMIC reduit possible)"
                            score = 20
                        else:
                            severity = Severity.HAUTE
                            note = ""
                            score = 85
                        findings.append(Finding(
                            categorie=FindingCategory.ANOMALIE,
                            severite=severity,
                            titre=f"Salaire inferieur au SMIC{note}",
                            description=(
                                f"Le salaire brut de {emp.prenom} {emp.nom} ({brut:.2f} EUR) "
                                f"est inferieur au SMIC mensuel 2026 "
                                f"({SMIC_MENSUEL_BRUT} EUR pour un temps plein).\\n\\n"
                                f"Temps de travail declare : {float(temps_travail)*100:.0f}%\\n"
                                f"SMIC proratise : {smic_proratis:.2f} EUR\\n\\n"
                                f"Que faire ?\\n"
                                f"Verifier le salaire de base et le temps de travail du salarie."
                            ),
                            valeur_constatee=f"{brut:.2f} EUR",
                            valeur_attendue=f">= {smic_proratis:.2f} EUR",
                            montant_impact=smic_proratis - brut,
                            score_risque=score,
                            recommandation="Verifier et corriger le salaire pour respecter le SMIC.",
                            detecte_par=self.nom,
                            documents_concernes=[decl.source_document_id or decl.id],
                            reference_legale="Art. L3231-2 Code du travail - SMIC 2026",
                        ))

        # --- RGDU / Reduction Generale validation ---
        for emp in decl.employes:
            emp_cots = [c for c in decl.cotisations if c.employe_id == emp.id]
            rgdu_cots = [c for c in emp_cots
                         if c.type_cotisation in (ContributionType.RGDU, ContributionType.LOI_FILLON)]
            if rgdu_cots:
                brut = max((c.base_brute for c in emp_cots), default=Decimal("0"))
                brut_annuel = brut * 12
                seuil_fillon_mensuel = SMIC_MENSUEL_BRUT * Decimal("1.6")
                seuil_rgdu_mensuel = SMIC_MENSUEL_BRUT * Decimal("3")
                for rc in rgdu_cots:
                    montant_reduction = abs(rc.montant_patronal) + abs(rc.montant_salarial)
                    if montant_reduction > TOLERANCE_MONTANT:
                        # Old Fillon: reduction should be zero if salary > 1.6 SMIC
                        if rc.type_cotisation == ContributionType.LOI_FILLON and brut > seuil_fillon_mensuel + TOLERANCE_MONTANT:
                            findings.append(Finding(
                                categorie=FindingCategory.ANOMALIE,
                                severite=Severity.HAUTE,
                                titre=f"Reduction Fillon appliquee au-dela de 1.6 SMIC ({emp.prenom} {emp.nom})",
                                description=(
                                    f"Une reduction Fillon de {montant_reduction:.2f} EUR est "
                                    f"appliquee pour {emp.prenom} {emp.nom} alors que le salaire "
                                    f"brut ({brut:.2f} EUR) depasse le seuil de 1.6 SMIC "
                                    f"({seuil_fillon_mensuel:.2f} EUR/mois).\\n\\n"
                                    f"Au-dela de ce seuil, la reduction Fillon doit etre nulle. "
                                    f"Depuis 2026, la Reduction Generale Degressive Unique (RGDU) "
                                    f"remplace l'ancien dispositif Fillon avec un seuil a 3 SMIC.\\n\\n"
                                    f"Que faire ?\\n"
                                    f"1. Verifier que le logiciel de paie utilise bien la RGDU 2026\\n"
                                    f"2. Supprimer la reduction Fillon qui n'est plus applicable\\n"
                                    f"3. Evaluer l'eligibilite a la RGDU si le salaire est < 3 SMIC"
                                ),
                                valeur_constatee=f"{montant_reduction:.2f} EUR",
                                valeur_attendue="0.00 EUR",
                                montant_impact=montant_reduction,
                                score_risque=85,
                                recommandation="Supprimer la reduction Fillon et verifier l'eligibilite a la RGDU 2026.",
                                detecte_par=self.nom,
                                documents_concernes=[decl.source_document_id or decl.id],
                                reference_legale="CSS art. L241-13 - RGDU 2026 (ex-Fillon)",
                            ))
                        # New RGDU: reduction should be zero if salary >= 3 SMIC
                        elif rc.type_cotisation == ContributionType.RGDU and not self.rules.est_eligible_rgdu(brut_annuel):
                            findings.append(Finding(
                                categorie=FindingCategory.ANOMALIE,
                                severite=Severity.HAUTE,
                                titre=f"RGDU appliquee au-dela de 3 SMIC ({emp.prenom} {emp.nom})",
                                description=(
                                    f"Une RGDU de {montant_reduction:.2f} EUR est appliquee pour "
                                    f"{emp.prenom} {emp.nom} alors que le salaire brut annuel estime "
                                    f"({brut_annuel:.2f} EUR) atteint ou depasse le seuil de 3 SMIC "
                                    f"({seuil_rgdu_mensuel * 12:.2f} EUR/an).\\n\\n"
                                    f"La RGDU est une reduction degressive qui s'annule a 3 SMIC. "
                                    f"Au-dela de ce seuil, aucune reduction ne doit etre appliquee.\\n\\n"
                                    f"Que faire ?\\n"
                                    f"1. Verifier le parametre de remuneration annuelle dans le logiciel\\n"
                                    f"2. Supprimer la RGDU pour ce salarie\\n"
                                    f"3. Regulariser les periodes anterieures si necessaire"
                                ),
                                valeur_constatee=f"{montant_reduction:.2f} EUR",
                                valeur_attendue="0.00 EUR",
                                montant_impact=montant_reduction,
                                score_risque=90,
                                recommandation="Supprimer la RGDU : le salaire depasse 3 SMIC.",
                                detecte_par=self.nom,
                                documents_concernes=[decl.source_document_id or decl.id],
                                reference_legale="CSS art. L241-13 - RGDU plafonnee a 3 SMIC",
                            ))

        # --- AT/MP taux range check ---
        at_cots = [c for c in decl.cotisations
                   if c.type_cotisation == ContributionType.ACCIDENT_TRAVAIL]
        for atc in at_cots:
            if atc.taux_patronal > 0:
                taux_pct = atc.taux_patronal * 100
                if taux_pct < Decimal("0.20") or taux_pct > Decimal("18"):
                    findings.append(Finding(
                        categorie=FindingCategory.ANOMALIE,
                        severite=Severity.HAUTE,
                        titre=f"Taux AT/MP hors plage raisonnable ({taux_pct:.2f}%)",
                        description=(
                            f"Le taux AT/MP constate est de {taux_pct:.2f}%, ce qui est "
                            f"en dehors de la plage raisonnable (0.20% a 18%).\\n\\n"
                            f"Les taux AT/MP sont fixes par la CARSAT en fonction de la "
                            f"sinistralite de l'entreprise et du secteur d'activite. "
                            f"Un taux inferieur a 0.20% ou superieur a 18% est tres inhabituel "
                            f"et peut indiquer une erreur de saisie.\\n\\n"
                            f"Que faire ?\\n"
                            f"1. Verifier le taux sur la notification annuelle de la CARSAT\\n"
                            f"2. Comparer avec le taux de l'annee precedente\\n"
                            f"3. Corriger dans le logiciel de paie si necessaire"
                        ),
                        valeur_constatee=f"{taux_pct:.2f}%",
                        valeur_attendue="entre 0.20% et 18%",
                        score_risque=75,
                        recommandation="Verifier le taux AT/MP sur la notification CARSAT.",
                        detecte_par=self.nom,
                        documents_concernes=[decl.source_document_id or decl.id],
                        reference_legale="CSS art. L242-5, D242-6-1 - Taux AT/MP",
                    ))

        # --- CSG/CRDS assiette 98.25% du brut ---
        csg_crds_types = (
            ContributionType.CSG_DEDUCTIBLE,
            ContributionType.CSG_NON_DEDUCTIBLE,
            ContributionType.CRDS,
        )
        for emp in decl.employes:
            emp_cots = [c for c in decl.cotisations if c.employe_id == emp.id]
            brut = max((c.base_brute for c in emp_cots), default=Decimal("0"))
            if brut > 0:
                assiette_attendue = (brut * Decimal("0.9825")).quantize(
                    Decimal("0.01"), ROUND_HALF_UP
                )
                csg_crds_cots = [c for c in emp_cots if c.type_cotisation in csg_crds_types]
                for cc in csg_crds_cots:
                    if cc.assiette > 0:
                        ecart_assiette = abs(cc.assiette - assiette_attendue)
                        if ecart_assiette > Decimal("5"):
                            ct_label = cc.type_cotisation.value.replace("_", " ").upper()
                            findings.append(Finding(
                                categorie=FindingCategory.ANOMALIE,
                                severite=Severity.MOYENNE,
                                titre=f"Assiette {ct_label} incorrecte ({emp.prenom} {emp.nom})",
                                description=(
                                    f"L'assiette de la {ct_label} pour {emp.prenom} {emp.nom} "
                                    f"est de {cc.assiette:.2f} EUR, alors que l'assiette attendue "
                                    f"(98.25% du brut) est de {assiette_attendue:.2f} EUR.\\n\\n"
                                    f"Ecart constate : {ecart_assiette:.2f} EUR (tolerance : 5 EUR).\\n\\n"
                                    f"La CSG et la CRDS sont calculees sur 98.25% du salaire brut "
                                    f"(abattement forfaitaire de 1.75% pour frais professionnels). "
                                    f"Cette erreur d'assiette est frequente dans les logiciels de paie.\\n\\n"
                                    f"Que faire ?\\n"
                                    f"Verifier le parametrage de l'assiette CSG/CRDS dans le logiciel de paie."
                                ),
                                valeur_constatee=f"{cc.assiette:.2f} EUR",
                                valeur_attendue=f"{assiette_attendue:.2f} EUR (98.25% de {brut:.2f})",
                                montant_impact=ecart_assiette,
                                score_risque=65,
                                recommandation="Corriger l'assiette CSG/CRDS a 98.25% du brut.",
                                detecte_par=self.nom,
                                documents_concernes=[decl.source_document_id or decl.id],
                                reference_legale="CSS art. L136-2 - Assiette CSG/CRDS (abattement 1.75%)",
                            ))

        # --- Proratisation temps partiel du PASS ---
        for emp in decl.employes:
            if Decimal("0") < emp.temps_travail < Decimal("1"):
                emp_cots = [c for c in decl.cotisations if c.employe_id == emp.id]
                vp_cots = [c for c in emp_cots
                           if c.type_cotisation == ContributionType.VIEILLESSE_PLAFONNEE]
                pass_proratise = PASS_MENSUEL * emp.temps_travail
                for vpc in vp_cots:
                    if vpc.assiette > pass_proratise + TOLERANCE_MONTANT:
                        findings.append(Finding(
                            categorie=FindingCategory.ANOMALIE,
                            severite=Severity.HAUTE,
                            titre=f"PASS non proratise pour temps partiel ({emp.prenom} {emp.nom})",
                            description=(
                                f"{emp.prenom} {emp.nom} travaille a "
                                f"{float(emp.temps_travail)*100:.0f}% d'un temps plein. "
                                f"L'assiette de la vieillesse plafonnee ({vpc.assiette:.2f} EUR) "
                                f"depasse le PASS proratise ({pass_proratise:.2f} EUR).\\n\\n"
                                f"Pour un salarie a temps partiel, le plafond de securite "
                                f"sociale doit etre proratise au prorata du temps de travail "
                                f"(PASS mensuel {PASS_MENSUEL} EUR x "
                                f"{float(emp.temps_travail)*100:.0f}% = "
                                f"{pass_proratise:.2f} EUR).\\n\\n"
                                f"Que faire ?\\n"
                                f"1. Verifier le temps de travail declare dans le logiciel de paie\\n"
                                f"2. Corriger le plafonnement de la cotisation vieillesse plafonnee\\n"
                                f"3. S'assurer que toutes les cotisations plafonnees sont proratisees"
                            ),
                            valeur_constatee=f"{vpc.assiette:.2f} EUR",
                            valeur_attendue=f"<= {pass_proratise:.2f} EUR",
                            montant_impact=vpc.assiette - pass_proratise,
                            score_risque=80,
                            recommandation="Proratiser le PASS au temps de travail du salarie.",
                            detecte_par=self.nom,
                            documents_concernes=[decl.source_document_id or decl.id],
                            reference_legale="CSS art. L242-8 - Proratisation du plafond temps partiel",
                        ))

        # --- Retraite complementaire T2 ---
        for emp in decl.employes:
            emp_cots = [c for c in decl.cotisations if c.employe_id == emp.id]
            if emp_cots:
                brut = max((c.base_brute for c in emp_cots), default=Decimal("0"))
                t2_cots = [c for c in emp_cots
                           if c.type_cotisation == ContributionType.RETRAITE_COMPLEMENTAIRE_T2]
                if brut > PASS_MENSUEL + TOLERANCE_MONTANT and not t2_cots:
                    findings.append(Finding(
                        categorie=FindingCategory.DONNEE_MANQUANTE,
                        severite=Severity.HAUTE,
                        titre=f"Retraite complementaire T2 manquante ({emp.prenom} {emp.nom})",
                        description=(
                            f"Le salaire brut de {emp.prenom} {emp.nom} ({brut:.2f} EUR) "
                            f"depasse le PASS mensuel ({PASS_MENSUEL} EUR). La cotisation "
                            f"de retraite complementaire Tranche 2 (AGIRC-ARRCO) devrait "
                            f"etre presente sur la fraction du salaire entre 1 et 8 PASS.\\n\\n"
                            f"L'absence de cette cotisation peut entrainer un manque a gagner "
                            f"pour le salarie en termes de points de retraite complementaire.\\n\\n"
                            f"Que faire ?\\n"
                            f"1. Verifier le parametrage retraite complementaire dans le logiciel\\n"
                            f"2. S'assurer que la Tranche 2 est bien declaree\\n"
                            f"3. Regulariser aupres de l'AGIRC-ARRCO si necessaire"
                        ),
                        valeur_constatee="absente",
                        valeur_attendue="cotisation T2 presente",
                        score_risque=80,
                        recommandation="Ajouter la cotisation retraite complementaire T2 pour les salaires > PASS.",
                        detecte_par=self.nom,
                        documents_concernes=[decl.source_document_id or decl.id],
                        reference_legale="ANI AGIRC-ARRCO art. 36 - Tranche 2",
                    ))
                elif brut <= PASS_MENSUEL and t2_cots:
                    for t2c in t2_cots:
                        t2_montant = abs(t2c.montant_patronal) + abs(t2c.montant_salarial)
                        if t2_montant > TOLERANCE_MONTANT:
                            findings.append(Finding(
                                categorie=FindingCategory.ANOMALIE,
                                severite=Severity.MOYENNE,
                                titre=f"Retraite complementaire T2 indue ({emp.prenom} {emp.nom})",
                                description=(
                                    f"Le salaire brut de {emp.prenom} {emp.nom} ({brut:.2f} EUR) "
                                    f"ne depasse pas le PASS mensuel ({PASS_MENSUEL} EUR). "
                                    f"Or une cotisation retraite complementaire Tranche 2 de "
                                    f"{t2_montant:.2f} EUR est presente.\\n\\n"
                                    f"La Tranche 2 ne s'applique que sur la fraction du salaire "
                                    f"comprise entre 1 et 8 PASS. Si le salaire est inferieur au "
                                    f"PASS, cette cotisation devrait etre nulle.\\n\\n"
                                    f"Que faire ?\\n"
                                    f"Verifier le parametrage de la retraite complementaire et "
                                    f"supprimer la cotisation T2 pour ce salarie."
                                ),
                                valeur_constatee=f"{t2_montant:.2f} EUR",
                                valeur_attendue="0.00 EUR",
                                montant_impact=t2_montant,
                                score_risque=65,
                                recommandation="Supprimer la cotisation T2 : salaire inferieur au PASS.",
                                detecte_par=self.nom,
                                documents_concernes=[decl.source_document_id or decl.id],
                                reference_legale="ANI AGIRC-ARRCO art. 36 - Tranche 2 (1-8 PASS)",
                            ))

        return findings

    def _verifier_cotisation(
        self, c: Cotisation, decl: Declaration, employe: Employe | None = None,
    ) -> list[Finding]:
        findings = []
        est_apprenti = _est_apprenti(employe)
        nom_employe = f"{employe.prenom} {employe.nom}" if employe else "Employe"

        # 1. Valeurs aberrantes
        if c.base_brute < 0:
            findings.append(Finding(
                categorie=FindingCategory.ANOMALIE,
                severite=Severity.HAUTE,
                titre="Base brute negative",
                description=(
                    f"La base brute de cotisation {c.type_cotisation.value} pour "
                    f"{nom_employe} est negative : {c.base_brute} EUR.\\n\\n"
                    f"Qu'est-ce que cela signifie ?\\n"
                    f"La base brute est le salaire sur lequel sont calculees les cotisations. "
                    f"Elle ne peut pas etre negative, sauf cas exceptionnel de regularisation.\\n\\n"
                    f"Que faire ?\\n"
                    f"1. Verifier la saisie dans le logiciel de paie\\n"
                    f"2. Si c'est une regularisation, verifier qu'un bulletin rectificatif precedent justifie ce montant\\n"
                    f"3. Contacter votre editeur de paie si l'erreur persiste"
                ),
                valeur_constatee=str(c.base_brute),
                valeur_attendue=">= 0",
                montant_impact=abs(c.base_brute),
                score_risque=80,
                recommandation=(
                    "Verifier la saisie dans le logiciel de paie. "
                    "Une base negative peut indiquer une erreur de parametrage "
                    "ou une regularisation non documentee."
                ),
                detecte_par=self.nom,
                documents_concernes=[c.source_document_id],
                reference_legale="Art. L242-1 CSS - Assiette des cotisations de securite sociale",
            ))

        if c.montant_patronal < 0:
            findings.append(Finding(
                categorie=FindingCategory.ANOMALIE,
                severite=Severity.HAUTE,
                titre="Montant patronal negatif",
                description=(
                    f"Le montant patronal pour {c.type_cotisation.value} "
                    f"({nom_employe}) est negatif : {c.montant_patronal} EUR.\\n\\n"
                    f"Qu'est-ce que cela signifie ?\\n"
                    f"L'employeur ne devrait pas avoir un montant de cotisation negatif, "
                    f"sauf en cas de trop-percu ou de regularisation.\\n\\n"
                    f"Que faire ?\\n"
                    f"Verifier si un trop-percu anterieur justifie ce montant. "
                    f"Dans le cas contraire, corriger la saisie."
                ),
                valeur_constatee=str(c.montant_patronal),
                valeur_attendue=">= 0",
                montant_impact=abs(c.montant_patronal),
                score_risque=80,
                recommandation="Verifier si un trop-percu ou une regularisation justifie ce montant.",
                detecte_par=self.nom,
                documents_concernes=[c.source_document_id],
                reference_legale="Art. L242-1 CSS",
            ))

        # 2. Verification des taux
        # Les apprentis ont des regimes specifiques : ne pas flaguer les ecarts
        # lies aux exonerations apprenti (base reduite, taux differents)
        if c.taux_patronal > 0 and not est_apprenti:
            conforme, taux_attendu = self.rules.verifier_taux(
                c.type_cotisation, c.taux_patronal, c.base_brute, est_patronal=True
            )
            if not conforme and taux_attendu is not None:
                ecart_montant = Decimal("0")
                if c.assiette > 0:
                    ecart_montant = abs(
                        (c.assiette * c.taux_patronal) - (c.assiette * taux_attendu)
                    ).quantize(Decimal("0.01"), ROUND_HALF_UP)

                ct_label = c.type_cotisation.value.replace("_", " ")
                findings.append(Finding(
                    categorie=FindingCategory.ANOMALIE,
                    severite=Severity.HAUTE if ecart_montant > Decimal("100") else Severity.MOYENNE,
                    titre=f"Taux patronal incorrect - {ct_label}",
                    description=(
                        f"Pour {nom_employe}, le taux patronal applique pour "
                        f"{ct_label} est de {c.taux_patronal:.4f} "
                        f"({float(c.taux_patronal)*100:.2f}%), alors que le taux "
                        f"reglementaire 2026 est de {taux_attendu:.4f} "
                        f"({float(taux_attendu)*100:.2f}%).\\n\\n"
                        f"Impact estime : {ecart_montant} EUR sur cette ligne.\\n\\n"
                        f"Qu'est-ce que cela signifie ?\\n"
                        f"Chaque cotisation sociale a un taux fixe par la loi. "
                        f"Un ecart peut provenir d'un bareme non mis a jour dans "
                        f"le logiciel de paie, ou d'une specificite sectorielle.\\n\\n"
                        f"Que faire ?\\n"
                        f"1. Verifier que votre logiciel de paie utilise les baremes 2026\\n"
                        f"2. Si un accord de branche prevoit un taux specifique, verifier sa conformite\\n"
                        f"3. Corriger le taux si necessaire et recalculer les bulletins concernes"
                    ),
                    valeur_constatee=f"{c.taux_patronal:.4f} ({float(c.taux_patronal)*100:.2f}%)",
                    valeur_attendue=f"{taux_attendu:.4f} ({float(taux_attendu)*100:.2f}%)",
                    montant_impact=ecart_montant,
                    score_risque=70,
                    recommandation=(
                        "Verifier le parametrage du logiciel de paie et s'assurer "
                        "que les taux 2026 sont a jour. Si l'ecart est lie a un "
                        "accord de branche, documenter cette specificite."
                    ),
                    detecte_par=self.nom,
                    documents_concernes=[c.source_document_id],
                    reference_legale="Bareme URSSAF 2026 - Art. L241-6 et D242-1 CSS",
                ))

        # Pour les apprentis, generer une note informative (pas une erreur)
        if est_apprenti and c.taux_patronal > 0:
            conforme, taux_attendu = self.rules.verifier_taux(
                c.type_cotisation, c.taux_patronal, c.base_brute, est_patronal=True
            )
            if not conforme and taux_attendu is not None:
                ct_label = c.type_cotisation.value.replace("_", " ")
                findings.append(Finding(
                    categorie=FindingCategory.ANOMALIE,
                    severite=Severity.FAIBLE,
                    titre=f"Apprenti - taux specifique {ct_label}",
                    description=(
                        f"{nom_employe} est identifie(e) comme apprenti(e). "
                        f"Le taux applique ({c.taux_patronal:.4f}) differe du taux "
                        f"standard ({taux_attendu:.4f}), ce qui est normal pour "
                        f"un contrat d'apprentissage.\\n\\n"
                        f"Les apprentis beneficient d'exonerations specifiques "
                        f"de cotisations sociales (Art. L6243-2 Code du travail). "
                        f"Verifiez que les exonerations appliquees correspondent "
                        f"bien au regime en vigueur."
                    ),
                    valeur_constatee=f"{c.taux_patronal:.4f}",
                    valeur_attendue=f"{taux_attendu:.4f} (standard)",
                    montant_impact=Decimal("0"),
                    score_risque=15,
                    recommandation=(
                        "Aucune action requise si l'exoneration apprenti est "
                        "correctement appliquee. Verifier la coherence avec le "
                        "contrat d'apprentissage enregistre."
                    ),
                    detecte_par=self.nom,
                    documents_concernes=[c.source_document_id],
                    reference_legale="Art. L6243-2 Code du travail - Exoneration apprentis",
                ))

        # 3. Verification du calcul base * taux = montant
        if c.taux_patronal > 0 and c.assiette > 0 and c.montant_patronal > 0:
            montant_calcule = (c.assiette * c.taux_patronal).quantize(
                Decimal("0.01"), ROUND_HALF_UP
            )
            ecart = abs(c.montant_patronal - montant_calcule)
            if ecart > TOLERANCE_MONTANT:
                ct_label = c.type_cotisation.value.replace("_", " ")
                findings.append(Finding(
                    categorie=FindingCategory.ANOMALIE,
                    severite=Severity.MOYENNE,
                    titre=f"Erreur de calcul - {ct_label}",
                    description=(
                        f"Pour {nom_employe}, le montant patronal ({c.montant_patronal} EUR) "
                        f"ne correspond pas au calcul attendu :\\n"
                        f"  Assiette ({c.assiette}) x Taux ({c.taux_patronal}) = "
                        f"{montant_calcule} EUR\\n"
                        f"  Ecart constate : {ecart} EUR\\n\\n"
                        f"Qu'est-ce que cela signifie ?\\n"
                        f"Le montant inscrit sur le bulletin ne correspond pas au "
                        f"produit de la base par le taux. Cela peut etre du a un "
                        f"arrondi, une proratisation, ou une erreur de saisie.\\n\\n"
                        f"Que faire ?\\n"
                        f"Verifier si un prorata temps partiel ou une regularisation "
                        f"explique l'ecart. Sinon, corriger dans le logiciel de paie."
                    ),
                    valeur_constatee=str(c.montant_patronal),
                    valeur_attendue=str(montant_calcule),
                    montant_impact=ecart,
                    score_risque=60,
                    recommandation=(
                        "Verifier le calcul de cette ligne. Un ecart peut "
                        "provenir d'un arrondi ou d'une proratisation."
                    ),
                    detecte_par=self.nom,
                    documents_concernes=[c.source_document_id],
                ))

        # 4. Verification du plafonnement PASS
        if c.type_cotisation == ContributionType.VIEILLESSE_PLAFONNEE:
            # Pour les apprentis, la base peut etre reduite (assiette forfaitaire)
            if est_apprenti and c.assiette < SMIC_MENSUEL_BRUT:
                # Normal pour un apprenti : assiette forfaitaire
                pass
            elif c.assiette > PASS_MENSUEL + TOLERANCE_MONTANT:
                excedent = c.assiette - PASS_MENSUEL
                findings.append(Finding(
                    categorie=FindingCategory.DEPASSEMENT_SEUIL,
                    severite=Severity.HAUTE,
                    titre="Depassement du plafond de securite sociale (PASS)",
                    description=(
                        f"Pour {nom_employe}, l'assiette de la vieillesse plafonnee "
                        f"({c.assiette} EUR) depasse le PASS mensuel 2026 "
                        f"({PASS_MENSUEL} EUR). Excedent : {excedent} EUR.\\n\\n"
                        f"Qu'est-ce que le PASS ?\\n"
                        f"Le Plafond Annuel de la Securite Sociale (PASS) est un "
                        f"seuil fixe chaque annee. En 2026, il est de {PASS_MENSUEL} EUR "
                        f"par mois. La cotisation vieillesse plafonnee ne peut pas "
                        f"porter sur un montant superieur.\\n\\n"
                        f"Que faire ?\\n"
                        f"1. Verifier que le logiciel de paie applique bien le plafond\\n"
                        f"2. Si le salaire depasse le PASS, seule la fraction jusqu'au "
                        f"plafond est soumise a cette cotisation\\n"
                        f"3. La part au-dela doit etre soumise a la vieillesse deplafonnee"
                    ),
                    valeur_constatee=str(c.assiette),
                    valeur_attendue=f"<= {PASS_MENSUEL} EUR",
                    montant_impact=excedent * c.taux_patronal if c.taux_patronal > 0 else excedent,
                    score_risque=85,
                    recommandation=(
                        "Le plafonnement au PASS n'est pas correctement applique. "
                        "Corriger l'assiette de la cotisation vieillesse plafonnee."
                    ),
                    detecte_par=self.nom,
                    documents_concernes=[c.source_document_id],
                    reference_legale=(
                        "Art. L241-3 CSS - Plafond Securite Sociale 2026 : "
                        f"{PASS_MENSUEL} EUR/mois, {PASS_MENSUEL * 12} EUR/an"
                    ),
                ))

        return findings
