"""Tests de synchronisation TAUX_COTISATIONS_2026 vs BAREMES_PAR_ANNEE[2026].

Verifie que les taux definis dans les constantes (config/constants.py)
sont coherents avec les baremes de la veille URSSAF (veille/urssaf_client.py).
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from decimal import Decimal

from urssaf_analyzer.config.constants import (
    TAUX_COTISATIONS_2026, ContributionType,
    PASS_MENSUEL, PASS_ANNUEL, SMIC_MENSUEL_BRUT, SMIC_HORAIRE_BRUT,
)
from urssaf_analyzer.veille.urssaf_client import BAREMES_PAR_ANNEE


class TestBaremesSync:
    """Verification de la coherence entre TAUX_COTISATIONS_2026 et BAREMES_PAR_ANNEE[2026]."""

    def test_annee_2026_presente(self):
        """BAREMES_PAR_ANNEE doit contenir l'annee 2026."""
        assert 2026 in BAREMES_PAR_ANNEE

    def test_pass_mensuel_coherent(self):
        """Le PASS mensuel doit etre coherent entre les deux sources."""
        baremes = BAREMES_PAR_ANNEE[2026]
        assert float(PASS_MENSUEL) == baremes["pass_mensuel"]

    def test_pass_annuel_coherent(self):
        """Le PASS annuel doit etre coherent entre les deux sources."""
        baremes = BAREMES_PAR_ANNEE[2026]
        assert float(PASS_ANNUEL) == baremes["pass_annuel"]

    def test_smic_horaire_coherent(self):
        """Le SMIC horaire doit etre coherent entre les deux sources."""
        baremes = BAREMES_PAR_ANNEE[2026]
        assert float(SMIC_HORAIRE_BRUT) == baremes["smic_horaire"]

    def test_smic_mensuel_coherent(self):
        """Le SMIC mensuel doit etre coherent entre les deux sources."""
        baremes = BAREMES_PAR_ANNEE[2026]
        assert float(SMIC_MENSUEL_BRUT) == baremes["smic_mensuel"]

    def test_taux_maladie_patronal(self):
        """Le taux maladie patronal doit etre coherent."""
        baremes = BAREMES_PAR_ANNEE[2026]
        taux = TAUX_COTISATIONS_2026[ContributionType.MALADIE]
        assert float(taux["patronal"]) == baremes["taux_maladie_patronal"]

    def test_taux_maladie_patronal_reduit(self):
        """Le taux maladie patronal reduit doit etre coherent."""
        baremes = BAREMES_PAR_ANNEE[2026]
        taux = TAUX_COTISATIONS_2026[ContributionType.MALADIE]
        assert float(taux["patronal_reduit"]) == baremes["taux_maladie_patronal_reduit"]

    def test_taux_vieillesse_plafonnee(self):
        """Les taux vieillesse plafonnee doivent etre coherents."""
        baremes = BAREMES_PAR_ANNEE[2026]
        taux = TAUX_COTISATIONS_2026[ContributionType.VIEILLESSE_PLAFONNEE]
        assert float(taux["patronal"]) == baremes["taux_vieillesse_plafonnee_patronal"]
        assert float(taux["salarial"]) == baremes["taux_vieillesse_plafonnee_salarial"]

    def test_taux_vieillesse_deplafonnee_present(self):
        """Les taux vieillesse deplafonnee doivent etre definis dans les deux sources."""
        baremes = BAREMES_PAR_ANNEE[2026]
        taux = TAUX_COTISATIONS_2026[ContributionType.VIEILLESSE_DEPLAFONNEE]
        assert "patronal" in taux
        assert "taux_vieillesse_deplafonnee_patronal" in baremes

    def test_taux_af_patronal(self):
        """Le taux allocations familiales patronal doit etre coherent."""
        baremes = BAREMES_PAR_ANNEE[2026]
        taux = TAUX_COTISATIONS_2026[ContributionType.ALLOCATIONS_FAMILIALES]
        assert float(taux["patronal"]) == baremes["taux_af_patronal"]

    def test_taux_csg_deductible(self):
        """Le taux CSG deductible doit etre coherent."""
        baremes = BAREMES_PAR_ANNEE[2026]
        taux = TAUX_COTISATIONS_2026[ContributionType.CSG_DEDUCTIBLE]
        assert float(taux["taux"]) == baremes["taux_csg_deductible"]

    def test_taux_chomage_patronal(self):
        """Le taux chomage patronal doit etre coherent."""
        baremes = BAREMES_PAR_ANNEE[2026]
        taux = TAUX_COTISATIONS_2026[ContributionType.ASSURANCE_CHOMAGE]
        assert float(taux["patronal"]) == baremes["taux_chomage_patronal"]

    def test_taux_ags(self):
        """Le taux AGS doit etre coherent."""
        baremes = BAREMES_PAR_ANNEE[2026]
        taux = TAUX_COTISATIONS_2026[ContributionType.AGS]
        assert float(taux["patronal"]) == baremes["taux_ags"]

    def test_taux_retraite_complementaire_t1(self):
        """Les taux retraite complementaire T1 doivent etre coherents."""
        baremes = BAREMES_PAR_ANNEE[2026]
        taux = TAUX_COTISATIONS_2026[ContributionType.RETRAITE_COMPLEMENTAIRE_T1]
        assert float(taux["patronal"]) == baremes["taux_rc_t1_patronal"]
        assert float(taux["salarial"]) == baremes["taux_rc_t1_salarial"]

    def test_baremes_annees_presentes(self):
        """Les annees principales (2020-2026) doivent etre presentes."""
        for annee in range(2020, 2027):
            assert annee in BAREMES_PAR_ANNEE, f"Annee {annee} manquante dans BAREMES_PAR_ANNEE"

    def test_baremes_contiennent_champs_essentiels(self):
        """Chaque annee doit contenir les champs essentiels."""
        champs_essentiels = [
            "pass_annuel", "pass_mensuel", "smic_horaire", "smic_mensuel",
            "taux_maladie_patronal", "taux_vieillesse_plafonnee_patronal",
        ]
        for annee, baremes in BAREMES_PAR_ANNEE.items():
            for champ in champs_essentiels:
                assert champ in baremes, f"Champ '{champ}' manquant pour {annee}"
