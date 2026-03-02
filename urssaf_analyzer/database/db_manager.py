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

CURRENT_SCHEMA_VERSION = 2

SCHEMA_SQL = """
-- Version du schema (pour migrations incrementales)
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL,
    date_application TEXT DEFAULT (datetime('now'))
);

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
    date_creation_entreprise TEXT,
    date_immatriculation TEXT,
    date_cloture_exercice TEXT DEFAULT '',
    regime_tva TEXT DEFAULT 'reel_normal',
    date_ajout TEXT DEFAULT (datetime('now')),
    notes TEXT DEFAULT '',
    actif INTEGER DEFAULT 1
);

-- Profils independants (multi-profil : un user peut avoir entreprise(s) + independant(s))
CREATE TABLE IF NOT EXISTS profils_independants (
    id TEXT PRIMARY KEY,
    profil_id TEXT NOT NULL REFERENCES profils(id) ON DELETE CASCADE,
    type_statut TEXT NOT NULL,
    siret TEXT DEFAULT '',
    activite TEXT DEFAULT '',
    code_naf TEXT DEFAULT '',
    regime_fiscal TEXT DEFAULT '',
    option_is INTEGER DEFAULT 0,
    tva_franchise INTEGER DEFAULT 1,
    caisse_retraite TEXT DEFAULT '',
    acre INTEGER DEFAULT 0,
    annee_creation INTEGER DEFAULT 0,
    chiffre_affaires_annuel REAL DEFAULT 0,
    benefice_annuel REAL DEFAULT 0,
    remuneration_nette REAL DEFAULT 0,
    actif INTEGER DEFAULT 1,
    date_creation TEXT DEFAULT (datetime('now')),
    date_modification TEXT DEFAULT (datetime('now'))
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
    independant_id TEXT REFERENCES profils_independants(id),
    date_analyse TEXT DEFAULT (datetime('now')),
    nb_documents INTEGER DEFAULT 0,
    nb_findings INTEGER DEFAULT 0,
    score_risque INTEGER DEFAULT 0,
    impact_financier REAL DEFAULT 0,
    ecart_cotisations_total REAL DEFAULT 0,
    ecart_assiette_total REAL DEFAULT 0,
    montant_regularisation REAL DEFAULT 0,
    chemin_rapport TEXT DEFAULT '',
    format_rapport TEXT DEFAULT 'html',
    statut TEXT DEFAULT 'termine',
    duree_secondes REAL DEFAULT 0,
    resume TEXT DEFAULT '',
    detail_json TEXT DEFAULT '{}'
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
    periode_fin TEXT,
    manuscrit_detecte INTEGER DEFAULT 0,
    confiance_ocr REAL DEFAULT 1.0
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
    type_alerte TEXT DEFAULT '',
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
    libelle TEXT DEFAULT '',
    taux_patronal REAL,
    taux_salarial REAL,
    taux_patronal_reduit REAL,
    taux_salarial_reduit REAL,
    plafond REAL,
    assiette TEXT DEFAULT '',
    seuil_effectif INTEGER,
    seuil_smic_multiple REAL,
    reference_legale TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    date_effet TEXT,
    source TEXT DEFAULT 'urssaf.fr',
    mois_maj INTEGER DEFAULT 1,
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
    reference_legale TEXT DEFAULT '',
    date_effet TEXT,
    source TEXT DEFAULT 'urssaf.fr',
    UNIQUE(annee, type_plafond)
);

-- Textes reglementaires (conservation historique)
CREATE TABLE IF NOT EXISTS reglementation (
    id TEXT PRIMARY KEY,
    reference TEXT NOT NULL,
    titre TEXT NOT NULL,
    domaine TEXT DEFAULT '',
    annee_effet INTEGER NOT NULL,
    date_publication TEXT,
    date_effet TEXT,
    resume TEXT DEFAULT '',
    texte_complet TEXT DEFAULT '',
    url TEXT DEFAULT '',
    source TEXT DEFAULT 'legifrance.gouv.fr',
    impact TEXT DEFAULT '',
    date_modification TEXT DEFAULT (datetime('now')),
    UNIQUE(reference, annee_effet)
);

-- Journal des patches mensuels reglementaires
CREATE TABLE IF NOT EXISTS patches_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    annee INTEGER NOT NULL,
    mois INTEGER NOT NULL,
    date_execution TEXT DEFAULT (datetime('now')),
    source TEXT DEFAULT '',
    nb_baremes INTEGER DEFAULT 0,
    nb_plafonds INTEGER DEFAULT 0,
    nb_reglements INTEGER DEFAULT 0,
    statut TEXT DEFAULT 'pending',
    erreurs TEXT DEFAULT '',
    details TEXT DEFAULT '{}'
);

-- Index pour performances
CREATE INDEX IF NOT EXISTS idx_entreprises_siret ON entreprises(siret);
CREATE INDEX IF NOT EXISTS idx_entreprises_siren ON entreprises(siren);
CREATE INDEX IF NOT EXISTS idx_portefeuille_profil ON portefeuille(profil_id);
CREATE INDEX IF NOT EXISTS idx_analyses_entreprise ON analyses(entreprise_id);
CREATE INDEX IF NOT EXISTS idx_analyses_date ON analyses(date_analyse);
CREATE INDEX IF NOT EXISTS idx_documents_analyses_analyse ON documents_analyses(analyse_id);
CREATE INDEX IF NOT EXISTS idx_veille_textes_annee ON veille_textes(annee_reference);
CREATE INDEX IF NOT EXISTS idx_veille_alertes_profil ON veille_alertes(profil_id);
CREATE INDEX IF NOT EXISTS idx_baremes_annee ON baremes(annee);
CREATE INDEX IF NOT EXISTS idx_plafonds_annee ON plafonds(annee);
CREATE INDEX IF NOT EXISTS idx_reglementation_annee ON reglementation(annee_effet);
CREATE INDEX IF NOT EXISTS idx_profils_independants_profil ON profils_independants(profil_id);
"""

# ===================================================================
# MIGRATIONS : mises a jour incrementales pour bases existantes
# ===================================================================

MIGRATION_V2 = """
-- Migration V1 -> V2 : alignement avec le schema Supabase
-- Ajout des tables manquantes

CREATE TABLE IF NOT EXISTS profils_independants (
    id TEXT PRIMARY KEY,
    profil_id TEXT NOT NULL REFERENCES profils(id) ON DELETE CASCADE,
    type_statut TEXT NOT NULL,
    siret TEXT DEFAULT '',
    activite TEXT DEFAULT '',
    code_naf TEXT DEFAULT '',
    regime_fiscal TEXT DEFAULT '',
    option_is INTEGER DEFAULT 0,
    tva_franchise INTEGER DEFAULT 1,
    caisse_retraite TEXT DEFAULT '',
    acre INTEGER DEFAULT 0,
    annee_creation INTEGER DEFAULT 0,
    chiffre_affaires_annuel REAL DEFAULT 0,
    benefice_annuel REAL DEFAULT 0,
    remuneration_nette REAL DEFAULT 0,
    actif INTEGER DEFAULT 1,
    date_creation TEXT DEFAULT (datetime('now')),
    date_modification TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reglementation (
    id TEXT PRIMARY KEY,
    reference TEXT NOT NULL,
    titre TEXT NOT NULL,
    domaine TEXT DEFAULT '',
    annee_effet INTEGER NOT NULL,
    date_publication TEXT,
    date_effet TEXT,
    resume TEXT DEFAULT '',
    texte_complet TEXT DEFAULT '',
    url TEXT DEFAULT '',
    source TEXT DEFAULT 'legifrance.gouv.fr',
    impact TEXT DEFAULT '',
    date_modification TEXT DEFAULT (datetime('now')),
    UNIQUE(reference, annee_effet)
);

CREATE TABLE IF NOT EXISTS patches_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    annee INTEGER NOT NULL,
    mois INTEGER NOT NULL,
    date_execution TEXT DEFAULT (datetime('now')),
    source TEXT DEFAULT '',
    nb_baremes INTEGER DEFAULT 0,
    nb_plafonds INTEGER DEFAULT 0,
    nb_reglements INTEGER DEFAULT 0,
    statut TEXT DEFAULT 'pending',
    erreurs TEXT DEFAULT '',
    details TEXT DEFAULT '{}'
);

-- Nouveaux index
CREATE INDEX IF NOT EXISTS idx_documents_analyses_analyse ON documents_analyses(analyse_id);
CREATE INDEX IF NOT EXISTS idx_reglementation_annee ON reglementation(annee_effet);
CREATE INDEX IF NOT EXISTS idx_profils_independants_profil ON profils_independants(profil_id);
"""

# Colonnes a ajouter aux tables existantes lors de la migration V2.
# Format : (table, colonne, definition_sql)
MIGRATION_V2_COLUMNS = [
    # entreprises : +13 colonnes
    ("entreprises", "nom_commercial", "TEXT DEFAULT ''"),
    ("entreprises", "forme_juridique_code", "TEXT DEFAULT ''"),
    ("entreprises", "activite_principale", "TEXT DEFAULT ''"),
    ("entreprises", "tranche_effectif", "TEXT DEFAULT ''"),
    ("entreprises", "capital_social", "REAL DEFAULT 0"),
    ("entreprises", "taux_versement_mobilite", "REAL DEFAULT 0"),
    ("entreprises", "convention_collective_idcc", "TEXT DEFAULT ''"),
    ("entreprises", "convention_collective_titre", "TEXT DEFAULT ''"),
    ("entreprises", "pays", "TEXT DEFAULT 'France'"),
    ("entreprises", "objet_social", "TEXT DEFAULT ''"),
    ("entreprises", "date_immatriculation", "TEXT"),
    ("entreprises", "date_cloture_exercice", "TEXT DEFAULT ''"),
    ("entreprises", "regime_tva", "TEXT DEFAULT 'reel_normal'"),
    # analyses : +5 colonnes
    ("analyses", "independant_id", "TEXT REFERENCES profils_independants(id)"),
    ("analyses", "ecart_cotisations_total", "REAL DEFAULT 0"),
    ("analyses", "ecart_assiette_total", "REAL DEFAULT 0"),
    ("analyses", "montant_regularisation", "REAL DEFAULT 0"),
    ("analyses", "detail_json", "TEXT DEFAULT '{}'"),
    # documents_analyses : +2 colonnes
    ("documents_analyses", "manuscrit_detecte", "INTEGER DEFAULT 0"),
    ("documents_analyses", "confiance_ocr", "REAL DEFAULT 1.0"),
    # baremes : +7 colonnes
    ("baremes", "libelle", "TEXT DEFAULT ''"),
    ("baremes", "taux_patronal_reduit", "REAL"),
    ("baremes", "taux_salarial_reduit", "REAL"),
    ("baremes", "assiette", "TEXT DEFAULT ''"),
    ("baremes", "seuil_effectif", "INTEGER"),
    ("baremes", "reference_legale", "TEXT DEFAULT ''"),
    ("baremes", "notes", "TEXT DEFAULT ''"),
    ("baremes", "mois_maj", "INTEGER DEFAULT 1"),
    # plafonds : +1 colonne
    ("plafonds", "reference_legale", "TEXT DEFAULT ''"),
    # veille_alertes : +1 colonne
    ("veille_alertes", "type_alerte", "TEXT DEFAULT ''"),
]


class Database:
    """Gestionnaire de base de donnees SQLite."""

    def __init__(self, db_path: Path | str = "urssaf_analyzer.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self):
        with self.connection() as conn:
            conn.executescript(SCHEMA_SQL)
            self._apply_migrations(conn)

    def _get_schema_version(self, conn) -> int:
        """Retourne la version actuelle du schema."""
        try:
            cursor = conn.execute("SELECT MAX(version) FROM schema_version")
            row = cursor.fetchone()
            return row[0] if row and row[0] is not None else 0
        except sqlite3.OperationalError:
            return 0

    def _set_schema_version(self, conn, version: int):
        """Enregistre la version du schema."""
        conn.execute(
            "INSERT INTO schema_version (version) VALUES (?)", (version,)
        )

    def _apply_migrations(self, conn):
        """Applique les migrations incrementales si necessaire."""
        current = self._get_schema_version(conn)
        if current >= CURRENT_SCHEMA_VERSION:
            return

        if current < 2:
            self._migrate_to_v2(conn)

        self._set_schema_version(conn, CURRENT_SCHEMA_VERSION)

    def _migrate_to_v2(self, conn):
        """Migration V1 -> V2 : nouvelles tables + colonnes manquantes."""
        # Creer les nouvelles tables
        conn.executescript(MIGRATION_V2)

        # Ajouter les colonnes manquantes aux tables existantes
        for table, column, definition in MIGRATION_V2_COLUMNS:
            try:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                )
            except sqlite3.OperationalError:
                # La colonne existe deja (base fraiche) : on ignore
                pass

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
