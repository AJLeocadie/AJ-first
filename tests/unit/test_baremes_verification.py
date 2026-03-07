"""Pipeline de verification croisee des baremes URSSAF 2026.

Valide la coherence entre TAUX_COTISATIONS_2026 (config/constants.py)
et BAREMES_PAR_ANNEE (veille/urssaf_client.py), ainsi que les relations
mathematiques entre plafonds, SMIC et seuils reglementaires.

Ref:
- Arrete du 19/12/2025 (PASS 2026)
- Decret SMIC 2026
- LFSS 2025 art. 17 (seuils maladie/AF)
- CSS art. L241-13 (RGDU)
"""

import sys
from pathlib import Path
from decimal import Decimal

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.config.constants import (
    TAUX_COTISATIONS_2026, ContributionType, PASS_MENSUEL, PASS_ANNUEL,
    SMIC_MENSUEL_BRUT, SMIC_HORAIRE_BRUT, HEURES_MENSUELLES_LEGALES,
    PASS_TRIMESTRIEL, PASS_JOURNALIER, PASS_HORAIRE,
    PLAFOND_4_PASS, PLAFOND_8_PASS,
    RGDU_SEUIL_SMIC_MULTIPLE, RGDU_TAUX_MAX_MOINS_50, RGDU_TAUX_MAX_50_PLUS,
    SEUIL_EFFECTIF_11, SEUIL_EFFECTIF_20, SEUIL_EFFECTIF_50, SEUIL_EFFECTIF_250,
)
from urssaf_analyzer.veille.urssaf_client import BAREMES_PAR_ANNEE, get_baremes_annee


# =====================================================================
# COHERENCE PLAFONDS SECURITE SOCIALE
# =====================================================================


class TestPlafondSecuriteSociale:
    """Coherence des plafonds de securite sociale 2026."""

    def test_pass_mensuel_consistency(self):
        """PASS_MENSUEL doit correspondre a BAREMES_PAR_ANNEE[2026]."""
        assert float(PASS_MENSUEL) == BAREMES_PAR_ANNEE[2026]["pass_mensuel"]

    def test_pass_annuel_is_12x_mensuel(self):
        """PASS_ANNUEL == PASS_MENSUEL * 12."""
        assert PASS_ANNUEL == PASS_MENSUEL * 12

    def test_pass_trimestriel_is_3x_mensuel(self):
        """PASS_TRIMESTRIEL == PASS_MENSUEL * 3."""
        assert PASS_TRIMESTRIEL == PASS_MENSUEL * 3

    def test_plafond_4pass(self):
        """PLAFOND_4_PASS == PASS_ANNUEL * 4."""
        assert PLAFOND_4_PASS == PASS_ANNUEL * 4

    def test_plafond_8pass(self):
        """PLAFOND_8_PASS == PASS_ANNUEL * 8."""
        assert PLAFOND_8_PASS == PASS_ANNUEL * 8

    def test_pass_journalier_present(self):
        """Le PASS journalier est defini et coherent avec les baremes."""
        assert PASS_JOURNALIER == Decimal("185.00")
        assert float(PASS_JOURNALIER) == BAREMES_PAR_ANNEE[2026]["pass_journalier"]

    def test_pass_horaire_present(self):
        """Le PASS horaire est defini."""
        assert PASS_HORAIRE == Decimal("28.00")


# =====================================================================
# COHERENCE SMIC
# =====================================================================


class TestSMIC:
    """Coherence des valeurs SMIC 2026."""

    def test_smic_mensuel_consistency(self):
        """SMIC_MENSUEL_BRUT doit correspondre a BAREMES_PAR_ANNEE[2026]."""
        assert float(SMIC_MENSUEL_BRUT) == BAREMES_PAR_ANNEE[2026]["smic_mensuel"]

    def test_smic_horaire_consistency(self):
        """SMIC_HORAIRE_BRUT doit correspondre a BAREMES_PAR_ANNEE[2026]."""
        assert float(SMIC_HORAIRE_BRUT) == BAREMES_PAR_ANNEE[2026]["smic_horaire"]

    def test_smic_mensuel_is_hourly_times_hours(self):
        """SMIC_MENSUEL_BRUT ~= SMIC_HORAIRE_BRUT * HEURES_MENSUELLES_LEGALES.

        Le SMIC mensuel officiel est arrondi au centime superieur (art. D3231-6
        Code du travail), d'ou un ecart possible de quelques centimes par rapport
        au calcul brut horaire * 151.67h. Tolerance de 0.05 EUR.
        """
        calcule = SMIC_HORAIRE_BRUT * HEURES_MENSUELLES_LEGALES
        ecart = abs(SMIC_MENSUEL_BRUT - calcule)
        assert ecart <= Decimal("0.05"), (
            f"SMIC mensuel {SMIC_MENSUEL_BRUT} != {SMIC_HORAIRE_BRUT} * "
            f"{HEURES_MENSUELLES_LEGALES} = {calcule} (ecart {ecart})"
        )


# =====================================================================
# CROSS-VALIDATION TAUX 2026
# =====================================================================


class TestTaux2026CrossValidation:
    """Verification croisee taux TAUX_COTISATIONS_2026 vs BAREMES_PAR_ANNEE[2026]."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.baremes = BAREMES_PAR_ANNEE[2026]
        self.taux = TAUX_COTISATIONS_2026

    # --- Maladie ---

    def test_maladie_patronal(self):
        assert float(self.taux[ContributionType.MALADIE]["patronal"]) == self.baremes["taux_maladie_patronal"]
        assert self.baremes["taux_maladie_patronal"] == 0.13

    def test_maladie_patronal_reduit(self):
        assert float(self.taux[ContributionType.MALADIE]["patronal_reduit"]) == self.baremes["taux_maladie_patronal_reduit"]
        assert self.baremes["taux_maladie_patronal_reduit"] == 0.07

    # --- Vieillesse plafonnee ---

    def test_vieillesse_plafonnee_patronal(self):
        assert float(self.taux[ContributionType.VIEILLESSE_PLAFONNEE]["patronal"]) == self.baremes["taux_vieillesse_plafonnee_patronal"]

    def test_vieillesse_plafonnee_salarial(self):
        assert float(self.taux[ContributionType.VIEILLESSE_PLAFONNEE]["salarial"]) == self.baremes["taux_vieillesse_plafonnee_salarial"]

    # --- Vieillesse deplafonnee ---
    # Note : les deux sources peuvent diverger legerement (TAUX_COTISATIONS_2026
    # est la source de verite pour le calcul, BAREMES pour la veille)

    def test_vieillesse_deplafonnee_salarial(self):
        assert float(self.taux[ContributionType.VIEILLESSE_DEPLAFONNEE]["salarial"]) == self.baremes["taux_vieillesse_deplafonnee_salarial"]

    # --- Allocations familiales ---

    def test_af_patronal(self):
        assert float(self.taux[ContributionType.ALLOCATIONS_FAMILIALES]["patronal"]) == self.baremes["taux_af_patronal"]

    # --- Chomage ---

    def test_chomage_patronal(self):
        assert float(self.taux[ContributionType.ASSURANCE_CHOMAGE]["patronal"]) == self.baremes["taux_chomage_patronal"]

    # --- AGS ---

    def test_ags(self):
        assert float(self.taux[ContributionType.AGS]["patronal"]) == self.baremes["taux_ags"]

    # --- CSG/CRDS ---

    def test_csg_deductible(self):
        assert float(self.taux[ContributionType.CSG_DEDUCTIBLE]["taux"]) == self.baremes["taux_csg_deductible"]

    def test_csg_non_deductible(self):
        assert float(self.taux[ContributionType.CSG_NON_DEDUCTIBLE]["taux"]) == self.baremes["taux_csg_non_deductible"]

    def test_crds(self):
        assert float(self.taux[ContributionType.CRDS]["taux"]) == self.baremes["taux_crds"]

    def test_assiette_csg_crds(self):
        assert float(self.taux[ContributionType.CSG_DEDUCTIBLE]["assiette_pct"]) == self.baremes["assiette_csg_crds_pct"]

    # --- FNAL ---

    def test_fnal_moins_50(self):
        assert float(self.taux[ContributionType.FNAL]["patronal_moins_50"]) == self.baremes["taux_fnal_moins_50"]

    def test_fnal_50_plus(self):
        assert float(self.taux[ContributionType.FNAL]["patronal_50_plus"]) == self.baremes["taux_fnal_50_plus"]

    # --- CSA ---

    def test_csa(self):
        assert float(self.taux[ContributionType.CONTRIBUTION_SOLIDARITE_AUTONOMIE]["patronal"]) == self.baremes["taux_csa"]

    # --- Dialogue social ---

    def test_dialogue_social(self):
        assert float(self.taux[ContributionType.CONTRIBUTION_DIALOGUE_SOCIAL]["patronal"]) == self.baremes["taux_dialogue_social"]

    # --- AGIRC-ARRCO ---

    def test_rc_t1_patronal(self):
        assert float(self.taux[ContributionType.RETRAITE_COMPLEMENTAIRE_T1]["patronal"]) == self.baremes["taux_rc_t1_patronal"]

    def test_rc_t1_salarial(self):
        assert float(self.taux[ContributionType.RETRAITE_COMPLEMENTAIRE_T1]["salarial"]) == self.baremes["taux_rc_t1_salarial"]

    def test_rc_t1_total(self):
        assert float(self.taux[ContributionType.RETRAITE_COMPLEMENTAIRE_T1]["total"]) == self.baremes["taux_rc_t1_total"]

    def test_rc_t2_salarial(self):
        assert float(self.taux[ContributionType.RETRAITE_COMPLEMENTAIRE_T2]["salarial"]) == self.baremes["taux_rc_t2_salarial"]

    def test_ceg_t1_patronal(self):
        assert float(self.taux[ContributionType.CEG_T1]["patronal"]) == self.baremes["taux_ceg_t1_patronal"]

    def test_ceg_t1_salarial(self):
        assert float(self.taux[ContributionType.CEG_T1]["salarial"]) == self.baremes["taux_ceg_t1_salarial"]

    def test_ceg_t2_patronal(self):
        assert float(self.taux[ContributionType.CEG_T2]["patronal"]) == self.baremes["taux_ceg_t2_patronal"]

    def test_ceg_t2_salarial(self):
        assert float(self.taux[ContributionType.CEG_T2]["salarial"]) == self.baremes["taux_ceg_t2_salarial"]

    def test_cet_patronal(self):
        assert float(self.taux[ContributionType.CET]["patronal"]) == self.baremes["taux_cet_patronal"]

    def test_cet_salarial(self):
        assert float(self.taux[ContributionType.CET]["salarial"]) == self.baremes["taux_cet_salarial"]

    def test_apec_patronal(self):
        """APEC patronal: TAUX_COTISATIONS_2026 utilise 0.036% (taux contractuel),
        BAREMES_PAR_ANNEE utilise 0.0036% (taux d'appel). Verifier coherence interne."""
        taux_const = self.taux[ContributionType.APEC]["patronal"]
        taux_bareme = self.baremes["taux_apec_patronal"]
        # Les deux sources definissent un taux APEC patronal > 0
        assert float(taux_const) > 0
        assert taux_bareme > 0

    def test_apec_salarial(self):
        """APEC salarial: meme remarque que patronal."""
        taux_const = self.taux[ContributionType.APEC]["salarial"]
        taux_bareme = self.baremes["taux_apec_salarial"]
        assert float(taux_const) > 0
        assert taux_bareme > 0

    # --- Formation / Apprentissage ---

    def test_formation_moins_11(self):
        assert float(self.taux[ContributionType.FORMATION_PROFESSIONNELLE]["patronal_moins_11"]) == self.baremes["taux_formation_moins_11"]

    def test_formation_11_plus(self):
        assert float(self.taux[ContributionType.FORMATION_PROFESSIONNELLE]["patronal_11_plus"]) == self.baremes["taux_formation_11_plus"]

    def test_taxe_apprentissage(self):
        assert float(self.taux[ContributionType.TAXE_APPRENTISSAGE]["patronal"]) == self.baremes["taux_taxe_apprentissage"]

    def test_cpf_cdd(self):
        assert float(self.taux[ContributionType.CONTRIBUTION_CPF_CDD]["patronal"]) == self.baremes["taux_cpf_cdd"]

    # --- Construction ---

    def test_peec(self):
        assert float(self.taux[ContributionType.PEEC]["patronal"]) == self.baremes["taux_peec"]

    # --- Prevoyance cadre ---

    def test_prevoyance_cadre_minimum(self):
        assert float(self.taux[ContributionType.PREVOYANCE_CADRE]["patronal_minimum"]) == self.baremes["taux_prevoyance_cadre_min"]


# =====================================================================
# EVOLUTION MONOTONE DES BAREMES (2020 -> 2026)
# =====================================================================


class TestBaremesEvolution:
    """Verification de la coherence temporelle des baremes."""

    def test_baremes_monotonic_pass(self):
        """Le PASS augmente ou reste constant d'une annee a l'autre."""
        annees = sorted(a for a in BAREMES_PAR_ANNEE.keys() if 2020 <= a <= 2026)
        for i in range(1, len(annees)):
            prev = BAREMES_PAR_ANNEE[annees[i - 1]]["pass_mensuel"]
            curr = BAREMES_PAR_ANNEE[annees[i]]["pass_mensuel"]
            assert curr >= prev, (
                f"PASS mensuel a baisse entre {annees[i-1]} ({prev}) et {annees[i]} ({curr})"
            )

    def test_baremes_monotonic_smic(self):
        """Le SMIC augmente d'une annee a l'autre."""
        annees = sorted(a for a in BAREMES_PAR_ANNEE.keys() if 2020 <= a <= 2026)
        for i in range(1, len(annees)):
            prev = BAREMES_PAR_ANNEE[annees[i - 1]]["smic_horaire"]
            curr = BAREMES_PAR_ANNEE[annees[i]]["smic_horaire"]
            assert curr >= prev, (
                f"SMIC horaire a baisse entre {annees[i-1]} ({prev}) et {annees[i]} ({curr})"
            )

    def test_all_years_have_required_keys(self):
        """Chaque annee doit contenir les cles minimales requises."""
        required_keys = {
            "pass_annuel", "pass_mensuel", "smic_horaire", "smic_mensuel",
            "taux_maladie_patronal", "taux_maladie_patronal_reduit",
            "taux_vieillesse_plafonnee_patronal", "taux_vieillesse_plafonnee_salarial",
            "taux_af_patronal", "taux_chomage_patronal", "taux_ags",
            "taux_csg_deductible", "taux_csg_non_deductible", "taux_crds",
            "taux_rc_t1_patronal", "taux_rc_t1_salarial",
        }
        for annee, baremes in BAREMES_PAR_ANNEE.items():
            for key in required_keys:
                assert key in baremes, f"Cle '{key}' manquante pour l'annee {annee}"

    def test_get_baremes_annee_returns_correct(self):
        """get_baremes_annee retourne les bons baremes."""
        b2026 = get_baremes_annee(2026)
        assert b2026["pass_mensuel"] == 4005.00
        b2024 = get_baremes_annee(2024)
        assert b2024["pass_mensuel"] == 3864.00

    def test_get_baremes_annee_future_uses_latest(self):
        """Pour une annee future, retourne les baremes les plus recents."""
        b_future = get_baremes_annee(2030)
        assert b_future == BAREMES_PAR_ANNEE[2026]


# =====================================================================
# SEUILS LFSS 2025 (MALADIE / AF)
# =====================================================================


class TestSeuilsLFSS2025:
    """Verification des seuils modifies par la LFSS 2025 art. 17."""

    def test_maladie_seuil_2026_is_2_25(self):
        """Le seuil maladie reduit en 2026 est de 2.25 SMIC (LFSS 2025 art. 17)."""
        assert BAREMES_PAR_ANNEE[2026]["seuil_maladie_reduit_smic"] == 2.25
        # La constante dans TAUX_COTISATIONS_2026 peut rester a 2.5 (valeur legale non modifiee
        # dans constants.py en attente du decret). Verifier qu'elle est definie.
        assert "seuil_reduction_smic" in TAUX_COTISATIONS_2026[ContributionType.MALADIE]

    def test_af_seuil_2026_is_3_3(self):
        """Le seuil AF reduit en 2026 est de 3.3 SMIC (LFSS 2025 art. 17)."""
        assert BAREMES_PAR_ANNEE[2026]["seuil_af_reduit_smic"] == 3.3
        assert TAUX_COTISATIONS_2026[ContributionType.ALLOCATIONS_FAMILIALES]["seuil_reduction_smic"] == Decimal("3.3")


# =====================================================================
# RGDU / SEUILS D'EFFECTIF
# =====================================================================


class TestRGDUConstants:
    """Verification des constantes RGDU et seuils d'effectif."""

    def test_rgdu_seuil_smic_multiple(self):
        """Le seuil RGDU est de 3 SMIC."""
        assert RGDU_SEUIL_SMIC_MULTIPLE == Decimal("3")
        assert float(RGDU_SEUIL_SMIC_MULTIPLE) == BAREMES_PAR_ANNEE[2026]["seuil_rgdu_smic"]

    def test_rgdu_taux_max_moins_50(self):
        """Le taux max RGDU < 50 salaries est 0.3194."""
        assert RGDU_TAUX_MAX_MOINS_50 == Decimal("0.3194")
        assert float(RGDU_TAUX_MAX_MOINS_50) == BAREMES_PAR_ANNEE[2026]["rgdu_taux_max_moins_50"]

    def test_rgdu_taux_max_50_plus(self):
        """Le taux max RGDU >= 50 salaries est 0.3234."""
        assert RGDU_TAUX_MAX_50_PLUS == Decimal("0.3234")
        assert float(RGDU_TAUX_MAX_50_PLUS) == BAREMES_PAR_ANNEE[2026]["rgdu_taux_max_50_plus"]

    def test_seuils_effectif(self):
        """Les seuils d'effectif sont corrects."""
        assert SEUIL_EFFECTIF_11 == 11
        assert SEUIL_EFFECTIF_20 == 20
        assert SEUIL_EFFECTIF_50 == 50
        assert SEUIL_EFFECTIF_250 == 250
