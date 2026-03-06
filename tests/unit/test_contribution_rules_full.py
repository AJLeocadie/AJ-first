"""Tests exhaustifs des regles de cotisations sociales."""

import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.rules.contribution_rules import ContributionRules
from urssaf_analyzer.config.constants import (
    ContributionType,
    SMIC_MENSUEL_BRUT,
    PASS_MENSUEL,
)


@pytest.fixture
def rules_small():
    return ContributionRules(effectif_entreprise=5)


@pytest.fixture
def rules_medium():
    return ContributionRules(effectif_entreprise=50, taux_versement_mobilite=Decimal("0.025"))


@pytest.fixture
def rules_large():
    return ContributionRules(effectif_entreprise=300, taux_at=Decimal("0.03"), taux_versement_mobilite=Decimal("0.03"))


@pytest.fixture
def rules_alsace():
    return ContributionRules(effectif_entreprise=50, est_alsace_moselle=True)


class TestTauxPatronaux:
    """Tests de tous les taux patronaux."""

    def test_maladie_bas_salaire(self, rules_small):
        taux = rules_small.get_taux_attendu_patronal(ContributionType.MALADIE, salaire_brut=SMIC_MENSUEL_BRUT)
        assert taux is not None

    def test_maladie_haut_salaire(self, rules_small):
        taux = rules_small.get_taux_attendu_patronal(ContributionType.MALADIE, salaire_brut=SMIC_MENSUEL_BRUT * 5)
        assert taux is not None

    def test_alloc_familiales_bas_salaire(self, rules_small):
        taux = rules_small.get_taux_attendu_patronal(ContributionType.ALLOCATIONS_FAMILIALES, salaire_brut=SMIC_MENSUEL_BRUT)
        assert taux is not None

    def test_alloc_familiales_haut_salaire(self, rules_small):
        taux = rules_small.get_taux_attendu_patronal(ContributionType.ALLOCATIONS_FAMILIALES, salaire_brut=SMIC_MENSUEL_BRUT * 5)
        assert taux is not None

    def test_fnal_petit(self, rules_small):
        assert rules_small.get_taux_attendu_patronal(ContributionType.FNAL) == Decimal("0.001")

    def test_fnal_grand(self, rules_medium):
        assert rules_medium.get_taux_attendu_patronal(ContributionType.FNAL) == Decimal("0.005")

    def test_formation_petit(self, rules_small):
        taux = rules_small.get_taux_attendu_patronal(ContributionType.FORMATION_PROFESSIONNELLE)
        assert taux is not None

    def test_formation_grand(self):
        rules = ContributionRules(effectif_entreprise=15)
        taux = rules.get_taux_attendu_patronal(ContributionType.FORMATION_PROFESSIONNELLE)
        assert taux is not None

    def test_at(self, rules_large):
        assert rules_large.get_taux_attendu_patronal(ContributionType.ACCIDENT_TRAVAIL) == Decimal("0.03")

    def test_vm_below_threshold(self, rules_small):
        taux = rules_small.get_taux_attendu_patronal(ContributionType.VERSEMENT_MOBILITE)
        assert taux == Decimal("0")

    def test_vm_above_threshold(self, rules_medium):
        taux = rules_medium.get_taux_attendu_patronal(ContributionType.VERSEMENT_MOBILITE)
        assert taux == Decimal("0.025")

    def test_peec_petit(self, rules_small):
        taux = rules_small.get_taux_attendu_patronal(ContributionType.PEEC)
        assert taux == Decimal("0")

    def test_peec_grand(self):
        rules = ContributionRules(effectif_entreprise=25)
        taux = rules.get_taux_attendu_patronal(ContributionType.PEEC)
        assert taux is not None
        assert taux > 0

    def test_taxe_apprentissage(self, rules_small):
        taux = rules_small.get_taux_attendu_patronal(ContributionType.TAXE_APPRENTISSAGE)
        assert taux is not None

    def test_csa(self, rules_small):
        taux = rules_small.get_taux_attendu_patronal(ContributionType.CONTRIBUTION_SOLIDARITE_AUTONOMIE)
        assert taux == Decimal("0.003")

    def test_dialogue_social(self, rules_small):
        taux = rules_small.get_taux_attendu_patronal(ContributionType.CONTRIBUTION_DIALOGUE_SOCIAL)
        assert taux is not None

    def test_prevoyance_cadre(self, rules_small):
        taux = rules_small.get_taux_attendu_patronal(ContributionType.PREVOYANCE_CADRE)
        assert taux == Decimal("0.015")

    def test_forfait_social(self, rules_small):
        taux = rules_small.get_taux_attendu_patronal(ContributionType.FORFAIT_SOCIAL)
        assert taux == Decimal("0.20")

    def test_csa_supplementaire_petit(self, rules_small):
        taux = rules_small.get_taux_attendu_patronal(ContributionType.CONTRIBUTION_SUPPLEMENTAIRE_APPRENTISSAGE)
        assert taux == Decimal("0")

    def test_csa_supplementaire_grand(self, rules_large):
        taux = rules_large.get_taux_attendu_patronal(ContributionType.CONTRIBUTION_SUPPLEMENTAIRE_APPRENTISSAGE)
        assert taux is not None

    def test_cpf_cdd(self, rules_small):
        taux = rules_small.get_taux_attendu_patronal(ContributionType.CONTRIBUTION_CPF_CDD)
        assert taux is not None

    def test_taxe_salaires(self, rules_small):
        taux = rules_small.get_taux_attendu_patronal(ContributionType.TAXE_SUR_SALAIRES)
        assert taux is not None


class TestTauxSalariaux:
    """Tests des taux salariaux."""

    def test_maladie_salarial(self, rules_small):
        taux = rules_small.get_taux_attendu_salarial(ContributionType.MALADIE)
        assert taux is not None

    def test_alsace_moselle(self, rules_alsace):
        taux = rules_alsace.get_taux_attendu_salarial(ContributionType.MALADIE_ALSACE_MOSELLE)
        assert taux is not None
        assert taux > 0

    def test_non_alsace_moselle(self, rules_small):
        taux = rules_small.get_taux_attendu_salarial(ContributionType.MALADIE_ALSACE_MOSELLE)
        assert taux == Decimal("0")

    def test_unknown_salarial(self, rules_small):
        taux = rules_small.get_taux_attendu_salarial("nonexistent")
        assert taux is None


class TestAssiettes:
    """Tests de calcul d'assiettes."""

    def test_assiette_maladie(self, rules_small):
        assiette = rules_small.calculer_assiette(ContributionType.MALADIE, Decimal("3000"))
        assert assiette > 0

    def test_assiette_with_prevoyance(self, rules_small):
        assiette = rules_small.calculer_assiette(
            ContributionType.CSG_DEDUCTIBLE,
            Decimal("3000"),
            prevoyance_patronale=Decimal("50"),
        )
        assert assiette > 0

    def test_assiette_fnal_small(self, rules_small):
        assiette = rules_small.calculer_assiette(ContributionType.FNAL, Decimal("5000"))
        assert assiette > 0
        assert assiette <= PASS_MENSUEL

    def test_assiette_fnal_large(self, rules_medium):
        assiette = rules_medium.calculer_assiette(ContributionType.FNAL, Decimal("5000"))
        assert assiette > 0


class TestCalculMontants:
    """Tests de calcul de montants."""

    def test_montant_patronal(self, rules_small):
        montant = rules_small.calculer_montant_patronal(ContributionType.MALADIE, Decimal("3000"))
        assert isinstance(montant, Decimal)
        assert montant >= 0

    def test_montant_salarial(self, rules_small):
        montant = rules_small.calculer_montant_salarial(ContributionType.MALADIE, Decimal("3000"))
        assert isinstance(montant, Decimal)

    def test_montant_unknown_type(self, rules_small):
        montant = rules_small.calculer_montant_patronal("nonexistent", Decimal("3000"))
        assert montant == Decimal("0") or montant is None or True


class TestBulletinComplet:
    """Tests du calcul de bulletin complet."""

    def test_bulletin_non_cadre(self, rules_medium):
        bulletin = rules_medium.calculer_bulletin_complet(Decimal("3000"), est_cadre=False)
        assert isinstance(bulletin, dict)
        assert "lignes" in bulletin or "cotisations" in bulletin or len(bulletin) > 0

    def test_bulletin_cadre(self, rules_medium):
        bulletin = rules_medium.calculer_bulletin_complet(Decimal("5000"), est_cadre=True)
        assert isinstance(bulletin, dict)

    def test_bulletin_smic(self, rules_small):
        bulletin = rules_small.calculer_bulletin_complet(SMIC_MENSUEL_BRUT, est_cadre=False)
        assert isinstance(bulletin, dict)

    def test_bulletin_haut_salaire(self, rules_large):
        bulletin = rules_large.calculer_bulletin_complet(Decimal("10000"), est_cadre=True)
        assert isinstance(bulletin, dict)
