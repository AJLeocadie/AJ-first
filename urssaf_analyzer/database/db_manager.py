"""Schema de la base de donnees SQLite pour URSSAF Analyzer.

Gere :
- Profils utilisateurs
- Portefeuille d'entreprises
- Historique des analyses
- Veille juridique (URSSAF + Legifrance)
"""

import sqlite3
from pathlib import Path
from contextlib import contextmanager

SCHEMA_SQL = """
-- Profils utilisateurs
CREATE TABLE IF NOT EXISTS profils (
    id TEXT PRIMARY KEY,
    nom TEXT NOT NULL,
    prenom TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    role TEXT DEFAULT 'analyste',
    mot_de_passe_hash TEXT NOT NULL,
    date_creation TEXT DEFAULT (datetime('now')),
    derniere_connexion TEXT,
    actif INTEGER DEFAULT 1
);

-- Entreprises du portefeuille
CREATE TABLE IF NOT EXISTS entreprises (
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
    date_creation_entreprise TEXT,
    date_ajout TEXT DEFAULT (datetime('now')),
    notes TEXT DEFAULT '',
    actif INTEGER DEFAULT 1
);

-- Association profil <-> entreprises (portefeuille)
CREATE TABLE IF NOT EXISTS portefeuille (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profil_id TEXT NOT NULL REFERENCES profils(id) ON DELETE CASCADE,
    entreprise_id TEXT NOT NULL REFERENCES entreprises(id) ON DELETE CASCADE,
    role_sur_entreprise TEXT DEFAULT 'gestionnaire',
    date_ajout TEXT DEFAULT (datetime('now')),
    UNIQUE(profil_id, entreprise_id)
);

-- Historique des analyses
CREATE TABLE IF NOT EXISTS analyses (
    id TEXT PRIMARY KEY,
    entreprise_id TEXT REFERENCES entreprises(id),
    profil_id TEXT REFERENCES profils(id),
    date_analyse TEXT DEFAULT (datetime('now')),
    nb_documents INTEGER DEFAULT 0,
    nb_findings INTEGER DEFAULT 0,
    score_risque INTEGER DEFAULT 0,
    impact_financier REAL DEFAULT 0,
    chemin_rapport TEXT DEFAULT '',
    format_rapport TEXT DEFAULT 'html',
    statut TEXT DEFAULT 'termine',
    duree_secondes REAL DEFAULT 0,
    resume TEXT DEFAULT ''
);

-- Documents analyses (rattaches a une analyse)
CREATE TABLE IF NOT EXISTS documents_analyses (
    id TEXT PRIMARY KEY,
    analyse_id TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    nom_fichier TEXT NOT NULL,
    type_fichier TEXT NOT NULL,
    hash_sha256 TEXT NOT NULL,
    taille_octets INTEGER DEFAULT 0,
    date_import TEXT DEFAULT (datetime('now')),
    annee_detectee INTEGER,
    periode_debut TEXT,
    periode_fin TEXT
);

-- Veille juridique : textes suivis
CREATE TABLE IF NOT EXISTS veille_textes (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    reference TEXT NOT NULL,
    titre TEXT NOT NULL,
    resume TEXT DEFAULT '',
    url TEXT DEFAULT '',
    date_publication TEXT,
    date_effet TEXT,
    date_collecte TEXT DEFAULT (datetime('now')),
    annee_reference INTEGER,
    categorie TEXT DEFAULT '',
    impact TEXT DEFAULT '',
    texte_complet TEXT DEFAULT '',
    actif INTEGER DEFAULT 1
);

-- Veille : alertes generees
CREATE TABLE IF NOT EXISTS veille_alertes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    texte_id TEXT REFERENCES veille_textes(id),
    entreprise_id TEXT REFERENCES entreprises(id),
    profil_id TEXT REFERENCES profils(id),
    titre TEXT NOT NULL,
    description TEXT DEFAULT '',
    severite TEXT DEFAULT 'info',
    date_alerte TEXT DEFAULT (datetime('now')),
    lue INTEGER DEFAULT 0,
    traitee INTEGER DEFAULT 0,
    date_traitement TEXT
);

-- Baremes et taux par annee (cache des donnees URSSAF)
CREATE TABLE IF NOT EXISTS baremes (
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
    date_collecte TEXT DEFAULT (datetime('now')),
    UNIQUE(annee, type_cotisation, code_ctp)
);

-- Plafonds par annee (PASS, SMIC)
CREATE TABLE IF NOT EXISTS plafonds (
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
);

-- Index pour performances
CREATE INDEX IF NOT EXISTS idx_entreprises_siret ON entreprises(siret);
CREATE INDEX IF NOT EXISTS idx_entreprises_siren ON entreprises(siren);
CREATE INDEX IF NOT EXISTS idx_portefeuille_profil ON portefeuille(profil_id);
CREATE INDEX IF NOT EXISTS idx_analyses_entreprise ON analyses(entreprise_id);
CREATE INDEX IF NOT EXISTS idx_analyses_date ON analyses(date_analyse);
CREATE INDEX IF NOT EXISTS idx_veille_textes_annee ON veille_textes(annee_reference);
CREATE INDEX IF NOT EXISTS idx_veille_alertes_profil ON veille_alertes(profil_id);
CREATE INDEX IF NOT EXISTS idx_baremes_annee ON baremes(annee);
CREATE INDEX IF NOT EXISTS idx_plafonds_annee ON plafonds(annee);
"""


class Database:
    """Gestionnaire de base de donnees SQLite."""

    def __init__(self, db_path: Path | str = "urssaf_analyzer.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self):
        with self.connection() as conn:
            conn.executescript(SCHEMA_SQL)

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self.connection() as conn:
            cursor = conn.execute(sql, params)
            return cursor.fetchall()

    def execute_insert(self, sql: str, params: tuple = ()) -> int:
        with self.connection() as conn:
            cursor = conn.execute(sql, params)
            return cursor.lastrowid

    def execute_many(self, sql: str, params_list: list[tuple]) -> None:
        with self.connection() as conn:
            conn.executemany(sql, params_list)
