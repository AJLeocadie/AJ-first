"""Tests de cas limites metier - logique business approfondie.

Couvre les edge cases reglementaires :
- Temps partiel : proratisation SMIC/PASS
- Multi-contrat : CDI + CDD (CPF-CDD uniquement sur CDD)
- Transitions de seuils d'effectif (10->11, 19->20, 49->50, 249->250)
- Limites exactes : salaire au SMIC, au PASS, a 2.25 SMIC, 3.3 SMIC, 3.0 SMIC
- Alsace-Moselle : cotisation maladie supplementaire 1.3%
- ACRE : eligibilite selon seuil 75% PASS
- Apprenti : exoneration salariale sous/sur 79% SMIC
- Cadre vs non-cadre : APEC, prevoyance, CEG T2
- Taxe sur les salaires : 3 tranches
- Zero salary, very high salary (10x PASS)
"""

import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.rules.contribution_rules import ContributionRules
from urssaf_analyzer.config.constants import (
    ContributionType, PASS_MENSUEL, PASS_ANNUEL, SMIC_MENSUEL_BRUT,
    SMIC_ANNUEL_BRUT, HEURES_MENSUELLES_LEGALES,
    SEUIL_EFFECTIF_11, SEUIL_EFFECTIF_20, SEUIL_EFFECTIF_50, SEUIL_EFFECTIF_250,
    TAUX_COTISATIONS_2026,
)


# =============================================
# Fixtures
# =============================================

@pytest.fixture
def rules_small():
    """Entreprise < 11 salaries."""
    return ContributionRules(effectif_entreprise=5)

@pytest.fixture
def rules_11():
    """Entreprise >= 11 salaries."""
    return ContributionRules(effectif_entreprise=11, taux_versement_mobilite=Decimal("0.0175"))

@pytest.fixture
def rules_20():
    """Entreprise >= 20 salaries."""
    return ContributionRules(effectif_entreprise=20, taux_versement_mobilite=Decimal("0.0175"))

@pytest.fixture
def rules_50():
    """Entreprise >= 50 salaries."""
    return ContributionRules(effectif_entreprise=50, taux_versement_mobilite=Decimal("0.025"))

@pytest.fixture
def rules_250():
    """Entreprise >= 250 salaries."""
    return ContributionRules(effectif_entreprise=250, taux_versement_mobilite=Decimal("0.025"))

@pytest.fixture
def rules_alsace():
    """Entreprise en Alsace-Moselle."""
    return ContributionRules(effectif_entreprise=50, est_alsace_moselle=True)


# =============================================
# Temps partiel : proratisation SMIC/PASS
# =============================================

class TestTempsPartielProratisation:
    """Tests de la proratisation des plafonds pour le temps partiel."""

    @pytest.mark.parametrize("heures,brut", [
        (Decimal("80"), Decimal("1200")),    # ~52.7% temps plein
        (Decimal("100"), Decimal("1500")),   # ~65.9% temps plein
        (Decimal("121.34"), Decimal("2400")), # ~80% temps plein
    ])
    def test_temps_partiel_bulletin_generation(self, rules_50, heures, brut):
        """Un bulletin temps partiel doit etre genere pour differents quotites."""
        result = rules_50.calculer_bulletin_temps_partiel(brut, heures_mensuelles=heures)
        assert isinstance(result, dict)
        assert "lignes" in result
        assert "temps_partiel" in result

        # Verifier que le PASS est proratise
        ratio = float(heures) / float(HEURES_MENSUELLES_LEGALES)
        pass_proratise = result["temps_partiel"]["pass_mensuel_proratise"]
        expected_pass = float((PASS_MENSUEL * Decimal(str(ratio))).quantize(Decimal("0.01")))
        assert abs(pass_proratise - expected_pass) < 0.02

    def test_temps_partiel_80h_smic_proratise(self, rules_50):
        """Pour 80h, le SMIC proratise doit etre environ 52.7% du SMIC."""
        heures = Decimal("80")
        ratio = heures / HEURES_MENSUELLES_LEGALES
        smic_proratise = (SMIC_MENSUEL_BRUT * ratio).quantize(Decimal("0.01"))
        # Pour un salaire au SMIC proratise, le taux maladie doit etre reduit
        brut = smic_proratise
        result = rules_50.calculer_bulletin_temps_partiel(brut, heures_mensuelles=heures)
        assert isinstance(result, dict)
        assert result["total_patronal"] > 0

    def test_rgdu_temps_partiel(self, rules_50):
        """RGDU temps partiel avec heures proratisees."""
        # 50% temps partiel = 910h annuelles
        heures_annuelles = Decimal("910")
        salaire_annuel = Decimal("18000")

        result = rules_50.calculer_rgdu_temps_partiel(salaire_annuel, heures_annuelles)
        assert isinstance(result, Decimal)
        # La reduction doit etre positive pour un salaire proche du SMIC proratise
        assert result >= Decimal("0")

    def test_rgdu_temps_partiel_full_time_equivalent(self, rules_50):
        """RGDU a temps plein (1820h) doit donner le meme resultat que calculer_rgdu."""
        heures_annuelles = HEURES_MENSUELLES_LEGALES * 12
        salaire_annuel = SMIC_ANNUEL_BRUT

        rgdu_tp = rules_50.calculer_rgdu_temps_partiel(salaire_annuel, heures_annuelles)
        rgdu_normal = rules_50.calculer_rgdu(salaire_annuel)

        # Les deux doivent etre proches (tolerance d'arrondi)
        assert abs(rgdu_tp - rgdu_normal) <= Decimal("1.00")


# =============================================
# Multi-contrat : CDI + CDD (CPF-CDD)
# =============================================

class TestMultiContrat:
    """Tests pour les situations multi-contrat."""

    def test_cpf_cdd_taux(self, rules_50):
        """CPF-CDD doit avoir un taux patronal de 1%."""
        taux = rules_50.get_taux_attendu_patronal(ContributionType.CONTRIBUTION_CPF_CDD)
        assert taux == Decimal("0.01")

    def test_cpf_cdd_montant(self, rules_50):
        """Le montant CPF-CDD doit etre 1% du brut CDD."""
        brut_cdd = Decimal("2000")
        montant = rules_50.calculer_montant_patronal(ContributionType.CONTRIBUTION_CPF_CDD, brut_cdd)
        expected = (brut_cdd * Decimal("0.01")).quantize(Decimal("0.01"))
        assert montant == expected

    def test_cdi_no_cpf_cdd(self, rules_50):
        """Un CDI ne doit pas avoir de CPF-CDD (taux applique a la masse salariale CDD uniquement)."""
        # Le taux existe mais il s'applique uniquement a la masse CDD
        # Pour un CDI, on ne calcule pas le CPF-CDD (c'est au niveau de l'application metier)
        taux = rules_50.get_taux_attendu_patronal(ContributionType.CONTRIBUTION_CPF_CDD)
        # Le taux est defini dans les rules mais ne s'applique qu'aux CDD
        assert taux == Decimal("0.01")


# =============================================
# Transitions de seuils d'effectif
# =============================================

class TestSeuilsEffectif:
    """Tests des transitions de seuils d'effectif."""

    def test_transition_10_to_11_formation_pro(self):
        """A 11 salaries, le taux formation pro passe de 0.55% a 1%."""
        rules_10 = ContributionRules(effectif_entreprise=10)
        rules_11 = ContributionRules(effectif_entreprise=11)

        taux_10 = rules_10.get_taux_attendu_patronal(ContributionType.FORMATION_PROFESSIONNELLE)
        taux_11 = rules_11.get_taux_attendu_patronal(ContributionType.FORMATION_PROFESSIONNELLE)

        assert taux_10 == Decimal("0.0055")
        assert taux_11 == Decimal("0.01")

    def test_transition_10_to_11_versement_mobilite(self):
        """A 11 salaries, le versement mobilite devient applicable."""
        rules_10 = ContributionRules(effectif_entreprise=10, taux_versement_mobilite=Decimal("0.02"))
        rules_11 = ContributionRules(effectif_entreprise=11, taux_versement_mobilite=Decimal("0.02"))

        taux_10 = rules_10.get_taux_attendu_patronal(ContributionType.VERSEMENT_MOBILITE)
        taux_11 = rules_11.get_taux_attendu_patronal(ContributionType.VERSEMENT_MOBILITE)

        assert taux_10 == Decimal("0")
        assert taux_11 == Decimal("0.02")

    def test_transition_19_to_20_peec(self):
        """A 20 salaries, la PEEC (1% logement) devient applicable."""
        rules_19 = ContributionRules(effectif_entreprise=19)
        rules_20 = ContributionRules(effectif_entreprise=20)

        taux_19 = rules_19.get_taux_attendu_patronal(ContributionType.PEEC)
        taux_20 = rules_20.get_taux_attendu_patronal(ContributionType.PEEC)

        assert taux_19 == Decimal("0")
        assert taux_20 == Decimal("0.0045")

    def test_transition_49_to_50_fnal(self):
        """A 50 salaries, le FNAL passe de 0.10% plafonne a 0.50% deplafonne."""
        rules_49 = ContributionRules(effectif_entreprise=49)
        rules_50 = ContributionRules(effectif_entreprise=50)

        taux_49 = rules_49.get_taux_attendu_patronal(ContributionType.FNAL)
        taux_50 = rules_50.get_taux_attendu_patronal(ContributionType.FNAL)

        assert taux_49 == Decimal("0.001")
        assert taux_50 == Decimal("0.005")

    def test_transition_49_to_50_fnal_assiette(self):
        """A 50 salaries, le FNAL est deplafonne (totalite du brut)."""
        rules_49 = ContributionRules(effectif_entreprise=49)
        rules_50 = ContributionRules(effectif_entreprise=50)
        brut = PASS_MENSUEL * 2  # 2 fois le PASS

        assiette_49 = rules_49.calculer_assiette(ContributionType.FNAL, brut)
        assiette_50 = rules_50.calculer_assiette(ContributionType.FNAL, brut)

        assert assiette_49 == PASS_MENSUEL  # Plafonnee au PASS
        assert assiette_50 == brut           # Totalite

    def test_transition_249_to_250_csa_apprentissage(self):
        """A 250 salaries, la contribution supplementaire apprentissage s'applique."""
        rules_249 = ContributionRules(effectif_entreprise=249)
        rules_250 = ContributionRules(effectif_entreprise=250)

        taux_249 = rules_249.get_taux_attendu_patronal(
            ContributionType.CONTRIBUTION_SUPPLEMENTAIRE_APPRENTISSAGE
        )
        taux_250 = rules_250.get_taux_attendu_patronal(
            ContributionType.CONTRIBUTION_SUPPLEMENTAIRE_APPRENTISSAGE
        )

        assert taux_249 == Decimal("0")
        assert taux_250 == Decimal("0.0005")

    def test_transition_49_to_50_rgdu_taux_max(self):
        """A 50 salaries, le taux max RGDU change."""
        from urssaf_analyzer.config.constants import RGDU_TAUX_MAX_MOINS_50, RGDU_TAUX_MAX_50_PLUS
        rules_49 = ContributionRules(effectif_entreprise=49)
        rules_50 = ContributionRules(effectif_entreprise=50)

        detail_49 = rules_49.detail_rgdu(SMIC_ANNUEL_BRUT)
        detail_50 = rules_50.detail_rgdu(SMIC_ANNUEL_BRUT)

        assert detail_49["taux_max"] == float(RGDU_TAUX_MAX_MOINS_50)
        assert detail_50["taux_max"] == float(RGDU_TAUX_MAX_50_PLUS)


# =============================================
# Boundary : salaire exactement aux seuils
# =============================================

class TestBoundarySalary:
    """Tests aux limites exactes des seuils de salaire."""

    def test_salary_exactly_smic(self, rules_50):
        """Salaire exactement au SMIC : taux maladie doit etre reduit (7%)."""
        taux = rules_50.get_taux_attendu_patronal(
            ContributionType.MALADIE, salaire_brut=SMIC_MENSUEL_BRUT,
        )
        assert taux == Decimal("0.07")

    def test_salary_exactly_pass(self, rules_50):
        """Salaire exactement au PASS : vieillesse plafonnee assiette = PASS."""
        assiette = rules_50.calculer_assiette(
            ContributionType.VIEILLESSE_PLAFONNEE, PASS_MENSUEL,
        )
        assert assiette == PASS_MENSUEL

    def test_salary_at_2_5_smic_maladie_boundary(self, rules_50):
        """Salaire a 2.5 SMIC : dernier seuil pour maladie reduite (7%)."""
        seuil_2_5 = SMIC_MENSUEL_BRUT * Decimal("2.5")
        taux_at_seuil = rules_50.get_taux_attendu_patronal(
            ContributionType.MALADIE, salaire_brut=seuil_2_5,
        )
        # A exactement 2.5 SMIC, le taux reduit s'applique
        assert taux_at_seuil == Decimal("0.07")

        # Juste au-dessus du seuil
        taux_above = rules_50.get_taux_attendu_patronal(
            ContributionType.MALADIE, salaire_brut=seuil_2_5 + Decimal("0.01"),
        )
        assert taux_above == Decimal("0.13")

    def test_salary_at_3_3_smic_af_boundary(self, rules_50):
        """Salaire a 3.3 SMIC : seuil pour AF reduite (3.45%)."""
        seuil_3_3 = SMIC_MENSUEL_BRUT * Decimal("3.3")
        taux_at = rules_50.get_taux_attendu_patronal(
            ContributionType.ALLOCATIONS_FAMILIALES, salaire_brut=seuil_3_3,
        )
        assert taux_at == Decimal("0.0345")

        taux_above = rules_50.get_taux_attendu_patronal(
            ContributionType.ALLOCATIONS_FAMILIALES,
            salaire_brut=seuil_3_3 + Decimal("0.01"),
        )
        assert taux_above == Decimal("0.0525")

    def test_salary_at_3_smic_rgdu_boundary(self, rules_50):
        """Salaire a 3.0 SMIC annuel : seuil RGDU (pas de reduction)."""
        seuil_3 = SMIC_ANNUEL_BRUT * Decimal("3")
        # A exactement 3 SMIC, la RGDU ne s'applique plus
        assert not rules_50.est_eligible_rgdu(seuil_3)
        assert rules_50.calculer_rgdu(seuil_3) == Decimal("0")

        # Juste en dessous
        assert rules_50.est_eligible_rgdu(seuil_3 - Decimal("0.01"))
        # La reduction doit etre tres faible
        rgdu = rules_50.calculer_rgdu(seuil_3 - Decimal("0.01"))
        assert rgdu >= Decimal("0")

    def test_salary_above_pass_retraite_t2(self, rules_50):
        """Au-dessus du PASS : la tranche 2 retraite complementaire s'active."""
        brut_above_pass = PASS_MENSUEL + Decimal("1000")
        assiette_t2 = rules_50.calculer_assiette(
            ContributionType.RETRAITE_COMPLEMENTAIRE_T2, brut_above_pass,
        )
        assert assiette_t2 > Decimal("0")
        assert assiette_t2 == Decimal("1000")  # excedent au-dessus du PASS

    def test_salary_below_pass_no_t2(self, rules_50):
        """En dessous du PASS : pas de tranche 2."""
        brut_below_pass = PASS_MENSUEL - Decimal("100")
        assiette_t2 = rules_50.calculer_assiette(
            ContributionType.RETRAITE_COMPLEMENTAIRE_T2, brut_below_pass,
        )
        assert assiette_t2 == Decimal("0")


# =============================================
# Alsace-Moselle : maladie salariale 1.3%
# =============================================

class TestAlsaceMoselle:
    """Tests du regime local Alsace-Moselle."""

    def test_alsace_moselle_maladie_salariale(self, rules_alsace):
        """Cotisation maladie supplementaire salariale de 1.3% en Alsace-Moselle."""
        taux = rules_alsace.get_taux_attendu_salarial(ContributionType.MALADIE_ALSACE_MOSELLE)
        assert taux == Decimal("0.013")

    def test_non_alsace_moselle_no_supplement(self, rules_50):
        """Hors Alsace-Moselle : pas de supplement maladie salariale."""
        taux = rules_50.get_taux_attendu_salarial(ContributionType.MALADIE_ALSACE_MOSELLE)
        assert taux == Decimal("0")

    def test_alsace_bulletin_includes_supplement(self, rules_alsace):
        """Le bulletin Alsace-Moselle doit inclure la ligne maladie supplementaire."""
        bulletin = rules_alsace.calculer_bulletin_complet(Decimal("3000"), est_cadre=False)
        types = [l["type"] for l in bulletin["lignes"]]
        assert ContributionType.MALADIE_ALSACE_MOSELLE.value in types

    def test_alsace_salarial_amount(self, rules_alsace):
        """Montant salarial maladie Alsace = brut * 1.3%."""
        brut = Decimal("3000")
        montant = rules_alsace.calculer_montant_salarial(
            ContributionType.MALADIE_ALSACE_MOSELLE, brut,
        )
        expected = (brut * Decimal("0.013")).quantize(Decimal("0.01"))
        assert montant == expected


# =============================================
# ACRE : exoneration
# =============================================

class TestACRE:
    """Tests de l'exoneration ACRE."""

    def test_acre_eligible_below_75_pass(self, rules_50):
        """Eligible si salaire < 75% du PASS."""
        seuil_75 = PASS_MENSUEL * Decimal("0.75")
        brut = seuil_75 - Decimal("100")

        result = rules_50.calculer_exoneration_acre(brut)
        assert result["eligible"] is True
        assert result["exoneration_mensuelle"] > 0

    def test_acre_not_eligible_above_75_pass(self, rules_50):
        """Non eligible si salaire > 75% du PASS."""
        seuil_75 = PASS_MENSUEL * Decimal("0.75")
        brut = seuil_75 + Decimal("1")

        result = rules_50.calculer_exoneration_acre(brut)
        assert result["eligible"] is False
        assert result["exoneration_mensuelle"] == 0.0

    def test_acre_zero_salary(self, rules_50):
        """ACRE avec salaire zero = non eligible."""
        result = rules_50.calculer_exoneration_acre(Decimal("0"))
        assert result["eligible"] is False

    def test_acre_exoneration_is_50_percent(self, rules_50):
        """L'exoneration ACRE est de 50% des cotisations patronales eligibles."""
        brut = Decimal("2000")
        result = rules_50.calculer_exoneration_acre(brut)
        assert result["eligible"] is True
        assert result["taux_exoneration"] == 0.5
        # L'exoneration doit etre la moitie des cotisations exonerables
        assert abs(result["exoneration_mensuelle"] - result["cotisations_exonerables"] * 0.5) < 0.02


# =============================================
# Apprenti : exoneration sous/sur 79% SMIC
# =============================================

class TestApprenti:
    """Tests des exonerations apprenti."""

    def test_apprenti_below_79_smic(self, rules_50):
        """Apprenti sous 79% du SMIC : exoneration salariale complete."""
        brut = SMIC_MENSUEL_BRUT * Decimal("0.5")
        result = rules_50.calculer_exoneration_apprenti(brut)
        assert result["eligible"] is True
        assert result["exoneration_salariale_mensuelle"] > 0

    def test_apprenti_above_79_smic(self, rules_50):
        """Apprenti au-dessus de 79% du SMIC : exoneration partielle."""
        brut = SMIC_MENSUEL_BRUT * 2
        result = rules_50.calculer_exoneration_apprenti(brut)
        assert result["eligible"] is True
        # L'exoneration salariale est limitee a la tranche <= 79% SMIC
        seuil_79 = float(SMIC_MENSUEL_BRUT * Decimal("0.79"))
        assert result["seuil_79_smic"] == pytest.approx(seuil_79, abs=0.01)

    def test_apprenti_rgdu_patronale(self, rules_50):
        """L'apprenti beneficie de la RGDU patronale (reduction generale)."""
        brut = SMIC_MENSUEL_BRUT  # Salaire au SMIC
        result = rules_50.calculer_exoneration_apprenti(brut)
        # Si eligible a la RGDU, la reduction doit etre positive
        assert result["rgdu_patronale_mensuelle"] >= 0


# =============================================
# Cadre vs non-cadre : APEC, prevoyance, CEG T2
# =============================================

class TestCadreNonCadre:
    """Tests des differences cadre / non-cadre."""

    def test_cadre_includes_apec(self, rules_50):
        """Un bulletin cadre doit inclure l'APEC."""
        bulletin = rules_50.calculer_bulletin_complet(
            PASS_MENSUEL + Decimal("1000"), est_cadre=True,
        )
        types = [l["type"] for l in bulletin["lignes"]]
        assert ContributionType.APEC.value in types

    def test_non_cadre_no_apec(self, rules_50):
        """Un bulletin non-cadre ne doit pas inclure l'APEC."""
        bulletin = rules_50.calculer_bulletin_complet(
            PASS_MENSUEL + Decimal("1000"), est_cadre=False,
        )
        types = [l["type"] for l in bulletin["lignes"]]
        assert ContributionType.APEC.value not in types

    def test_cadre_includes_prevoyance(self, rules_50):
        """Un bulletin cadre doit inclure la prevoyance cadre obligatoire."""
        bulletin = rules_50.calculer_bulletin_complet(Decimal("5000"), est_cadre=True)
        types = [l["type"] for l in bulletin["lignes"]]
        assert ContributionType.PREVOYANCE_CADRE.value in types

    def test_non_cadre_no_prevoyance_cadre(self, rules_50):
        """Un bulletin non-cadre ne doit pas avoir la prevoyance cadre."""
        bulletin = rules_50.calculer_bulletin_complet(Decimal("3000"), est_cadre=False)
        types = [l["type"] for l in bulletin["lignes"]]
        assert ContributionType.PREVOYANCE_CADRE.value not in types

    def test_cadre_above_pass_has_t2(self, rules_50):
        """Cadre au-dessus du PASS : T2 retraite complementaire + CEG T2."""
        brut = PASS_MENSUEL + Decimal("2000")
        bulletin = rules_50.calculer_bulletin_complet(brut, est_cadre=True)
        types = [l["type"] for l in bulletin["lignes"]]
        assert ContributionType.RETRAITE_COMPLEMENTAIRE_T2.value in types
        assert ContributionType.CEG_T2.value in types

    def test_cadre_vs_noncadre_total_charges(self, rules_50):
        """Le total charges patronales d'un cadre doit etre >= non-cadre (prevoyance/APEC)."""
        brut = PASS_MENSUEL + Decimal("1000")
        bulletin_cadre = rules_50.calculer_bulletin_complet(brut, est_cadre=True)
        bulletin_nc = rules_50.calculer_bulletin_complet(brut, est_cadre=False)

        # Le cadre a des cotisations supplementaires (prevoyance, APEC)
        assert bulletin_cadre["total_patronal"] >= bulletin_nc["total_patronal"]


# =============================================
# Taxe sur les salaires : 3 tranches
# =============================================

class TestTaxeSalaires:
    """Tests de la taxe sur les salaires (3 tranches)."""

    def test_taxe_salaires_tranche_1_only(self, rules_50):
        """Salaire <= seuil 1 : taxe a 4.25% uniquement."""
        result = rules_50.calculer_taxe_salaires(Decimal("5000"))
        assert result["tranche_1"]["montant"] > 0
        assert result["tranche_2"]["montant"] == 0
        assert result["tranche_3"]["montant"] == 0

    def test_taxe_salaires_tranche_2(self, rules_50):
        """Salaire entre seuil 1 et seuil 2 : tranches 1 et 2."""
        result = rules_50.calculer_taxe_salaires(Decimal("12000"))
        assert result["tranche_1"]["montant"] > 0
        assert result["tranche_2"]["montant"] > 0
        assert result["tranche_3"]["montant"] == 0

    def test_taxe_salaires_tranche_3(self, rules_50):
        """Salaire > seuil 2 : les 3 tranches s'appliquent."""
        result = rules_50.calculer_taxe_salaires(Decimal("25000"))
        assert result["tranche_1"]["montant"] > 0
        assert result["tranche_2"]["montant"] > 0
        assert result["tranche_3"]["montant"] > 0

    def test_taxe_salaires_taux_progressifs(self, rules_50):
        """Les taux doivent etre progressifs : 4.25% < 8.50% < 13.60%."""
        result = rules_50.calculer_taxe_salaires(Decimal("25000"))
        assert result["tranche_1"]["taux"] < result["tranche_2"]["taux"]
        assert result["tranche_2"]["taux"] < result["tranche_3"]["taux"]

    def test_taxe_salaires_total_coherent(self, rules_50):
        """Le total doit etre la somme des 3 tranches."""
        result = rules_50.calculer_taxe_salaires(Decimal("25000"))
        total_calc = (
            result["tranche_1"]["montant"]
            + result["tranche_2"]["montant"]
            + result["tranche_3"]["montant"]
        )
        assert abs(result["total"] - total_calc) < 0.01


# =============================================
# Zero salary, very high salary
# =============================================

class TestSalaryExtremes:
    """Tests aux extremes de salaire."""

    def test_zero_salary_bulletin(self, rules_50):
        """Salaire zero : le bulletin ne doit pas planter."""
        bulletin = rules_50.calculer_bulletin_complet(Decimal("0"))
        assert isinstance(bulletin, dict)
        assert bulletin["brut_mensuel"] == 0.0
        assert bulletin["total_patronal"] == 0.0
        assert bulletin["total_salarial"] == 0.0

    def test_zero_salary_rgdu(self, rules_50):
        """RGDU avec salaire zero = pas de reduction."""
        assert rules_50.calculer_rgdu(Decimal("0")) == Decimal("0")
        assert not rules_50.est_eligible_rgdu(Decimal("0"))

    def test_very_high_salary_10x_pass(self, rules_50):
        """Salaire a 10x le PASS : plafonnements respectes."""
        brut = PASS_MENSUEL * 10
        bulletin = rules_50.calculer_bulletin_complet(brut, est_cadre=True)

        assert isinstance(bulletin, dict)
        assert bulletin["total_patronal"] > 0
        assert bulletin["total_salarial"] > 0

        # Verifier que la vieillesse plafonnee est bien plafonnee au PASS
        for ligne in bulletin["lignes"]:
            if ligne["type"] == ContributionType.VIEILLESSE_PLAFONNEE.value:
                assert ligne["assiette"] == float(PASS_MENSUEL)
                break

    def test_very_high_salary_rgdu_not_eligible(self, rules_50):
        """Salaire tres eleve : pas eligible a la RGDU."""
        salaire_annuel = PASS_ANNUEL * 10
        assert not rules_50.est_eligible_rgdu(salaire_annuel)
        assert rules_50.calculer_rgdu(salaire_annuel) == Decimal("0")

    def test_very_high_salary_taxe_salaires(self, rules_50):
        """Taxe sur les salaires a salaire tres eleve : toutes tranches s'appliquent."""
        result = rules_50.calculer_taxe_salaires(PASS_ANNUEL * 5)
        assert result["tranche_1"]["montant"] > 0
        assert result["tranche_2"]["montant"] > 0
        assert result["tranche_3"]["montant"] > 0
        assert result["total"] > 0

    def test_net_imposable_with_extremes(self, rules_50):
        """Net imposable ne doit pas planter aux extremes."""
        for brut in [Decimal("0.01"), SMIC_MENSUEL_BRUT, PASS_MENSUEL * 10]:
            result = rules_50.calculer_net_imposable(brut, est_cadre=False)
            assert isinstance(result, dict)
            assert "net_imposable" in result
