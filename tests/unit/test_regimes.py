"""Tests des regimes speciaux (guso_agessa, independant)."""

import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.regimes.guso_agessa import (
    RegimeSpecial,
    ConventionCollective,
    CONVENTIONS_COLLECTIVES,
    ParametresGUSO,
)
from urssaf_analyzer.regimes.independant import (
    TypeIndependant,
    ActiviteMicro,
    ProfilIndependant,
    SEUILS_MICRO_2026,
    TVA_FRANCHISE_SEUILS,
    FORMATION_MICRO,
    CotisationsTNS2026,
    TNS_2026,
    COTISATIONS_CIPAV_2026,
    calculer_cotisations_micro,
)


# =====================================================
# GUSO / AGESSA
# =====================================================

class TestRegimeSpecial:
    """Tests de l'enum RegimeSpecial."""

    def test_regime_general(self):
        assert RegimeSpecial.REGIME_GENERAL == "regime_general"

    def test_guso(self):
        assert RegimeSpecial.GUSO == "guso"

    def test_artistes_auteurs(self):
        assert RegimeSpecial.ARTISTES_AUTEURS == "artistes_auteurs"

    def test_all_values_are_strings(self):
        for r in RegimeSpecial:
            assert isinstance(r.value, str)


class TestConventionCollective:
    """Tests des conventions collectives."""

    def test_conventions_not_empty(self):
        assert len(CONVENTIONS_COLLECTIVES) > 0

    def test_convention_syntec(self):
        cc = CONVENTIONS_COLLECTIVES.get("1486")
        assert cc is not None
        assert "SYNTEC" in cc.titre

    def test_convention_hcr(self):
        cc = CONVENTIONS_COLLECTIVES.get("1979")
        assert cc is not None
        assert "HCR" in cc.titre or "Hotels" in cc.titre

    def test_convention_btp(self):
        cc = CONVENTIONS_COLLECTIVES.get("1596")
        assert cc is not None
        assert cc.taux_prevoyance == Decimal("0.015")

    def test_convention_dataclass_fields(self):
        cc = ConventionCollective(idcc="TEST", titre="Test CC")
        assert cc.idcc == "TEST"
        assert cc.brochure == ""
        assert cc.code_naf_principaux == []
        assert cc.specificites == []

    def test_convention_with_specificites(self):
        cc = CONVENTIONS_COLLECTIVES.get("1979")
        assert len(cc.specificites) > 0


class TestParametresGUSO:
    """Tests des parametres GUSO."""

    def test_default_taux(self):
        p = ParametresGUSO()
        assert p.maladie_patronal == Decimal("0.13")
        assert p.accident_travail == Decimal("0.0175")
        assert p.conges_spectacles == Decimal("0.155")

    def test_csg_crds(self):
        p = ParametresGUSO()
        assert p.csg_deductible == Decimal("0.068")
        assert p.csg_non_deductible == Decimal("0.024")
        assert p.crds == Decimal("0.005")
        assert p.abattement_csg == Decimal("0.9825")


# =====================================================
# INDEPENDANTS
# =====================================================

class TestTypeIndependant:
    """Tests de l'enum TypeIndependant."""

    def test_micro(self):
        assert TypeIndependant.MICRO_ENTREPRENEUR == "micro_entrepreneur"

    def test_gerant(self):
        assert TypeIndependant.GERANT_MAJORITAIRE == "gerant_majoritaire"

    def test_all_values(self):
        assert len(list(TypeIndependant)) >= 7


class TestActiviteMicro:
    """Tests de l'enum ActiviteMicro."""

    def test_vente(self):
        assert ActiviteMicro.VENTE_MARCHANDISES == "vente_marchandises"

    def test_bnc(self):
        assert ActiviteMicro.PRESTATIONS_BNC == "prestations_bnc"


class TestProfilIndependant:
    """Tests du dataclass ProfilIndependant."""

    def test_defaults(self):
        profil = ProfilIndependant(type_statut=TypeIndependant.MICRO_ENTREPRENEUR)
        assert profil.chiffre_affaires_annuel == Decimal("0")
        assert profil.tva_franchise is True
        assert profil.acre is False

    def test_custom(self):
        profil = ProfilIndependant(
            type_statut=TypeIndependant.MICRO_ENTREPRENEUR,
            activite="Conseil",
            siret="12345678901234",
            chiffre_affaires_annuel=Decimal("50000"),
        )
        assert profil.chiffre_affaires_annuel == Decimal("50000")


class TestSeuilsMicro:
    """Tests des seuils micro-entreprise 2026."""

    def test_seuils_vente(self):
        params = SEUILS_MICRO_2026[ActiviteMicro.VENTE_MARCHANDISES]
        assert params["ca_max"] == Decimal("188700")
        assert params["abattement_fiscal"] == Decimal("0.71")

    def test_seuils_bnc(self):
        params = SEUILS_MICRO_2026[ActiviteMicro.PRESTATIONS_BNC]
        assert params["ca_max"] == Decimal("77700")
        assert params["abattement_fiscal"] == Decimal("0.34")

    def test_tva_franchise_seuils(self):
        assert TVA_FRANCHISE_SEUILS["vente"] == Decimal("91900")
        assert TVA_FRANCHISE_SEUILS["services"] == Decimal("36800")

    def test_formation_micro(self):
        assert FORMATION_MICRO[ActiviteMicro.VENTE_MARCHANDISES] == Decimal("0.001")


class TestCotisationsTNS:
    """Tests des taux TNS."""

    def test_tns_defaults(self):
        tns = CotisationsTNS2026()
        assert tns.vieillesse_plafonnee == Decimal("0.1775")
        assert tns.csg_deductible == Decimal("0.068")

    def test_tns_global_instance(self):
        assert TNS_2026.maladie_taux_1 == Decimal("0.004")


class TestCIPAV:
    """Tests des cotisations CIPAV."""

    def test_cipav_not_empty(self):
        assert len(COTISATIONS_CIPAV_2026) > 0

    def test_cipav_retraite_base(self):
        assert "retraite_base_t1" in COTISATIONS_CIPAV_2026


class TestCalculerCotisationsMicro:
    """Tests du calcul cotisations micro-entrepreneur."""

    def test_calcul_vente_basic(self):
        result = calculer_cotisations_micro(
            Decimal("50000"),
            ActiviteMicro.VENTE_MARCHANDISES,
        )
        assert "erreur" not in result or result.get("erreur") is None

    def test_calcul_bnc(self):
        result = calculer_cotisations_micro(
            Decimal("30000"),
            ActiviteMicro.PRESTATIONS_BNC,
        )
        assert isinstance(result, dict)

    def test_calcul_avec_acre(self):
        result = calculer_cotisations_micro(
            Decimal("50000"),
            ActiviteMicro.VENTE_MARCHANDISES,
            acre=True,
        )
        assert isinstance(result, dict)

    def test_calcul_activite_invalide(self):
        result = calculer_cotisations_micro(
            Decimal("10000"),
            "invalid_type",
        )
        assert "erreur" in result
