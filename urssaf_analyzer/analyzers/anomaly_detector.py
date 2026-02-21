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

            # FNAL deplafonne >= 50 salaries : verifier que c'est bien le bon taux
            if effectif >= SEUIL_EFFECTIF_50 and ContributionType.FNAL in types_presents:
                fnal_cots = [c for c in decl.cotisations if c.type_cotisation == ContributionType.FNAL]
                for fc in fnal_cots:
                    if fc.taux_patronal > 0 and fc.taux_patronal < Decimal("0.004"):
                        findings.append(Finding(
                            categorie=FindingCategory.ANOMALIE,
                            severite=Severity.HAUTE,
                            titre="FNAL : taux plafonne applique au lieu du deplafonne",
                            description=(
                                f"L'entreprise a {effectif} salaries (>= 50). "
                                f"Le FNAL doit etre calcule au taux deplafonne de 0.50% "
                                f"sur la totalite du salaire, et non au taux plafonne "
                                f"de 0.10%.\\n\\n"
                                f"Taux constate : {float(fc.taux_patronal)*100:.2f}%\\n"
                                f"Taux attendu : 0.50%\\n\\n"
                                f"Impact : sous-declaration systematique de cotisations."
                            ),
                            valeur_constatee=f"{float(fc.taux_patronal)*100:.2f}%",
                            valeur_attendue="0.50%",
                            score_risque=80,
                            recommandation="Corriger le taux FNAL a 0.50% deplafonne pour effectif >= 50.",
                            detecte_par=self.nom,
                            documents_concernes=[decl.source_document_id or decl.id],
                            reference_legale="Art. L834-1 CSS - FNAL deplafonne >= 50 salaries",
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
