"""Detecteur d'anomalies dans les cotisations sociales.

Detecte :
- Taux de cotisation incorrects par rapport a la reglementation 2026
- Erreurs de calcul (base * taux != montant)
- Assiettes de cotisation aberrantes (negatives, excessives)
- Plafonnement PASS non applique ou mal applique
"""

from decimal import Decimal, ROUND_HALF_UP

from urssaf_analyzer.analyzers.base_analyzer import BaseAnalyzer
from urssaf_analyzer.config.constants import (
    ContributionType, Severity, FindingCategory,
    TOLERANCE_MONTANT, TOLERANCE_TAUX, PASS_MENSUEL,
)
from urssaf_analyzer.models.documents import Declaration, Finding, Cotisation
from urssaf_analyzer.rules.contribution_rules import ContributionRules


class AnomalyDetector(BaseAnalyzer):
    """Detecte les anomalies dans les montants et taux de cotisations."""

    @property
    def nom(self) -> str:
        return "Detecteur d'anomalies"

    def __init__(self, effectif: int = 0, taux_at: Decimal = Decimal("0.0208")):
        self.rules = ContributionRules(effectif, taux_at)

    def analyser(self, declarations: list[Declaration]) -> list[Finding]:
        findings = []
        for decl in declarations:
            effectif = decl.employeur.effectif if decl.employeur else 0
            if effectif > 0:
                self.rules = ContributionRules(effectif, self.rules.taux_at)

            for cotisation in decl.cotisations:
                findings.extend(self._verifier_cotisation(cotisation, decl))
        return findings

    def _verifier_cotisation(self, c: Cotisation, decl: Declaration) -> list[Finding]:
        findings = []

        # 1. Valeurs aberrantes
        if c.base_brute < 0:
            findings.append(Finding(
                categorie=FindingCategory.ANOMALIE,
                severite=Severity.HAUTE,
                titre="Base brute negative",
                description=(
                    f"La base brute de cotisation {c.type_cotisation.value} "
                    f"est negative : {c.base_brute}"
                ),
                valeur_constatee=str(c.base_brute),
                valeur_attendue=">= 0",
                montant_impact=abs(c.base_brute),
                score_risque=80,
                recommandation="Verifier la saisie et corriger la base de cotisation.",
                detecte_par=self.nom,
                documents_concernes=[c.source_document_id],
                reference_legale="Art. L242-1 CSS",
            ))

        if c.montant_patronal < 0:
            findings.append(Finding(
                categorie=FindingCategory.ANOMALIE,
                severite=Severity.HAUTE,
                titre="Montant patronal negatif",
                description=(
                    f"Le montant patronal pour {c.type_cotisation.value} "
                    f"est negatif : {c.montant_patronal}"
                ),
                valeur_constatee=str(c.montant_patronal),
                valeur_attendue=">= 0",
                montant_impact=abs(c.montant_patronal),
                score_risque=80,
                recommandation="Verifier si un trop-percu ou une erreur de signe.",
                detecte_par=self.nom,
                documents_concernes=[c.source_document_id],
            ))

        # 2. Verification des taux
        if c.taux_patronal > 0:
            conforme, taux_attendu = self.rules.verifier_taux(
                c.type_cotisation, c.taux_patronal, c.base_brute, est_patronal=True
            )
            if not conforme and taux_attendu is not None:
                ecart_montant = Decimal("0")
                if c.assiette > 0:
                    ecart_montant = abs(
                        (c.assiette * c.taux_patronal) - (c.assiette * taux_attendu)
                    ).quantize(Decimal("0.01"), ROUND_HALF_UP)

                findings.append(Finding(
                    categorie=FindingCategory.ANOMALIE,
                    severite=Severity.HAUTE if ecart_montant > Decimal("100") else Severity.MOYENNE,
                    titre=f"Taux patronal incorrect - {c.type_cotisation.value}",
                    description=(
                        f"Le taux patronal applique ({c.taux_patronal:.4f}) differe "
                        f"du taux reglementaire ({taux_attendu:.4f}) pour "
                        f"{c.type_cotisation.value}."
                    ),
                    valeur_constatee=f"{c.taux_patronal:.4f}",
                    valeur_attendue=f"{taux_attendu:.4f}",
                    montant_impact=ecart_montant,
                    score_risque=70,
                    recommandation=(
                        "Verifier le parametrage du logiciel de paie. "
                        "S'assurer que les taux 2026 sont a jour."
                    ),
                    detecte_par=self.nom,
                    documents_concernes=[c.source_document_id],
                    reference_legale="Bareme URSSAF 2026",
                ))

        # 3. Verification du calcul base * taux = montant
        if c.taux_patronal > 0 and c.assiette > 0 and c.montant_patronal > 0:
            montant_calcule = (c.assiette * c.taux_patronal).quantize(
                Decimal("0.01"), ROUND_HALF_UP
            )
            ecart = abs(c.montant_patronal - montant_calcule)
            if ecart > TOLERANCE_MONTANT:
                findings.append(Finding(
                    categorie=FindingCategory.ANOMALIE,
                    severite=Severity.MOYENNE,
                    titre=f"Erreur de calcul - {c.type_cotisation.value}",
                    description=(
                        f"Le montant patronal ({c.montant_patronal}) ne correspond pas "
                        f"au calcul assiette x taux ({c.assiette} x {c.taux_patronal} "
                        f"= {montant_calcule}). Ecart : {ecart}."
                    ),
                    valeur_constatee=str(c.montant_patronal),
                    valeur_attendue=str(montant_calcule),
                    montant_impact=ecart,
                    score_risque=60,
                    recommandation="Verifier le calcul de cette ligne de cotisation.",
                    detecte_par=self.nom,
                    documents_concernes=[c.source_document_id],
                ))

        # 4. Verification du plafonnement PASS
        if c.type_cotisation == ContributionType.VIEILLESSE_PLAFONNEE:
            if c.assiette > PASS_MENSUEL + TOLERANCE_MONTANT:
                excedent = c.assiette - PASS_MENSUEL
                findings.append(Finding(
                    categorie=FindingCategory.DEPASSEMENT_SEUIL,
                    severite=Severity.HAUTE,
                    titre="Depassement du plafond de securite sociale (PASS)",
                    description=(
                        f"L'assiette de la vieillesse plafonnee ({c.assiette}) "
                        f"depasse le PASS mensuel ({PASS_MENSUEL}). "
                        f"Excedent : {excedent}."
                    ),
                    valeur_constatee=str(c.assiette),
                    valeur_attendue=f"<= {PASS_MENSUEL}",
                    montant_impact=excedent * c.taux_patronal if c.taux_patronal > 0 else excedent,
                    score_risque=85,
                    recommandation=(
                        "Le plafonnement au PASS n'est pas correctement applique. "
                        "Corriger l'assiette de la cotisation vieillesse plafonnee."
                    ),
                    detecte_par=self.nom,
                    documents_concernes=[c.source_document_id],
                    reference_legale="Art. L241-3 CSS - Plafond Securite Sociale 2026 : 4 005 EUR/mois",
                ))

        return findings
