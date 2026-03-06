"""Tests du gestionnaire de portefeuille."""

import sys
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.portfolio.portfolio_manager import PortfolioManager


class FakeDB:
    """Fake database for portfolio manager tests."""

    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE profils (
                id TEXT PRIMARY KEY,
                nom TEXT,
                prenom TEXT,
                email TEXT UNIQUE,
                role TEXT DEFAULT 'analyste',
                mot_de_passe_hash TEXT,
                date_creation TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                derniere_connexion TIMESTAMP,
                actif INTEGER DEFAULT 1
            );
            CREATE TABLE entreprises (
                id TEXT PRIMARY KEY,
                siret TEXT,
                siren TEXT,
                raison_sociale TEXT,
                nom_commercial TEXT DEFAULT '',
                forme_juridique TEXT DEFAULT '',
                forme_juridique_code TEXT DEFAULT '',
                code_naf TEXT DEFAULT '',
                activite_principale TEXT DEFAULT '',
                effectif INTEGER DEFAULT 0,
                tranche_effectif TEXT DEFAULT '',
                capital_social REAL DEFAULT 0,
                taux_at REAL DEFAULT 0.0208,
                taux_versement_mobilite REAL DEFAULT 0,
                convention_collective TEXT DEFAULT '',
                convention_collective_idcc TEXT DEFAULT '',
                convention_collective_titre TEXT DEFAULT '',
                adresse TEXT DEFAULT '',
                code_postal TEXT DEFAULT '',
                ville TEXT DEFAULT '',
                pays TEXT DEFAULT 'France',
                objet_social TEXT DEFAULT '',
                date_immatriculation TEXT DEFAULT '',
                date_cloture_exercice TEXT DEFAULT '',
                regime_tva TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                actif INTEGER DEFAULT 1,
                date_creation TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE portefeuille (
                profil_id TEXT,
                entreprise_id TEXT,
                role_sur_entreprise TEXT DEFAULT 'gestionnaire',
                date_ajout TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(profil_id, entreprise_id)
            );
            CREATE TABLE analyses (
                id TEXT PRIMARY KEY,
                entreprise_id TEXT,
                profil_id TEXT,
                nb_documents INTEGER DEFAULT 0,
                nb_findings INTEGER DEFAULT 0,
                score_risque INTEGER DEFAULT 0,
                impact_financier REAL DEFAULT 0,
                chemin_rapport TEXT DEFAULT '',
                format_rapport TEXT DEFAULT 'html',
                duree_secondes REAL DEFAULT 0,
                resume TEXT DEFAULT '',
                date_analyse TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

    def execute(self, sql, params=None):
        cursor = self.conn.cursor()
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)
        self.conn.commit()
        return cursor.fetchall()


@pytest.fixture
def pm():
    db = FakeDB()
    return PortfolioManager(db)


class TestPortfolioManagerProfils:
    """Tests de gestion des profils."""

    def test_creer_profil(self, pm):
        profil = pm.creer_profil("Dupont", "Jean", "jean@test.com", "Password123!")
        assert profil is not None
        assert profil["nom"] == "Dupont"
        assert profil["prenom"] == "Jean"
        assert profil["email"] == "jean@test.com"
        assert profil["role"] == "analyste"

    def test_authentifier_valid(self, pm):
        pm.creer_profil("Dupont", "Jean", "jean@test.com", "Password123!")
        profil = pm.authentifier("jean@test.com", "Password123!")
        assert profil is not None
        assert profil["email"] == "jean@test.com"
        assert "mot_de_passe_hash" not in profil

    def test_authentifier_wrong_password(self, pm):
        pm.creer_profil("Dupont", "Jean", "jean@test.com", "Password123!")
        result = pm.authentifier("jean@test.com", "WrongPassword!")
        assert result is None

    def test_authentifier_unknown_email(self, pm):
        result = pm.authentifier("unknown@test.com", "Password123!")
        assert result is None

    def test_get_profil(self, pm):
        profil = pm.creer_profil("Dupont", "Jean", "jean@test.com", "Password123!")
        retrieved = pm.get_profil(profil["id"])
        assert retrieved is not None
        assert retrieved["email"] == "jean@test.com"

    def test_get_profil_inexistant(self, pm):
        result = pm.get_profil("nonexistent-id")
        assert result is None

    def test_lister_profils(self, pm):
        pm.creer_profil("A", "B", "a@test.com", "Password123!")
        pm.creer_profil("C", "D", "c@test.com", "Password123!")
        profils = pm.lister_profils()
        assert len(profils) == 2

    def test_hash_password(self):
        h = PortfolioManager._hash_password("test")
        assert ":" in h
        parts = h.split(":")
        assert len(parts) == 2

    def test_verify_password(self):
        h = PortfolioManager._hash_password("test123")
        assert PortfolioManager._verify_password("test123", h) is True
        assert PortfolioManager._verify_password("wrong", h) is False

    def test_verify_password_invalid_format(self):
        assert PortfolioManager._verify_password("test", "invalid_hash") is False


class TestPortfolioManagerEntreprises:
    """Tests de gestion des entreprises."""

    def test_ajouter_entreprise(self, pm):
        ent = pm.ajouter_entreprise("12345678901234", "Acme Corp")
        assert ent is not None
        assert ent["siret"] == "12345678901234"
        assert ent["raison_sociale"] == "Acme Corp"

    def test_ajouter_entreprise_with_details(self, pm):
        ent = pm.ajouter_entreprise(
            "12345678901234", "Acme Corp",
            forme_juridique="SAS",
            code_naf="6201Z",
            effectif=50,
        )
        assert ent["forme_juridique"] == "SAS"
        assert ent["code_naf"] == "6201Z"

    def test_get_entreprise(self, pm):
        ent = pm.ajouter_entreprise("12345678901234", "Acme Corp")
        retrieved = pm.get_entreprise(ent["id"])
        assert retrieved is not None

    def test_get_entreprise_par_siret(self, pm):
        pm.ajouter_entreprise("12345678901234", "Acme Corp")
        ent = pm.get_entreprise_par_siret("12345678901234")
        assert ent is not None
        assert ent["raison_sociale"] == "Acme Corp"

    def test_modifier_entreprise(self, pm):
        ent = pm.ajouter_entreprise("12345678901234", "Acme Corp")
        updated = pm.modifier_entreprise(ent["id"], raison_sociale="Acme Inc")
        assert updated["raison_sociale"] == "Acme Inc"

    def test_modifier_entreprise_no_updates(self, pm):
        ent = pm.ajouter_entreprise("12345678901234", "Acme Corp")
        updated = pm.modifier_entreprise(ent["id"], invalid_field="ignored")
        assert updated["raison_sociale"] == "Acme Corp"

    def test_supprimer_entreprise(self, pm):
        ent = pm.ajouter_entreprise("12345678901234", "Acme Corp")
        pm.supprimer_entreprise(ent["id"])
        result = pm.lister_entreprises(actif_seulement=True)
        assert len(result) == 0

    def test_lister_entreprises(self, pm):
        pm.ajouter_entreprise("11111111111111", "Corp A")
        pm.ajouter_entreprise("22222222222222", "Corp B")
        result = pm.lister_entreprises()
        assert len(result) == 2

    def test_lister_entreprises_inclure_inactives(self, pm):
        ent = pm.ajouter_entreprise("11111111111111", "Corp A")
        pm.supprimer_entreprise(ent["id"])
        result = pm.lister_entreprises(actif_seulement=False)
        assert len(result) == 1

    def test_rechercher_entreprises(self, pm):
        pm.ajouter_entreprise("11111111111111", "Acme Corp")
        pm.ajouter_entreprise("22222222222222", "Beta Inc")
        results = pm.rechercher_entreprises("Acme")
        assert len(results) == 1
        assert results[0]["raison_sociale"] == "Acme Corp"


class TestPortfolioManagerPortefeuille:
    """Tests du portefeuille."""

    def test_assigner_et_get(self, pm):
        profil = pm.creer_profil("A", "B", "a@test.com", "Password123!")
        ent = pm.ajouter_entreprise("12345678901234", "Corp")
        pm.assigner_entreprise(profil["id"], ent["id"])
        portfolio = pm.get_portefeuille(profil["id"])
        assert len(portfolio) == 1

    def test_retirer_entreprise(self, pm):
        profil = pm.creer_profil("A", "B", "a@test.com", "Password123!")
        ent = pm.ajouter_entreprise("12345678901234", "Corp")
        pm.assigner_entreprise(profil["id"], ent["id"])
        pm.retirer_entreprise_portefeuille(profil["id"], ent["id"])
        portfolio = pm.get_portefeuille(profil["id"])
        assert len(portfolio) == 0


class TestPortfolioManagerAnalyses:
    """Tests de l'historique des analyses."""

    def test_enregistrer_analyse(self, pm):
        ent = pm.ajouter_entreprise("12345678901234", "Corp")
        analyse_id = pm.enregistrer_analyse(
            entreprise_id=ent["id"],
            nb_documents=3,
            nb_findings=5,
            score_risque=42,
        )
        assert analyse_id is not None

    def test_historique_par_entreprise(self, pm):
        ent = pm.ajouter_entreprise("12345678901234", "Corp")
        pm.enregistrer_analyse(entreprise_id=ent["id"], score_risque=10)
        pm.enregistrer_analyse(entreprise_id=ent["id"], score_risque=20)
        hist = pm.get_historique_analyses(entreprise_id=ent["id"])
        assert len(hist) == 2

    def test_historique_par_profil(self, pm):
        profil = pm.creer_profil("A", "B", "a@test.com", "Password123!")
        pm.enregistrer_analyse(profil_id=profil["id"], score_risque=10)
        hist = pm.get_historique_analyses(profil_id=profil["id"])
        assert len(hist) == 1

    def test_historique_global(self, pm):
        pm.enregistrer_analyse(score_risque=10)
        pm.enregistrer_analyse(score_risque=20)
        hist = pm.get_historique_analyses()
        assert len(hist) == 2

    def test_dashboard_entreprise(self, pm):
        ent = pm.ajouter_entreprise("12345678901234", "Corp")
        pm.enregistrer_analyse(entreprise_id=ent["id"], score_risque=30, nb_findings=5, impact_financier=1000.0)
        pm.enregistrer_analyse(entreprise_id=ent["id"], score_risque=40, nb_findings=3, impact_financier=500.0)
        dashboard = pm.get_dashboard_entreprise(ent["id"])
        assert dashboard["entreprise"] is not None
        assert dashboard["statistiques"]["nb_analyses"] == 2
        assert dashboard["statistiques"]["findings_cumules"] == 8

    def test_dashboard_entreprise_inexistante(self, pm):
        dashboard = pm.get_dashboard_entreprise("nonexistent")
        assert dashboard == {}

    def test_dashboard_entreprise_sans_analyse(self, pm):
        ent = pm.ajouter_entreprise("12345678901234", "Corp")
        dashboard = pm.get_dashboard_entreprise(ent["id"])
        assert dashboard["statistiques"]["nb_analyses"] == 0
        assert dashboard["statistiques"]["dernier_score_risque"] == 0
