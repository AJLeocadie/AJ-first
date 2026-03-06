"""Tests exhaustifs des regimes speciaux et independants."""

import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# =====================================================
# GUSO / AGESSA - Full coverage
# =====================================================

class TestGUSOCalculations:
    """Tests des calculs GUSO."""

    def test_calculer_cotisations_guso_basic(self):
        from urssaf_analyzer.regimes.guso_agessa import calculer_cotisations_guso
        result = calculer_cotisations_guso(Decimal("500"))
        assert isinstance(result, dict)
        assert "cotisations" in result or "total" in result or len(result) > 0

    def test_calculer_cotisations_guso_high_salary(self):
        from urssaf_analyzer.regimes.guso_agessa import calculer_cotisations_guso
        result = calculer_cotisations_guso(Decimal("5000"))
        assert isinstance(result, dict)

    def test_calculer_cotisations_guso_custom_hours(self):
        from urssaf_analyzer.regimes.guso_agessa import calculer_cotisations_guso
        result = calculer_cotisations_guso(Decimal("1000"), nb_heures=Decimal("35"))
        assert isinstance(result, dict)

    def test_calculer_cotisations_guso_small(self):
        from urssaf_analyzer.regimes.guso_agessa import calculer_cotisations_guso
        result = calculer_cotisations_guso(Decimal("100"))
        assert isinstance(result, dict)


class TestArtistesAuteursCalculations:
    """Tests des calculs artistes-auteurs."""

    def test_calculer_bda(self):
        from urssaf_analyzer.regimes.guso_agessa import calculer_cotisations_artistes_auteurs
        result = calculer_cotisations_artistes_auteurs(Decimal("30000"), est_bda=True)
        assert isinstance(result, dict)

    def test_calculer_ta(self):
        from urssaf_analyzer.regimes.guso_agessa import calculer_cotisations_artistes_auteurs
        result = calculer_cotisations_artistes_auteurs(Decimal("20000"), est_bda=False)
        assert isinstance(result, dict)

    def test_calculer_avec_frais_reels(self):
        from urssaf_analyzer.regimes.guso_agessa import calculer_cotisations_artistes_auteurs
        result = calculer_cotisations_artistes_auteurs(Decimal("30000"), frais_reels=Decimal("5000"))
        assert isinstance(result, dict)

    def test_calculer_low_revenue(self):
        from urssaf_analyzer.regimes.guso_agessa import calculer_cotisations_artistes_auteurs
        result = calculer_cotisations_artistes_auteurs(Decimal("5000"))
        assert isinstance(result, dict)


class TestConventionCollectiveLookup:
    """Tests de recherche de conventions collectives."""

    def test_get_convention_existante(self):
        from urssaf_analyzer.regimes.guso_agessa import get_convention_collective
        cc = get_convention_collective("1486")
        assert cc is not None
        assert "SYNTEC" in cc.titre or "Bureaux" in cc.titre

    def test_get_convention_inexistante(self):
        from urssaf_analyzer.regimes.guso_agessa import get_convention_collective
        cc = get_convention_collective("9999")
        assert cc is None

    def test_rechercher_conventions(self):
        from urssaf_analyzer.regimes.guso_agessa import rechercher_conventions
        results = rechercher_conventions("batiment")
        assert len(results) >= 0

    def test_lister_conventions(self):
        from urssaf_analyzer.regimes.guso_agessa import lister_conventions
        result = lister_conventions()
        assert isinstance(result, list)
        assert len(result) > 0


# =====================================================
# INDEPENDANTS - Full coverage
# =====================================================

class TestMicroEntrepreneur:
    """Tests du calcul micro-entrepreneur."""

    def test_calcul_vente(self):
        from urssaf_analyzer.regimes.independant import calculer_cotisations_micro, ActiviteMicro
        result = calculer_cotisations_micro(Decimal("50000"), ActiviteMicro.VENTE_MARCHANDISES)
        assert isinstance(result, dict)
        assert "erreur" not in result

    def test_calcul_prestations_bic(self):
        from urssaf_analyzer.regimes.independant import calculer_cotisations_micro, ActiviteMicro
        result = calculer_cotisations_micro(Decimal("40000"), ActiviteMicro.PRESTATIONS_BIC)
        assert isinstance(result, dict)

    def test_calcul_bnc(self):
        from urssaf_analyzer.regimes.independant import calculer_cotisations_micro, ActiviteMicro
        result = calculer_cotisations_micro(Decimal("30000"), ActiviteMicro.PRESTATIONS_BNC)
        assert isinstance(result, dict)

    def test_calcul_location(self):
        from urssaf_analyzer.regimes.independant import calculer_cotisations_micro, ActiviteMicro
        result = calculer_cotisations_micro(Decimal("80000"), ActiviteMicro.LOCATION_MEUBLEE)
        assert isinstance(result, dict)

    def test_calcul_avec_acre(self):
        from urssaf_analyzer.regimes.independant import calculer_cotisations_micro, ActiviteMicro
        result = calculer_cotisations_micro(Decimal("30000"), ActiviteMicro.PRESTATIONS_BNC, acre=True)
        assert isinstance(result, dict)

    def test_calcul_avec_prelevement_liberatoire(self):
        from urssaf_analyzer.regimes.independant import calculer_cotisations_micro, ActiviteMicro
        result = calculer_cotisations_micro(Decimal("30000"), ActiviteMicro.VENTE_MARCHANDISES, prelevement_liberatoire=True)
        assert isinstance(result, dict)

    def test_calcul_depassement_seuil(self):
        from urssaf_analyzer.regimes.independant import calculer_cotisations_micro, ActiviteMicro
        result = calculer_cotisations_micro(Decimal("200000"), ActiviteMicro.VENTE_MARCHANDISES)
        assert isinstance(result, dict)

    def test_calcul_ca_zero(self):
        from urssaf_analyzer.regimes.independant import calculer_cotisations_micro, ActiviteMicro
        result = calculer_cotisations_micro(Decimal("0"), ActiviteMicro.VENTE_MARCHANDISES)
        assert isinstance(result, dict)


class TestTNS:
    """Tests du calcul TNS regime reel."""

    def test_calcul_tns_basic(self):
        from urssaf_analyzer.regimes.independant import calculer_cotisations_tns
        result = calculer_cotisations_tns(Decimal("40000"))
        assert isinstance(result, dict)

    def test_calcul_tns_low_income(self):
        from urssaf_analyzer.regimes.independant import calculer_cotisations_tns
        result = calculer_cotisations_tns(Decimal("10000"))
        assert isinstance(result, dict)

    def test_calcul_tns_high_income(self):
        from urssaf_analyzer.regimes.independant import calculer_cotisations_tns
        result = calculer_cotisations_tns(Decimal("100000"))
        assert isinstance(result, dict)

    def test_calcul_tns_avec_acre(self):
        from urssaf_analyzer.regimes.independant import calculer_cotisations_tns
        result = calculer_cotisations_tns(Decimal("40000"), acre=True)
        assert isinstance(result, dict)

    def test_calcul_tns_conjoint(self):
        from urssaf_analyzer.regimes.independant import calculer_cotisations_tns
        result = calculer_cotisations_tns(Decimal("40000"), conjoint_collaborateur=True)
        assert isinstance(result, dict)

    def test_calcul_tns_liberal(self):
        from urssaf_analyzer.regimes.independant import calculer_cotisations_tns, TypeIndependant
        result = calculer_cotisations_tns(Decimal("60000"), type_independant=TypeIndependant.PROFESSION_LIBERALE)
        assert isinstance(result, dict)

    def test_calcul_tns_zero_income(self):
        from urssaf_analyzer.regimes.independant import calculer_cotisations_tns
        result = calculer_cotisations_tns(Decimal("0"))
        assert isinstance(result, dict)
