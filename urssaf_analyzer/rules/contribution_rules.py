"""Regles metier de calcul et validation des cotisations sociales.

Basees sur la reglementation URSSAF 2026 :
- RGDU (Reduction Generale Degressive Unique)
- Taux de cotisations du regime general
- Regles de plafonnement (PASS)
- Regles specifiques par effectif
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from urssaf_analyzer.config.constants import (
    ContributionType,
    TAUX_COTISATIONS_2026,
    PASS_MENSUEL,
    PASS_ANNUEL,
    SMIC_MENSUEL_BRUT,
    SMIC_ANNUEL_BRUT,
    RGDU_SEUIL_SMIC_MULTIPLE,
    TOLERANCE_TAUX,
    TOLERANCE_MONTANT,
)


class ContributionRules:
    """Regles de calcul et de validation des cotisations sociales 2026."""

    def __init__(self, effectif_entreprise: int = 0, taux_at: Decimal = Decimal("0.0208")):
        self.effectif = effectif_entreprise
        self.taux_at = taux_at

    def get_taux_attendu_patronal(self, type_cotisation: ContributionType, salaire_brut: Decimal = Decimal("0")) -> Optional[Decimal]:
        """Retourne le taux patronal attendu pour un type de cotisation."""
        taux = TAUX_COTISATIONS_2026.get(type_cotisation)
        if not taux:
            return None

        if type_cotisation == ContributionType.MALADIE:
            seuil = SMIC_MENSUEL_BRUT * taux.get("seuil_reduction_smic", Decimal("2.5"))
            if salaire_brut > 0 and salaire_brut <= seuil:
                return taux.get("patronal_reduit", taux["patronal"])
            return taux["patronal"]

        if type_cotisation == ContributionType.ALLOCATIONS_FAMILIALES:
            seuil = SMIC_MENSUEL_BRUT * taux.get("seuil_reduction_smic", Decimal("3.5"))
            if salaire_brut > 0 and salaire_brut <= seuil:
                return taux.get("patronal_reduit", taux["patronal"])
            return taux["patronal"]

        if type_cotisation == ContributionType.FNAL:
            if self.effectif >= 50:
                return taux.get("patronal_50_plus", Decimal("0.005"))
            return taux.get("patronal_moins_50", Decimal("0.001"))

        if type_cotisation == ContributionType.FORMATION_PROFESSIONNELLE:
            if self.effectif >= 11:
                return taux.get("patronal_11_plus", Decimal("0.01"))
            return taux.get("patronal_moins_11", Decimal("0.0055"))

        if type_cotisation == ContributionType.ACCIDENT_TRAVAIL:
            return self.taux_at

        return taux.get("patronal", taux.get("taux"))

    def get_taux_attendu_salarial(self, type_cotisation: ContributionType) -> Optional[Decimal]:
        """Retourne le taux salarial attendu."""
        taux = TAUX_COTISATIONS_2026.get(type_cotisation)
        if not taux:
            return None
        return taux.get("salarial", taux.get("taux"))

    def calculer_assiette(self, type_cotisation: ContributionType, brut_mensuel: Decimal) -> Decimal:
        """Calcule l'assiette de cotisation apres plafonnement."""
        taux = TAUX_COTISATIONS_2026.get(type_cotisation, {})

        # Cotisations plafonnees
        if "plafond" in taux:
            plafond = taux["plafond"]
            return min(brut_mensuel, plafond)

        # Cotisations avec plafond multiple du PASS
        if "plafond_multiple_pass" in taux:
            plafond = PASS_MENSUEL * taux["plafond_multiple_pass"]
            return min(brut_mensuel, plafond)

        # Cotisations avec plancher et plafond (tranche 2)
        if "plancher" in taux:
            plancher = taux["plancher"]
            plafond = PASS_MENSUEL * taux.get("plafond_multiple_pass", Decimal("8"))
            if brut_mensuel <= plancher:
                return Decimal("0")
            return min(brut_mensuel, plafond) - plancher

        # CSG/CRDS : assiette = 98.25% du brut
        if "assiette_pct" in taux:
            return (brut_mensuel * taux["assiette_pct"]).quantize(Decimal("0.01"), ROUND_HALF_UP)

        # Pas de plafonnement
        return brut_mensuel

    def calculer_montant_patronal(self, type_cotisation: ContributionType, brut_mensuel: Decimal) -> Decimal:
        """Calcule le montant de la cotisation patronale."""
        assiette = self.calculer_assiette(type_cotisation, brut_mensuel)
        taux = self.get_taux_attendu_patronal(type_cotisation, brut_mensuel)
        if taux is None:
            return Decimal("0")
        return (assiette * taux).quantize(Decimal("0.01"), ROUND_HALF_UP)

    def calculer_montant_salarial(self, type_cotisation: ContributionType, brut_mensuel: Decimal) -> Decimal:
        """Calcule le montant de la cotisation salariale."""
        assiette = self.calculer_assiette(type_cotisation, brut_mensuel)
        taux = self.get_taux_attendu_salarial(type_cotisation)
        if taux is None:
            return Decimal("0")
        return (assiette * taux).quantize(Decimal("0.01"), ROUND_HALF_UP)

    def verifier_taux(
        self, type_cotisation: ContributionType, taux_constate: Decimal,
        salaire_brut: Decimal = Decimal("0"), est_patronal: bool = True
    ) -> tuple[bool, Optional[Decimal]]:
        """Verifie si un taux est conforme. Retourne (conforme, taux_attendu)."""
        if est_patronal:
            taux_attendu = self.get_taux_attendu_patronal(type_cotisation, salaire_brut)
        else:
            taux_attendu = self.get_taux_attendu_salarial(type_cotisation)

        if taux_attendu is None:
            return True, None

        ecart = abs(taux_constate - taux_attendu)
        conforme = ecart <= TOLERANCE_TAUX
        return conforme, taux_attendu

    def verifier_plafonnement(
        self, type_cotisation: ContributionType, assiette_constatee: Decimal,
        brut_mensuel: Decimal
    ) -> tuple[bool, Decimal]:
        """Verifie si le plafonnement est correctement applique."""
        assiette_attendue = self.calculer_assiette(type_cotisation, brut_mensuel)
        ecart = abs(assiette_constatee - assiette_attendue)
        conforme = ecart <= TOLERANCE_MONTANT
        return conforme, assiette_attendue

    def calculer_rgdu(self, salaire_brut_annuel: Decimal) -> Decimal:
        """Calcule la RGDU (Reduction Generale Degressive Unique) 2026.

        La RGDU s'applique aux salaires < 3 SMIC annuel.
        Formule simplifiee : coefficient = (T / 0.6) * ((3 * SMIC * nb_heures / salaire) - 1)
        ou T est le taux maximal de reduction.
        """
        seuil = SMIC_ANNUEL_BRUT * RGDU_SEUIL_SMIC_MULTIPLE
        if salaire_brut_annuel >= seuil or salaire_brut_annuel <= 0:
            return Decimal("0")

        # Taux maximal de reduction (simplifie)
        t_max = Decimal("0.3194")  # Valeur 2026 approximative
        coeff = (t_max / Decimal("0.6")) * ((seuil / salaire_brut_annuel) - 1)
        coeff = min(coeff, t_max)  # Le coefficient ne peut depasser T
        reduction = (salaire_brut_annuel * coeff).quantize(Decimal("0.01"), ROUND_HALF_UP)
        return reduction

    def est_eligible_rgdu(self, salaire_brut_annuel: Decimal) -> bool:
        """Verifie si un salaire est eligible a la RGDU."""
        seuil = SMIC_ANNUEL_BRUT * RGDU_SEUIL_SMIC_MULTIPLE
        return Decimal("0") < salaire_brut_annuel < seuil
