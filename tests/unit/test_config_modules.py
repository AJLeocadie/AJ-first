"""Tests des modules de configuration (idcc_database, taux_atmp, settings)."""

import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.config.idcc_database import (
    IDCC_DATABASE,
    rechercher_idcc,
    get_ccn_par_idcc,
    get_prevoyance_par_idcc,
)
from urssaf_analyzer.config.taux_atmp import (
    TAUX_ATMP_PAR_NAF,
    TAUX_ATMP_MOYEN,
    MAJORATION_TRAJET,
    MAJORATION_CHARGES,
    MAJORATION_PENIBILITE,
    MAJORATION_ECAP,
    get_taux_atmp,
)
from urssaf_analyzer.config.settings import (
    AppConfig,
    SecurityConfig,
    AnalysisConfig,
    ReportConfig,
)


# =====================================================
# IDCC DATABASE
# =====================================================

class TestIDCCDatabase:
    """Tests de la base IDCC."""

    def test_database_not_empty(self):
        assert len(IDCC_DATABASE) > 0

    def test_database_entries_have_required_fields(self):
        for idcc, data in IDCC_DATABASE.items():
            assert "nom" in data, f"IDCC {idcc} missing 'nom'"
            assert "secteur" in data, f"IDCC {idcc} missing 'secteur'"
            assert "prevoyance_cadre" in data
            assert "prevoyance_non_cadre" in data
            assert "mutuelle_employeur_min_pct" in data

    def test_database_decimal_values(self):
        for idcc, data in IDCC_DATABASE.items():
            assert isinstance(data["prevoyance_cadre"], Decimal)
            assert isinstance(data["prevoyance_non_cadre"], Decimal)

    def test_rechercher_idcc_par_numero(self):
        results = rechercher_idcc("1486")
        assert len(results) > 0
        assert results[0]["idcc"] == "1486"
        assert results[0]["score"] == 100

    def test_rechercher_idcc_par_nom(self):
        results = rechercher_idcc("batiment")
        assert len(results) > 0
        for r in results:
            assert "batiment" in r["nom"].lower() or "batiment" in r.get("secteur", "").lower()

    def test_rechercher_idcc_par_secteur(self):
        results = rechercher_idcc("restauration")
        assert len(results) > 0

    def test_rechercher_idcc_no_result(self):
        results = rechercher_idcc("xyznonexistent")
        assert results == []

    def test_rechercher_idcc_max_20(self):
        results = rechercher_idcc("a")
        assert len(results) <= 20

    def test_get_ccn_par_idcc_existant(self):
        ccn = get_ccn_par_idcc("1486")
        assert ccn is not None
        assert "SYNTEC" in ccn["nom"] or "Bureaux" in ccn["nom"]

    def test_get_ccn_par_idcc_padding(self):
        ccn = get_ccn_par_idcc("16")
        assert ccn is not None or get_ccn_par_idcc("0016") is not None

    def test_get_ccn_par_idcc_inexistant(self):
        ccn = get_ccn_par_idcc("9999")
        assert ccn is None

    def test_get_prevoyance_cadre(self):
        result = get_prevoyance_par_idcc("1486", est_cadre=True)
        assert result["ccn_connue"] is True
        assert result["taux_prevoyance"] == float(Decimal("0.015"))
        assert result["est_cadre"] is True

    def test_get_prevoyance_non_cadre(self):
        result = get_prevoyance_par_idcc("1486", est_cadre=False)
        assert result["ccn_connue"] is True
        assert result["taux_prevoyance"] == float(Decimal("0.006"))

    def test_get_prevoyance_idcc_inconnu(self):
        result = get_prevoyance_par_idcc("9999", est_cadre=True)
        assert result["ccn_connue"] is False
        assert "note" in result

    def test_get_prevoyance_idcc_inconnu_non_cadre(self):
        result = get_prevoyance_par_idcc("9999", est_cadre=False)
        assert result["ccn_connue"] is False
        assert result["taux_prevoyance"] == 0.0


# =====================================================
# TAUX AT/MP
# =====================================================

class TestTauxATMP:
    """Tests de la table des taux AT/MP."""

    def test_table_not_empty(self):
        assert len(TAUX_ATMP_PAR_NAF) > 0

    def test_all_values_are_decimal(self):
        for code, taux in TAUX_ATMP_PAR_NAF.items():
            assert isinstance(taux, Decimal), f"Code {code}: taux not Decimal"

    def test_taux_moyen(self):
        assert TAUX_ATMP_MOYEN == Decimal("0.0208")

    def test_majorations(self):
        assert isinstance(MAJORATION_TRAJET, Decimal)
        assert isinstance(MAJORATION_CHARGES, Decimal)
        assert isinstance(MAJORATION_PENIBILITE, Decimal)
        assert isinstance(MAJORATION_ECAP, Decimal)

    def test_get_taux_informatique(self):
        result = get_taux_atmp("62.02A", effectif=10)
        assert result["code_naf"] == "62.02A"
        assert result["taux"] > 0
        assert result["mode_tarification"] == "collectif"

    def test_get_taux_construction(self):
        result = get_taux_atmp("41.20B", effectif=5)
        assert result["taux"] > 0

    def test_get_taux_collectif_small(self):
        result = get_taux_atmp("62", effectif=10)
        assert result["mode_tarification"] == "collectif"
        assert "< 20" in result["note"]

    def test_get_taux_mixte(self):
        result = get_taux_atmp("62", effectif=50)
        assert result["mode_tarification"] == "mixte"

    def test_get_taux_individuel(self):
        result = get_taux_atmp("62", effectif=200)
        assert result["mode_tarification"] == "individuel"

    def test_get_taux_unknown_naf(self):
        result = get_taux_atmp("ZZ.ZZZ", effectif=10)
        assert result["taux"] == float(TAUX_ATMP_MOYEN)

    def test_get_taux_has_majorations(self):
        result = get_taux_atmp("62", effectif=10)
        assert "majorations_incluses" in result
        assert "trajet_M1" in result["majorations_incluses"]

    def test_get_taux_precision_naf(self):
        # Test with sub-code like 43.1
        result = get_taux_atmp("43.10A", effectif=5)
        assert result["taux"] > 0

    def test_get_taux_naf_2digits(self):
        result = get_taux_atmp("47", effectif=10)
        assert result["taux"] == float(TAUX_ATMP_PAR_NAF.get("47", TAUX_ATMP_MOYEN))

    def test_taux_collectif_pct_format(self):
        result = get_taux_atmp("62", effectif=10)
        assert "%" in result["taux_collectif_pct"]


# =====================================================
# SETTINGS
# =====================================================

class TestSettings:
    """Tests de la configuration de l'application."""

    def test_security_config_defaults(self):
        config = SecurityConfig()
        assert config.encryption_algorithm == "AES-256-GCM"
        assert config.key_derivation == "pbkdf2"
        assert config.pbkdf2_iterations == 310_000
        assert config.salt_length == 32
        assert config.iv_length == 12
        assert config.secure_delete_passes == 3

    def test_analysis_config_defaults(self):
        config = AnalysisConfig()
        assert config.annee_reference == 2026
        assert config.tolerance_montant == 0.01
        assert config.max_file_size_mb == 100

    def test_report_config_defaults(self):
        config = ReportConfig()
        assert config.format_defaut == "html"
        assert config.inclure_graphiques is True
        assert config.langue == "fr"

    def test_app_config_creates_dirs(self, tmp_path):
        config = AppConfig(base_dir=tmp_path)
        assert config.data_dir.exists()
        assert config.encrypted_dir.exists()
        assert config.temp_dir.exists()
        assert config.reports_dir.exists()

    def test_app_config_default_paths(self, tmp_path):
        config = AppConfig(base_dir=tmp_path)
        assert config.data_dir == tmp_path / "data"
        assert config.encrypted_dir == tmp_path / "data" / "encrypted"
        assert config.temp_dir == tmp_path / "data" / "temp"
        assert config.reports_dir == tmp_path / "data" / "reports"
        assert config.audit_log_path == tmp_path / "data" / "audit.log"

    def test_app_config_custom_paths(self, tmp_path):
        custom_data = tmp_path / "custom_data"
        custom_data.mkdir()
        config = AppConfig(base_dir=tmp_path, data_dir=custom_data)
        assert config.data_dir == custom_data

    def test_app_config_nested_configs(self, tmp_path):
        config = AppConfig(base_dir=tmp_path)
        assert isinstance(config.security, SecurityConfig)
        assert isinstance(config.analysis, AnalysisConfig)
        assert isinstance(config.report, ReportConfig)

    def test_security_config_custom(self):
        config = SecurityConfig(pbkdf2_iterations=200_000)
        assert config.pbkdf2_iterations == 200_000
