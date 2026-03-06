"""Tests exhaustifs du module de base de donnees.

Couverture : schema, migrations, CRUD, concurrence, integrite.
"""

import sys
import sqlite3
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.database.db_manager import (
    Database, SCHEMA_SQL,
    _get_schema_version, _table_exists, _apply_migration_v2,
)


class TestDatabaseCreation:
    """Tests de creation et initialisation de la base."""

    def test_create_new_database(self, tmp_path):
        db = Database(tmp_path / "new.db")
        assert db.db_path.exists()

    def test_schema_version_is_2(self, tmp_path):
        db = Database(tmp_path / "v2.db")
        assert db.get_schema_version() == 2

    def test_all_tables_created(self, tmp_path):
        db = Database(tmp_path / "tables.db")
        expected_tables = [
            "schema_version", "profils", "entreprises",
            "profils_independants", "portefeuille", "analyses",
            "documents_analyses", "veille_textes", "veille_alertes",
            "baremes", "plafonds", "reglementation", "patches_log",
        ]
        with db.connection() as conn:
            for table in expected_tables:
                assert _table_exists(conn, table), f"Table {table} manquante"

    def test_indexes_created(self, tmp_path):
        db = Database(tmp_path / "idx.db")
        with db.connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
            )
            indexes = {row[0] for row in cursor.fetchall()}
        assert "idx_entreprises_siret" in indexes
        assert "idx_analyses_date" in indexes
        assert "idx_baremes_annee" in indexes

    def test_create_directory_if_not_exists(self, tmp_path):
        db_path = tmp_path / "sub" / "dir" / "test.db"
        db = Database(db_path)
        assert db.db_path.exists()

    def test_wal_mode_enabled(self, tmp_path):
        db = Database(tmp_path / "wal.db")
        with db.connection() as conn:
            result = conn.execute("PRAGMA journal_mode").fetchone()
            assert result[0] == "wal"

    def test_foreign_keys_enabled(self, tmp_path):
        db = Database(tmp_path / "fk.db")
        with db.connection() as conn:
            result = conn.execute("PRAGMA foreign_keys").fetchone()
            assert result[0] == 1


class TestDatabaseCRUD:
    """Tests CRUD sur la base de donnees."""

    def test_insert_and_select(self, tmp_path):
        db = Database(tmp_path / "crud.db")
        db.execute_insert(
            "INSERT INTO profils (id, nom, prenom, email, mot_de_passe_hash) VALUES (?, ?, ?, ?, ?)",
            ("p1", "Dupont", "Jean", "jean@test.fr", "hash123"),
        )
        rows = db.execute("SELECT * FROM profils WHERE id = ?", ("p1",))
        assert len(rows) == 1
        assert rows[0]["nom"] == "Dupont"

    def test_insert_entreprise(self, tmp_path):
        db = Database(tmp_path / "ent.db")
        db.execute_insert(
            "INSERT INTO entreprises (id, siret, siren, raison_sociale) VALUES (?, ?, ?, ?)",
            ("e1", "12345678901234", "123456789", "ACME SARL"),
        )
        rows = db.execute("SELECT * FROM entreprises WHERE siret = ?", ("12345678901234",))
        assert len(rows) == 1
        assert rows[0]["raison_sociale"] == "ACME SARL"

    def test_insert_analyse(self, tmp_path):
        db = Database(tmp_path / "analyse.db")
        db.execute_insert(
            "INSERT INTO analyses (id, nb_documents, nb_findings, score_risque, impact_financier) "
            "VALUES (?, ?, ?, ?, ?)",
            ("a1", 3, 5, 72, 15000.50),
        )
        rows = db.execute("SELECT * FROM analyses WHERE id = ?", ("a1",))
        assert len(rows) == 1
        assert rows[0]["score_risque"] == 72
        assert rows[0]["impact_financier"] == 15000.50

    def test_execute_many(self, tmp_path):
        db = Database(tmp_path / "many.db")
        params = [
            ("p1", "Nom1", "Prenom1", "email1@test.fr", "h1"),
            ("p2", "Nom2", "Prenom2", "email2@test.fr", "h2"),
            ("p3", "Nom3", "Prenom3", "email3@test.fr", "h3"),
        ]
        db.execute_many(
            "INSERT INTO profils (id, nom, prenom, email, mot_de_passe_hash) VALUES (?, ?, ?, ?, ?)",
            params,
        )
        rows = db.execute("SELECT COUNT(*) as cnt FROM profils")
        assert rows[0]["cnt"] == 3

    def test_unique_constraint_email(self, tmp_path):
        db = Database(tmp_path / "unique.db")
        db.execute_insert(
            "INSERT INTO profils (id, nom, prenom, email, mot_de_passe_hash) VALUES (?, ?, ?, ?, ?)",
            ("p1", "Nom", "Prenom", "dup@test.fr", "hash"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute_insert(
                "INSERT INTO profils (id, nom, prenom, email, mot_de_passe_hash) VALUES (?, ?, ?, ?, ?)",
                ("p2", "Nom2", "Prenom2", "dup@test.fr", "hash2"),
            )

    def test_unique_constraint_siret(self, tmp_path):
        db = Database(tmp_path / "siret.db")
        db.execute_insert(
            "INSERT INTO entreprises (id, siret, siren, raison_sociale) VALUES (?, ?, ?, ?)",
            ("e1", "11111111111111", "111111111", "Ent1"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute_insert(
                "INSERT INTO entreprises (id, siret, siren, raison_sociale) VALUES (?, ?, ?, ?)",
                ("e2", "11111111111111", "111111111", "Ent2"),
            )

    def test_rollback_on_error(self, tmp_path):
        db = Database(tmp_path / "rollback.db")
        try:
            with db.connection() as conn:
                conn.execute(
                    "INSERT INTO profils (id, nom, prenom, email, mot_de_passe_hash) VALUES (?, ?, ?, ?, ?)",
                    ("r1", "Nom", "Prenom", "roll@test.fr", "hash"),
                )
                raise ValueError("Erreur simulee")
        except ValueError:
            pass
        rows = db.execute("SELECT * FROM profils WHERE id = ?", ("r1",))
        assert len(rows) == 0


class TestDatabaseMigration:
    """Tests des migrations de schema."""

    def test_v1_to_v2_migration(self, tmp_path):
        """Simule une base V1 et verifie la migration V2."""
        db_path = tmp_path / "v1.db"
        conn = sqlite3.connect(str(db_path))
        # Creer une base V1 minimale
        conn.execute("""CREATE TABLE profils (
            id TEXT PRIMARY KEY,
            nom TEXT NOT NULL,
            prenom TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            role TEXT DEFAULT 'analyste',
            mot_de_passe_hash TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE entreprises (
            id TEXT PRIMARY KEY,
            siret TEXT UNIQUE NOT NULL,
            siren TEXT NOT NULL,
            raison_sociale TEXT NOT NULL,
            forme_juridique TEXT DEFAULT '',
            code_naf TEXT DEFAULT '',
            effectif INTEGER DEFAULT 0,
            taux_at REAL DEFAULT 0.0208,
            convention_collective TEXT DEFAULT '',
            adresse TEXT DEFAULT '',
            code_postal TEXT DEFAULT '',
            ville TEXT DEFAULT '',
            date_ajout TEXT,
            notes TEXT DEFAULT '',
            actif INTEGER DEFAULT 1
        )""")
        conn.execute("""CREATE TABLE analyses (
            id TEXT PRIMARY KEY,
            entreprise_id TEXT,
            profil_id TEXT,
            date_analyse TEXT,
            nb_documents INTEGER DEFAULT 0,
            nb_findings INTEGER DEFAULT 0,
            score_risque INTEGER DEFAULT 0,
            impact_financier REAL DEFAULT 0,
            chemin_rapport TEXT DEFAULT '',
            format_rapport TEXT DEFAULT 'html',
            statut TEXT DEFAULT 'termine',
            duree_secondes REAL DEFAULT 0,
            resume TEXT DEFAULT ''
        )""")
        conn.execute("""CREATE TABLE documents_analyses (
            id TEXT PRIMARY KEY,
            analyse_id TEXT NOT NULL,
            nom_fichier TEXT NOT NULL,
            type_fichier TEXT NOT NULL,
            hash_sha256 TEXT NOT NULL,
            taille_octets INTEGER DEFAULT 0,
            date_import TEXT,
            annee_detectee INTEGER,
            periode_debut TEXT,
            periode_fin TEXT
        )""")
        conn.execute("""CREATE TABLE portefeuille (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profil_id TEXT NOT NULL,
            entreprise_id TEXT NOT NULL,
            role_sur_entreprise TEXT DEFAULT 'gestionnaire',
            date_ajout TEXT,
            UNIQUE(profil_id, entreprise_id)
        )""")
        conn.execute("""CREATE TABLE veille_textes (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            reference TEXT NOT NULL,
            titre TEXT NOT NULL,
            resume TEXT DEFAULT '',
            url TEXT DEFAULT '',
            date_publication TEXT,
            date_effet TEXT,
            date_collecte TEXT,
            annee_reference INTEGER,
            categorie TEXT DEFAULT '',
            impact TEXT DEFAULT '',
            texte_complet TEXT DEFAULT '',
            actif INTEGER DEFAULT 1
        )""")
        conn.execute("""CREATE TABLE veille_alertes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            texte_id TEXT,
            entreprise_id TEXT,
            profil_id TEXT,
            titre TEXT NOT NULL,
            description TEXT DEFAULT '',
            severite TEXT DEFAULT 'info',
            date_alerte TEXT,
            lue INTEGER DEFAULT 0,
            traitee INTEGER DEFAULT 0,
            date_traitement TEXT
        )""")
        conn.execute("""CREATE TABLE baremes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            annee INTEGER NOT NULL,
            type_cotisation TEXT NOT NULL,
            code_ctp TEXT DEFAULT '',
            taux_patronal REAL,
            taux_salarial REAL,
            plafond REAL,
            seuil_smic_multiple REAL,
            date_effet TEXT,
            source TEXT DEFAULT 'urssaf.fr',
            date_collecte TEXT,
            UNIQUE(annee, type_cotisation, code_ctp)
        )""")
        conn.execute("""CREATE TABLE plafonds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            annee INTEGER NOT NULL,
            type_plafond TEXT NOT NULL,
            valeur_annuelle REAL,
            valeur_mensuelle REAL,
            valeur_journaliere REAL,
            valeur_horaire REAL,
            date_effet TEXT,
            source TEXT DEFAULT 'urssaf.fr',
            UNIQUE(annee, type_plafond)
        )""")
        conn.execute("INSERT INTO profils VALUES ('p1', 'Test', 'User', 'test@test.fr', 'analyste', 'hash')")
        conn.commit()
        conn.close()

        # La migration doit se faire automatiquement
        db = Database(db_path)
        assert db.get_schema_version() == 2

        # Verifier que les nouvelles tables existent
        with db.connection() as conn:
            assert _table_exists(conn, "profils_independants")
            assert _table_exists(conn, "reglementation")
            assert _table_exists(conn, "patches_log")

        # Verifier que les donnees V1 sont preservees
        rows = db.execute("SELECT * FROM profils WHERE id = ?", ("p1",))
        assert len(rows) == 1

    def test_reopening_v2_database(self, tmp_path):
        """Rouvrir une base V2 ne doit pas causer d'erreur."""
        db_path = tmp_path / "reopen.db"
        db1 = Database(db_path)
        db1.execute_insert(
            "INSERT INTO profils (id, nom, prenom, email, mot_de_passe_hash) VALUES (?, ?, ?, ?, ?)",
            ("p1", "Test", "User", "t@t.fr", "h"),
        )
        db2 = Database(db_path)
        assert db2.get_schema_version() == 2
        rows = db2.execute("SELECT * FROM profils")
        assert len(rows) == 1


class TestDatabaseRelations:
    """Tests des relations et contraintes referentielles."""

    def test_portefeuille_relation(self, tmp_path):
        db = Database(tmp_path / "rel.db")
        db.execute_insert(
            "INSERT INTO profils (id, nom, prenom, email, mot_de_passe_hash) VALUES (?, ?, ?, ?, ?)",
            ("p1", "Test", "User", "t@t.fr", "h"),
        )
        db.execute_insert(
            "INSERT INTO entreprises (id, siret, siren, raison_sociale) VALUES (?, ?, ?, ?)",
            ("e1", "12345678901234", "123456789", "ACME"),
        )
        db.execute_insert(
            "INSERT INTO portefeuille (profil_id, entreprise_id) VALUES (?, ?)",
            ("p1", "e1"),
        )
        rows = db.execute(
            "SELECT e.raison_sociale FROM portefeuille p "
            "JOIN entreprises e ON p.entreprise_id = e.id "
            "WHERE p.profil_id = ?",
            ("p1",),
        )
        assert len(rows) == 1
        assert rows[0]["raison_sociale"] == "ACME"

    def test_cascade_delete_profil(self, tmp_path):
        db = Database(tmp_path / "cascade.db")
        db.execute_insert(
            "INSERT INTO profils (id, nom, prenom, email, mot_de_passe_hash) VALUES (?, ?, ?, ?, ?)",
            ("p1", "Test", "User", "t@t.fr", "h"),
        )
        db.execute_insert(
            "INSERT INTO profils_independants (id, profil_id, type_statut) VALUES (?, ?, ?)",
            ("pi1", "p1", "micro_entrepreneur"),
        )
        db.execute("DELETE FROM profils WHERE id = ?", ("p1",))
        rows = db.execute("SELECT * FROM profils_independants WHERE profil_id = ?", ("p1",))
        assert len(rows) == 0
