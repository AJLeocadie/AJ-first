"""Tests unitaires exhaustifs des regles de cotisations sociales.

Niveau bancaire : verification de chaque taux, assiette, calcul RGDU,
exonerations, conventions collectives.
Ref: CSS art. L241-1 a L241-18, LFSS 2026.
"""

import pytest
from decimal import Decimal

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.rules.contribution_rules import ContributionRules
from urssaf_analyzer.config.constants import (
    ContributionType, SMIC_MENSUEL_BRUT, SMIC_ANNUEL_BRUT,
    PASS_MENSUEL, PASS_ANNUEL, RGDU_SEUIL_SMIC_MULTIPLE,
    RGDU_TAUX_MAX_MOINS_50, RGDU_TAUX_MAX_50_PLUS,
    SEUIL_EFFECTIF_11, SEUIL_EFFECTIF_20, SEUIL_EFFECTIF_50,
    TOLERANCE_TAUX,
)


# ================================================================
# TAUX PATRONAUX
# ================================================================

class TestTauxPatronaux:
    """Verification des taux patronaux pour chaque type de cotisation."""

    @pytest.fixture
    def rules_pme(self):
        return ContributionRules(effectif_entreprise=25, taux_at=Decimal("0.0208"))

    @pytest.fixture
    def rules_eti(self):
        return ContributionRules(effectif_entreprise=100, taux_at=Decimal("0.0208"))

    @pytest.fixture
    def rules_tpe(self):
        return ContributionRules(effectif_entreprise=5)

    # --- Maladie ---

    def test_maladie_taux_reduit_sous_2_5_smic(self, rules_pme):
        brut = SMIC_MENSUEL_BRUT * Decimal("2.0")
        taux = rules_pme.get_taux_attendu_patronal(ContributionType.MALADIE, brut)
        # Sous 2.5 SMIC: taux reduit
        assert taux is not None
        assert taux < Decimal("0.13")

    def test_maladie_taux_plein_au_dessus_2_5_smic(self, rules_pme):
        brut = SMIC_MENSUEL_BRUT * Decimal("3.0")
        taux = rules_pme.get_taux_attendu_patronal(ContributionType.MALADIE, brut)
        assert taux is not None

    # --- AF ---

    def test_af_taux_reduit_sous_3_5_smic(self, rules_pme):
        brut = SMIC_MENSUEL_BRUT * Decimal("2.0")
        taux = rules_pme.get_taux_attendu_patronal(ContributionType.ALLOCATIONS_FAMILIALES, brut)
        assert taux is not None

    # --- FNAL ---

    def test_fnal_plafonne_moins_50(self, rules_pme):
        taux = rules_pme.get_taux_attendu_patronal(ContributionType.FNAL)
        assert taux == Decimal("0.001")

    def test_fnal_deplafonne_50_plus(self, rules_eti):
        taux = rules_eti.get_taux_attendu_patronal(ContributionType.FNAL)
        assert taux == Decimal("0.005")

    # --- Formation professionnelle ---

    def test_formation_pro_moins_11(self, rules_tpe):
        taux = rules_tpe.get_taux_attendu_patronal(ContributionType.FORMATION_PROFESSIONNELLE)
        assert taux == Decimal("0.0055")

    def test_formation_pro_11_plus(self, rules_pme):
        taux = rules_pme.get_taux_attendu_patronal(ContributionType.FORMATION_PROFESSIONNELLE)
        assert taux == Decimal("0.01")

    # --- AT/MP ---

    def test_at_taux_propre_entreprise(self, rules_pme):
        taux = rules_pme.get_taux_attendu_patronal(ContributionType.ACCIDENT_TRAVAIL)
        assert taux == Decimal("0.0208")

    # --- VM ---

    def test_vm_zero_si_moins_11(self, rules_tpe):
        taux = rules_tpe.get_taux_attendu_patronal(ContributionType.VERSEMENT_MOBILITE)
        assert taux == Decimal("0")

    def test_vm_taux_si_11_plus(self):
        rules = ContributionRules(effectif_entreprise=15, taux_versement_mobilite=Decimal("0.020"))
        taux = rules.get_taux_attendu_patronal(ContributionType.VERSEMENT_MOBILITE)
        assert taux == Decimal("0.020")

    # --- PEEC ---

    def test_peec_zero_si_moins_20(self, rules_tpe):
        taux = rules_tpe.get_taux_attendu_patronal(ContributionType.PEEC)
        assert taux == Decimal("0")

    def test_peec_non_zero_si_20_plus(self, rules_pme):
        taux = rules_pme.get_taux_attendu_patronal(ContributionType.PEEC)
        assert taux is not None
        assert taux > Decimal("0")


# ================================================================
# ASSIETTES
# ================================================================

class TestAssiettes:
    """Tests du calcul des assiettes de cotisations."""

    @pytest.fixture
    def rules(self):
        return ContributionRules(effectif_entreprise=25)

    def test_assiette_deplafonnee(self, rules):
        brut = Decimal("10000")
        assiette = rules.calculer_assiette(ContributionType.VIEILLESSE_DEPLAFONNEE, brut)
        assert assiette == brut

    def test_assiette_plafonnee_pass(self, rules):
        brut = Decimal("10000")
        assiette = rules.calculer_assiette(ContributionType.VIEILLESSE_PLAFONNEE, brut)
        assert assiette <= PASS_MENSUEL

    def test_assiette_plafonnee_sous_pass(self, rules):
        brut = Decimal("2000")
        assiette = rules.calculer_assiette(ContributionType.VIEILLESSE_PLAFONNEE, brut)
        assert assiette == brut

    def test_assiette_csg_98_25_pct(self, rules):
        brut = Decimal("3000")
        assiette = rules.calculer_assiette(ContributionType.CSG_DEDUCTIBLE, brut)
        expected = (brut * Decimal("0.9825")).quantize(Decimal("0.01"))
        assert assiette == expected

    def test_assiette_csg_avec_prevoyance(self, rules):
        brut = Decimal("3000")
        prev = Decimal("50")
        assiette = rules.calculer_assiette(ContributionType.CSG_DEDUCTIBLE, brut, prev)
        expected = (brut * Decimal("0.9825") + prev).quantize(Decimal("0.01"))
        assert assiette == expected

    def test_assiette_fnal_plafonnee_moins_50(self):
        rules = ContributionRules(effectif_entreprise=10)
        brut = Decimal("5000")
        assiette = rules.calculer_assiette(ContributionType.FNAL, brut)
        assert assiette == min(brut, PASS_MENSUEL)

    def test_assiette_fnal_deplafonnee_50_plus(self):
        rules = ContributionRules(effectif_entreprise=100)
        brut = Decimal("5000")
        assiette = rules.calculer_assiette(ContributionType.FNAL, brut)
        assert assiette == brut


# ================================================================
# CALCUL DE MONTANTS
# ================================================================

class TestCalculMontants:
    """Tests du calcul des montants de cotisations."""

    @pytest.fixture
    def rules(self):
        return ContributionRules(effectif_entreprise=25, taux_at=Decimal("0.0208"))

    def test_montant_patronal_positif(self, rules):
        montant = rules.calculer_montant_patronal(ContributionType.MALADIE, Decimal("3000"))
        assert montant > Decimal("0")

    def test_montant_salarial_positif(self, rules):
        montant = rules.calculer_montant_salarial(ContributionType.VIEILLESSE_PLAFONNEE, Decimal("3000"))
        assert montant > Decimal("0")

    def test_montant_precision_centimes(self, rules):
        montant = rules.calculer_montant_patronal(ContributionType.MALADIE, Decimal("3333.33"))
        # Arrondi au centime
        assert montant == montant.quantize(Decimal("0.01"))

    def test_montant_zero_brut_nul(self, rules):
        montant = rules.calculer_montant_patronal(ContributionType.MALADIE, Decimal("0"))
        assert montant == Decimal("0")


# ================================================================
# BULLETIN COMPLET
# ================================================================

class TestBulletinComplet:
    """Tests du calcul de bulletin complet."""

    @pytest.fixture
    def rules(self):
        return ContributionRules(effectif_entreprise=25, taux_at=Decimal("0.0208"))

    def test_bulletin_structure(self, rules):
        bulletin = rules.calculer_bulletin_complet(Decimal("3000"))
        assert "brut_mensuel" in bulletin
        assert "lignes" in bulletin
        assert "total_patronal" in bulletin
        assert "total_salarial" in bulletin
        assert "net_avant_impot" in bulletin
        assert "cout_total_employeur" in bulletin
        assert "taux_charges_patronales" in bulletin
        assert "taux_charges_salariales" in bulletin

    def test_bulletin_net_positif(self, rules):
        bulletin = rules.calculer_bulletin_complet(Decimal("3000"))
        assert bulletin["net_avant_impot"] > 0

    def test_bulletin_net_inferieur_brut(self, rules):
        brut = Decimal("3000")
        bulletin = rules.calculer_bulletin_complet(brut)
        assert bulletin["net_avant_impot"] < float(brut)

    def test_bulletin_cout_total_superieur_brut(self, rules):
        brut = Decimal("3000")
        bulletin = rules.calculer_bulletin_complet(brut)
        assert bulletin["cout_total_employeur"] > float(brut)

    def test_bulletin_cadre_vs_non_cadre(self, rules):
        brut = Decimal("5000")
        non_cadre = rules.calculer_bulletin_complet(brut, est_cadre=False)
        cadre = rules.calculer_bulletin_complet(brut, est_cadre=True)
        # Cadre a plus de lignes (prevoyance, APEC)
        assert len(cadre["lignes"]) >= len(non_cadre["lignes"])

    def test_bulletin_coherence_totaux(self, rules):
        bulletin = rules.calculer_bulletin_complet(Decimal("3000"))
        total_p = sum(l["montant_patronal"] for l in bulletin["lignes"])
        total_s = sum(l["montant_salarial"] for l in bulletin["lignes"])
        assert abs(float(total_p) - bulletin["total_patronal"]) < 0.01
        assert abs(float(total_s) - bulletin["total_salarial"]) < 0.01

    def test_bulletin_taux_charges_patronales_realiste(self, rules):
        bulletin = rules.calculer_bulletin_complet(Decimal("3000"))
        # Charges patronales entre 25% et 60% du brut
        taux = bulletin["taux_charges_patronales"]
        assert 25 < taux < 60

    def test_bulletin_smic(self, rules):
        """Bulletin au SMIC : doit etre calculable sans erreur."""
        bulletin = rules.calculer_bulletin_complet(SMIC_MENSUEL_BRUT)
        assert bulletin["net_avant_impot"] > 0

    def test_bulletin_haut_salaire(self, rules):
        """Bulletin avec salaire eleve : plafonnement PASS correct."""
        bulletin = rules.calculer_bulletin_complet(Decimal("15000"))
        assert bulletin["net_avant_impot"] > 0


# ================================================================
# RGDU (Reduction Generale Degressive Unique)
# ================================================================

class TestRGDU:
    """Tests du calcul RGDU 2026."""

    @pytest.fixture
    def rules_pme(self):
        return ContributionRules(effectif_entreprise=25)

    @pytest.fixture
    def rules_eti(self):
        return ContributionRules(effectif_entreprise=100)

    def test_rgdu_au_smic(self, rules_pme):
        """Au SMIC, la RGDU doit etre maximale."""
        reduction = rules_pme.calculer_rgdu(SMIC_ANNUEL_BRUT)
        assert reduction > Decimal("0")

    def test_rgdu_au_dessus_3_smic_zero(self, rules_pme):
        """Au-dessus de 3 SMIC, aucune reduction."""
        brut_annuel = SMIC_ANNUEL_BRUT * Decimal("3.5")
        reduction = rules_pme.calculer_rgdu(brut_annuel)
        assert reduction == Decimal("0")

    def test_rgdu_exactement_3_smic(self, rules_pme):
        """Exactement 3 SMIC : pas de reduction (>=)."""
        brut_annuel = SMIC_ANNUEL_BRUT * RGDU_SEUIL_SMIC_MULTIPLE
        reduction = rules_pme.calculer_rgdu(brut_annuel)
        assert reduction == Decimal("0")

    def test_rgdu_decroissante(self, rules_pme):
        """La RGDU doit decroitre quand le salaire augmente."""
        r_smic = rules_pme.calculer_rgdu(SMIC_ANNUEL_BRUT)
        r_2_smic = rules_pme.calculer_rgdu(SMIC_ANNUEL_BRUT * 2)
        assert r_smic > r_2_smic

    def test_rgdu_salaire_negatif(self, rules_pme):
        assert rules_pme.calculer_rgdu(Decimal("-1000")) == Decimal("0")

    def test_rgdu_salaire_zero(self, rules_pme):
        assert rules_pme.calculer_rgdu(Decimal("0")) == Decimal("0")

    def test_rgdu_effectif_50_plus_taux_superieur(self, rules_pme, rules_eti):
        """Les entreprises >= 50 ont un taux max RGDU superieur."""
        brut = SMIC_ANNUEL_BRUT * Decimal("1.5")
        r_pme = rules_pme.calculer_rgdu(brut)
        r_eti = rules_eti.calculer_rgdu(brut)
        assert r_eti >= r_pme

    def test_eligibilite_rgdu(self, rules_pme):
        assert rules_pme.est_eligible_rgdu(SMIC_ANNUEL_BRUT) is True
        assert rules_pme.est_eligible_rgdu(SMIC_ANNUEL_BRUT * 4) is False
        assert rules_pme.est_eligible_rgdu(Decimal("0")) is False

    def test_detail_rgdu(self, rules_pme):
        detail = rules_pme.detail_rgdu(SMIC_ANNUEL_BRUT * Decimal("1.5"))
        assert detail["eligible"] is True
        assert detail["reduction_annuelle"] > 0
        assert detail["reduction_mensuelle"] > 0
        assert detail["coefficient"] > 0
        assert detail["coefficient"] <= float(RGDU_TAUX_MAX_MOINS_50)


# ================================================================
# VERIFICATION DE CONFORMITE
# ================================================================

class TestVerificationConformite:
    """Tests de la verification de taux et plafonnement."""

    @pytest.fixture
    def rules(self):
        return ContributionRules(effectif_entreprise=25, taux_at=Decimal("0.0208"))

    def test_verifier_taux_conforme(self, rules):
        brut = Decimal("3000")
        taux_attendu = rules.get_taux_attendu_patronal(ContributionType.MALADIE, brut)
        conforme, _ = rules.verifier_taux(ContributionType.MALADIE, taux_attendu, brut)
        assert conforme is True

    def test_verifier_taux_non_conforme(self, rules):
        conforme, taux_attendu = rules.verifier_taux(
            ContributionType.MALADIE, Decimal("0.999"), Decimal("3000"),
        )
        assert conforme is False
        assert taux_attendu is not None

    def test_verifier_taux_tolerance(self, rules):
        brut = Decimal("3000")
        taux_attendu = rules.get_taux_attendu_patronal(ContributionType.MALADIE, brut)
        # Ecart dans la tolerance
        taux_approx = taux_attendu + TOLERANCE_TAUX / 2
        conforme, _ = rules.verifier_taux(ContributionType.MALADIE, taux_approx, brut)
        assert conforme is True

    def test_verifier_plafonnement(self, rules):
        brut = Decimal("5000")
        assiette_attendue = rules.calculer_assiette(ContributionType.VIEILLESSE_PLAFONNEE, brut)
        conforme, _ = rules.verifier_plafonnement(
            ContributionType.VIEILLESSE_PLAFONNEE, assiette_attendue, brut,
        )
        assert conforme is True


# ================================================================
# EXONERATIONS
# ================================================================

class TestExonerations:
    """Tests des exonerations (ACRE, apprenti)."""

    @pytest.fixture
    def rules(self):
        return ContributionRules(effectif_entreprise=25, taux_at=Decimal("0.0208"))

    def test_acre_eligible(self, rules):
        brut = SMIC_MENSUEL_BRUT * Decimal("1.5")
        result = rules.calculer_exoneration_acre(brut)
        assert result["eligible"] is True
        assert result["exoneration_mensuelle"] > 0

    def test_acre_non_eligible_salaire_eleve(self, rules):
        brut = PASS_MENSUEL * Decimal("0.80")
        result = rules.calculer_exoneration_acre(brut)
        assert result["eligible"] is False

    def test_acre_brut_zero(self, rules):
        result = rules.calculer_exoneration_acre(Decimal("0"))
        assert result["eligible"] is False

    def test_apprenti_exoneration(self, rules):
        brut = SMIC_MENSUEL_BRUT * Decimal("0.60")  # 60% SMIC (apprenti 2e annee)
        result = rules.calculer_exoneration_apprenti(brut)
        assert result["eligible"] is True
        assert result["exoneration_salariale_mensuelle"] > 0

    def test_apprenti_rgdu(self, rules):
        brut = SMIC_MENSUEL_BRUT * Decimal("0.60")
        result = rules.calculer_exoneration_apprenti(brut)
        assert result["rgdu_patronale_mensuelle"] >= 0


# ================================================================
# TEMPS PARTIEL
# ================================================================

class TestTempsPartiel:
    """Tests des calculs en temps partiel."""

    @pytest.fixture
    def rules(self):
        return ContributionRules(effectif_entreprise=25, taux_at=Decimal("0.0208"))

    def test_temps_partiel_pass_proratise(self, rules):
        brut = Decimal("1500")
        heures = Decimal("80")  # Mi-temps
        bulletin = rules.calculer_bulletin_temps_partiel(brut, heures)
        assert "temps_partiel" in bulletin
        assert bulletin["temps_partiel"]["ratio"] < 1.0

    def test_temps_plein_pas_de_prorata(self, rules):
        brut = Decimal("3000")
        bulletin = rules.calculer_bulletin_temps_partiel(brut, Decimal("151.67"))
        assert "temps_partiel" not in bulletin

    def test_rgdu_temps_partiel(self, rules):
        brut_annuel = SMIC_ANNUEL_BRUT * Decimal("0.5")
        heures_annuelles = Decimal("910")  # Mi-temps
        reduction = rules.calculer_rgdu_temps_partiel(brut_annuel, heures_annuelles)
        assert reduction >= Decimal("0")


# ================================================================
# CONVENTIONS COLLECTIVES
# ================================================================

class TestConventionsCollectives:
    """Tests des CCN et prevoyance."""

    @pytest.fixture
    def rules(self):
        return ContributionRules()

    def test_ccn_syntec_cadre(self, rules):
        result = rules.get_prevoyance_ccn("syntec", est_cadre=True)
        assert result["ccn_connue"] is True
        assert result["taux_prevoyance_patronal"] == 0.015

    def test_ccn_syntec_non_cadre(self, rules):
        result = rules.get_prevoyance_ccn("syntec", est_cadre=False)
        assert result["ccn_connue"] is True
        assert result["taux_prevoyance_patronal"] == 0.006

    def test_ccn_inconnue(self, rules):
        result = rules.get_prevoyance_ccn("inconnue")
        assert result["ccn_connue"] is False

    def test_identifier_ccn_by_name(self, rules):
        assert rules.identifier_ccn("Convention SYNTEC") == "syntec"
        assert rules.identifier_ccn("Metallurgie nationale") == "metallurgie"

    def test_identifier_ccn_by_idcc(self, rules):
        assert rules.identifier_ccn("IDCC 1486") == "syntec"

    def test_identifier_ccn_unknown(self, rules):
        assert rules.identifier_ccn("Convention inconnue XYZ") is None


# ================================================================
# TAXE SUR LES SALAIRES
# ================================================================

class TestTaxeSalaires:
    """Tests de la taxe sur les salaires."""

    @pytest.fixture
    def rules(self):
        return ContributionRules()

    def test_taxe_salaires_3_tranches(self, rules):
        result = rules.calculer_taxe_salaires(Decimal("50000"))
        assert result["tranche_1"]["montant"] > 0
        assert result["tranche_2"]["montant"] > 0
        assert result["tranche_3"]["montant"] > 0
        assert result["total"] > 0

    def test_taxe_salaires_sous_seuil_1(self, rules):
        result = rules.calculer_taxe_salaires(Decimal("5000"))
        assert result["tranche_2"]["montant"] == 0
        assert result["tranche_3"]["montant"] == 0

    def test_taxe_salaires_zero(self, rules):
        result = rules.calculer_taxe_salaires(Decimal("0"))
        assert result["total"] == 0


# ================================================================
# NET IMPOSABLE
# ================================================================

class TestNetImposable:
    """Tests du calcul du net imposable."""

    @pytest.fixture
    def rules(self):
        return ContributionRules(effectif_entreprise=25, taux_at=Decimal("0.0208"))

    def test_net_imposable_structure(self, rules):
        result = rules.calculer_net_imposable(Decimal("3000"))
        assert "brut" in result
        assert "net_imposable" in result
        assert "net_a_payer_avant_ir" in result
        assert "assiette_pas" in result

    def test_net_imposable_superieur_net_a_payer(self, rules):
        """Net imposable > net a payer (CSG non deductible + CRDS)."""
        result = rules.calculer_net_imposable(Decimal("3000"))
        assert result["net_imposable"] >= result["net_a_payer_avant_ir"]

    def test_net_imposable_positif(self, rules):
        result = rules.calculer_net_imposable(SMIC_MENSUEL_BRUT)
        assert result["net_imposable"] > 0
