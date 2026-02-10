"""Tests des regles metier URSSAF."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from decimal import Decimal
from urssaf_analyzer.config.constants import (
    ContributionType, PASS_MENSUEL, SMIC_MENSUEL_BRUT, SMIC_ANNUEL_BRUT,
    RGDU_SEUIL_SMIC_MULTIPLE,
)
from urssaf_analyzer.rules.contribution_rules import ContributionRules


class TestContributionRules:
    """Tests des regles de calcul des cotisations."""

    def setup_method(self):
        self.rules = ContributionRules(effectif_entreprise=25)

    def test_taux_maladie_patronal(self):
        taux = self.rules.get_taux_attendu_patronal(
            ContributionType.MALADIE, SMIC_MENSUEL_BRUT * 3
        )
        assert taux == Decimal("0.13")

    def test_taux_maladie_reduit(self):
        taux = self.rules.get_taux_attendu_patronal(
            ContributionType.MALADIE, SMIC_MENSUEL_BRUT * 2
        )
        # Salaire < 2.5 SMIC -> taux reduit
        assert taux == Decimal("0.07")

    def test_taux_vieillesse_plafonnee(self):
        taux = self.rules.get_taux_attendu_patronal(ContributionType.VIEILLESSE_PLAFONNEE)
        assert taux == Decimal("0.0855")

    def test_taux_vieillesse_deplafonnee_2026(self):
        """Le taux 2026 passe a 2.11%."""
        taux = self.rules.get_taux_attendu_patronal(ContributionType.VIEILLESSE_DEPLAFONNEE)
        assert taux == Decimal("0.0211")

    def test_assiette_plafonnee_sous_pass(self):
        brut = Decimal("3000")
        assiette = self.rules.calculer_assiette(
            ContributionType.VIEILLESSE_PLAFONNEE, brut
        )
        assert assiette == brut  # Sous le plafond

    def test_assiette_plafonnee_au_dessus_pass(self):
        brut = Decimal("6000")
        assiette = self.rules.calculer_assiette(
            ContributionType.VIEILLESSE_PLAFONNEE, brut
        )
        assert assiette == PASS_MENSUEL  # Plafonne

    def test_assiette_csg(self):
        brut = Decimal("3000")
        assiette = self.rules.calculer_assiette(
            ContributionType.CSG_DEDUCTIBLE, brut
        )
        # 98.25% du brut
        assert assiette == Decimal("2947.50")

    def test_calcul_montant_patronal(self):
        brut = Decimal("3000")
        montant = self.rules.calculer_montant_patronal(
            ContributionType.VIEILLESSE_PLAFONNEE, brut
        )
        # 3000 * 0.0855 = 256.50
        assert montant == Decimal("256.50")

    def test_verification_taux_conforme(self):
        conforme, _ = self.rules.verifier_taux(
            ContributionType.VIEILLESSE_PLAFONNEE,
            Decimal("0.0855"),
        )
        assert conforme is True

    def test_verification_taux_non_conforme(self):
        conforme, taux_attendu = self.rules.verifier_taux(
            ContributionType.VIEILLESSE_PLAFONNEE,
            Decimal("0.09"),  # Trop eleve
        )
        assert conforme is False
        assert taux_attendu == Decimal("0.0855")

    def test_fnal_moins_50_salaries(self):
        rules = ContributionRules(effectif_entreprise=30)
        taux = rules.get_taux_attendu_patronal(ContributionType.FNAL)
        assert taux == Decimal("0.001")

    def test_fnal_50_plus_salaries(self):
        rules = ContributionRules(effectif_entreprise=60)
        taux = rules.get_taux_attendu_patronal(ContributionType.FNAL)
        assert taux == Decimal("0.005")

    def test_rgdu_eligible(self):
        salaire = SMIC_ANNUEL_BRUT * 2  # 2 SMIC < 3 SMIC
        assert self.rules.est_eligible_rgdu(salaire) is True

    def test_rgdu_non_eligible(self):
        salaire = SMIC_ANNUEL_BRUT * 4  # 4 SMIC > 3 SMIC
        assert self.rules.est_eligible_rgdu(salaire) is False

    def test_rgdu_calcul(self):
        salaire = SMIC_ANNUEL_BRUT  # 1 SMIC -> reduction maximale
        reduction = self.rules.calculer_rgdu(salaire)
        assert reduction > 0

    def test_rgdu_au_dessus_seuil(self):
        salaire = SMIC_ANNUEL_BRUT * RGDU_SEUIL_SMIC_MULTIPLE + 1
        reduction = self.rules.calculer_rgdu(salaire)
        assert reduction == Decimal("0")
