"""Tests du module de veille juridique.

Couverture :
- legifrance_client: LegifranceClient, get_legislation_par_annee, ARTICLES_CSS_COTISATIONS
- urssaf_client: URSSAFOpenDataClient, get_baremes_annee, comparer_baremes, BAREMES_PAR_ANNEE
- veille_manager: VeilleManager (detection annees, veille pour annees)
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import date

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.veille.legifrance_client import (
    LegifranceClient,
    get_legislation_par_annee,
    ARTICLES_CSS_COTISATIONS,
    CODES_URSSAF,
    MOTS_CLES_VEILLE,
)
from urssaf_analyzer.veille.urssaf_client import (
    URSSAFOpenDataClient,
    get_baremes_annee,
    comparer_baremes,
    BAREMES_PAR_ANNEE,
    DATASETS,
)
from urssaf_analyzer.veille.veille_manager import VeilleManager


# ==============================
# Legifrance Client
# ==============================

class TestLegifranceClient:
    """Tests du client Legifrance."""

    def test_init_sandbox(self):
        client = LegifranceClient(sandbox=True)
        assert "sandbox" in client.token_url
        assert "sandbox" in client.api_base

    def test_init_production(self):
        client = LegifranceClient(sandbox=False)
        assert "sandbox" not in client.token_url
        assert "piste.gouv.fr" in client.api_base

    def test_get_token_sans_credentials(self):
        client = LegifranceClient(client_id="", client_secret="")
        token = client._get_token()
        assert token is None

    def test_get_token_cache(self):
        client = LegifranceClient()
        import time
        client._token = "cached_token"
        client._token_expiry = time.time() + 3600
        assert client._get_token() == "cached_token"

    def test_api_request_sans_token(self):
        client = LegifranceClient()
        result = client._api_request("search", {})
        assert result is None

    def test_rechercher_textes_sans_credentials(self):
        client = LegifranceClient()
        result = client.rechercher_textes("cotisations sociales")
        assert result == []

    def test_consulter_article_sans_credentials(self):
        client = LegifranceClient()
        result = client.consulter_article_css("LEGIARTI000006740102")
        assert result is None

    def test_lister_modifications_sans_credentials(self):
        client = LegifranceClient()
        result = client.lister_modifications_code()
        assert result == []

    def test_veille_mensuelle_sans_credentials(self):
        client = LegifranceClient()
        result = client.veille_mensuelle(2026, 1)
        assert result == []


class TestLegifranceConstantes:
    """Tests des constantes et donnees pre-chargees."""

    def test_codes_urssaf(self):
        assert len(CODES_URSSAF) == 3
        assert any("073189" in c for c in CODES_URSSAF)  # CSS

    def test_mots_cles_veille(self):
        assert len(MOTS_CLES_VEILLE) >= 10
        assert "URSSAF" in MOTS_CLES_VEILLE
        assert "DSN" in MOTS_CLES_VEILLE

    def test_articles_css_couvre_2020_a_2026(self):
        for annee in range(2020, 2027):
            assert annee in ARTICLES_CSS_COTISATIONS

    def test_articles_css_structure(self):
        for annee, data in ARTICLES_CSS_COTISATIONS.items():
            assert "description" in data
            assert "textes_cles" in data
            assert len(data["textes_cles"]) >= 1
            for texte in data["textes_cles"]:
                assert "reference" in texte
                assert "titre" in texte
                assert "resume" in texte

    def test_get_legislation_annee_connue(self):
        result = get_legislation_par_annee(2026)
        assert "RGDU" in result["description"]
        assert len(result["textes_cles"]) >= 3

    def test_get_legislation_annee_future(self):
        result = get_legislation_par_annee(2030)
        assert "description" in result

    def test_get_legislation_annee_ancienne(self):
        result = get_legislation_par_annee(2010)
        assert "description" in result


# ==============================
# URSSAF Open Data Client
# ==============================

class TestURSSAFOpenDataClient:
    """Tests du client URSSAF Open Data."""

    def test_init(self):
        client = URSSAFOpenDataClient()
        assert "open.urssaf.fr" in client.api_base

    def test_datasets_connus(self):
        assert "versement_mobilite" in DATASETS
        assert "exonerations" in DATASETS
        assert len(DATASETS) >= 5


class TestBaremesParAnnee:
    """Tests des baremes pre-charges."""

    def test_baremes_couvre_2020_a_2026(self):
        for annee in range(2020, 2027):
            assert annee in BAREMES_PAR_ANNEE

    def test_baremes_structure_complete(self):
        champs_requis = [
            "pass_annuel", "pass_mensuel", "smic_horaire", "smic_mensuel",
            "taux_maladie_patronal", "taux_maladie_patronal_reduit",
            "taux_vieillesse_plafonnee_patronal", "taux_af_patronal",
            "taux_csg_deductible", "taux_crds",
            "taux_fnal_moins_50", "taux_fnal_50_plus",
            "taux_chomage_patronal", "taux_ags",
            "taux_rc_t1_patronal", "taux_rc_t1_salarial",
            "taux_formation_moins_11", "taux_formation_11_plus",
            "taux_peec", "taux_prevoyance_cadre_min",
        ]
        for annee in range(2020, 2027):
            baremes = BAREMES_PAR_ANNEE[annee]
            for champ in champs_requis:
                assert champ in baremes, f"Champ {champ} manquant pour {annee}"

    def test_pass_croissant(self):
        """Le PASS doit etre croissant ou stable au fil des annees."""
        annees = sorted(BAREMES_PAR_ANNEE.keys())
        for i in range(1, len(annees)):
            assert (
                BAREMES_PAR_ANNEE[annees[i]]["pass_annuel"]
                >= BAREMES_PAR_ANNEE[annees[i - 1]]["pass_annuel"]
            )

    def test_smic_croissant(self):
        annees = sorted(BAREMES_PAR_ANNEE.keys())
        for i in range(1, len(annees)):
            assert (
                BAREMES_PAR_ANNEE[annees[i]]["smic_horaire"]
                >= BAREMES_PAR_ANNEE[annees[i - 1]]["smic_horaire"]
            )

    def test_taux_maladie_stable(self):
        for annee in range(2020, 2027):
            assert BAREMES_PAR_ANNEE[annee]["taux_maladie_patronal"] == 0.13

    def test_get_baremes_annee_connue(self):
        b = get_baremes_annee(2026)
        assert b["pass_annuel"] == 48060.00
        assert b["smic_horaire"] == 12.02

    def test_get_baremes_annee_future(self):
        b = get_baremes_annee(2030)
        assert "pass_annuel" in b

    def test_get_baremes_annee_ancienne(self):
        b = get_baremes_annee(2010)
        assert "pass_annuel" in b


class TestComparerBaremes:
    """Tests de la comparaison inter-annees."""

    def test_comparer_memes_annees(self):
        diffs = comparer_baremes(2024, 2024)
        assert diffs == []

    def test_comparer_annees_differentes(self):
        diffs = comparer_baremes(2024, 2025)
        assert len(diffs) > 0

    def test_comparer_structure(self):
        diffs = comparer_baremes(2024, 2025)
        for diff in diffs:
            assert "parametre" in diff
            assert "evolution" in diff
            assert f"valeur_2024" in diff
            assert f"valeur_2025" in diff

    def test_pass_evolution_2024_2025(self):
        diffs = comparer_baremes(2024, 2025)
        pass_diff = next((d for d in diffs if d["parametre"] == "pass_annuel"), None)
        assert pass_diff is not None
        assert "hausse" in pass_diff["evolution"]

    def test_comparer_2025_2026_nouveaux_champs(self):
        diffs = comparer_baremes(2025, 2026)
        params = [d["parametre"] for d in diffs]
        # 2026 a des champs nouveaux
        assert any("nouveau" in d["evolution"] for d in diffs)


# ==============================
# Veille Manager
# ==============================

class TestVeilleManager:
    """Tests du gestionnaire de veille."""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.execute.return_value = []
        return db

    @pytest.fixture
    def manager(self, mock_db):
        return VeilleManager(db=mock_db)

    def test_init(self, manager):
        assert manager.legifrance is not None
        assert manager.urssaf is not None

    def test_detecter_annees_documents(self, manager):
        textes = [
            "DSN de janvier 2024",
            "Bordereau URSSAF 2025 - Cotisations",
            "Pas d'annee ici",
        ]
        annees = manager.detecter_annees_documents(textes)
        assert 2024 in annees
        assert 2025 in annees
        assert len(annees) == 2

    def test_detecter_annees_hors_plage(self, manager):
        textes = ["Document de 2010 et 2040"]
        annees = manager.detecter_annees_documents(textes)
        assert 2040 not in annees

    def test_detecter_annees_vide(self, manager):
        annees = manager.detecter_annees_documents([])
        assert annees == set()

    def test_detecter_annees_sans_annee(self, manager):
        annees = manager.detecter_annees_documents(["texte sans nombre"])
        assert annees == set()

    def test_detecter_annees_multiples_dans_meme_doc(self, manager):
        textes = ["Comparaison 2023 vs 2024 vs 2025"]
        annees = manager.detecter_annees_documents(textes)
        assert {2023, 2024, 2025} == annees

    def test_get_veille_pour_annees(self, manager):
        veille = manager.get_veille_pour_annees({2025, 2026})
        assert veille["annees_detectees"] == [2025, 2026]
        assert 2025 in veille["legislation_applicable"]
        assert 2026 in veille["legislation_applicable"]
        assert 2025 in veille["baremes"]
        assert 2026 in veille["baremes"]
        assert len(veille["evolutions"]) >= 1

    def test_get_veille_annee_unique(self, manager):
        veille = manager.get_veille_pour_annees({2026})
        assert veille["annees_detectees"] == [2026]
        assert veille["evolutions"] == []

    def test_get_veille_genere_alertes(self, manager):
        veille = manager.get_veille_pour_annees({2024, 2025})
        # Il y a des differences entre 2024 et 2025 (PASS, SMIC)
        assert len(veille["alertes"]) > 0

    def test_executer_veille_mensuelle(self, manager):
        result = manager.executer_veille_mensuelle(2026, 3)
        assert result["periode"] == "03/2026"
        assert "baremes_urssaf" in result
        assert "alertes" in result
        assert len(result["alertes"]) > 0

    def test_get_alertes_recentes(self, manager, mock_db):
        manager.get_alertes_recentes(limit=10)
        mock_db.execute.assert_called()

    def test_get_textes_veille_avec_annee(self, manager, mock_db):
        manager.get_textes_veille(annee=2026, limit=10)
        mock_db.execute.assert_called()

    def test_marquer_alerte_lue(self, manager, mock_db):
        manager.marquer_alerte_lue(42)
        mock_db.execute.assert_called_with(
            "UPDATE veille_alertes SET lue = 1 WHERE id = ?", (42,)
        )

    def test_marquer_alerte_traitee(self, manager, mock_db):
        manager.marquer_alerte_traitee(42)
        call_args = mock_db.execute.call_args
        assert "traitee = 1" in call_args[0][0]
