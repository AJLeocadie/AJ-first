"""Client Supabase pour URSSAF Analyzer.

Gere :
- Connexion et authentification Supabase
- CRUD profils, entreprises, portefeuille
- Profils independants (multi-profil)
- Historique baremes et reglementation (conservation annees anterieures)
- Patch mensuel de mise a jour reglementaire

Configuration via variables d'environnement :
  SUPABASE_URL=https://xxx.supabase.co
  SUPABASE_KEY=eyJhbG...
  SUPABASE_SERVICE_KEY=eyJhbG... (pour les operations admin/patch)

Ref architecture :
- Toutes les tables prefixees 'ua_' pour eviter les collisions
- RLS (Row Level Security) active sur toutes les tables
- Conservation historique : chaque bareme/taux est versionne par annee
"""

import os
import json
from datetime import datetime, date
from decimal import Decimal
from typing import Optional

# Le client Supabase est optionnel
try:
    from supabase import create_client, Client
    HAS_SUPABASE = True
except ImportError:
    HAS_SUPABASE = False
    Client = None


class DecimalEncoder(json.JSONEncoder):
    """Encode Decimal en float pour JSON."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        return super().default(obj)


def _serialize(data: dict) -> dict:
    """Serialise un dict pour Supabase (convertit Decimal, date)."""
    return json.loads(json.dumps(data, cls=DecimalEncoder))


class SupabaseClient:
    """Client Supabase pour URSSAF Analyzer."""

    def __init__(
        self,
        url: str = None,
        key: str = None,
        service_key: str = None,
    ):
        self.url = url or os.environ.get("SUPABASE_URL", "")
        self.key = key or os.environ.get("SUPABASE_KEY", "")
        self.service_key = service_key or os.environ.get("SUPABASE_SERVICE_KEY", "")
        self._client: Optional[Client] = None
        self._admin_client: Optional[Client] = None

    @property
    def client(self) -> Optional[Client]:
        """Client Supabase standard (avec RLS)."""
        if not HAS_SUPABASE:
            return None
        if self._client is None and self.url and self.key:
            self._client = create_client(self.url, self.key)
        return self._client

    @property
    def admin(self) -> Optional[Client]:
        """Client admin (bypass RLS) pour les operations systeme."""
        if not HAS_SUPABASE:
            return None
        if self._admin_client is None and self.url and self.service_key:
            self._admin_client = create_client(self.url, self.service_key)
        return self._admin_client

    @property
    def is_connected(self) -> bool:
        return self.client is not None

    # ============================
    # PROFILS UTILISATEURS
    # ============================

    def creer_profil(self, data: dict) -> dict:
        """Cree un profil utilisateur."""
        if not self.client:
            return {"error": "Supabase non connecte"}
        result = self.client.table("ua_profils").insert(_serialize(data)).execute()
        return result.data[0] if result.data else {}

    def get_profil(self, profil_id: str) -> Optional[dict]:
        result = self.client.table("ua_profils").select("*").eq("id", profil_id).execute()
        return result.data[0] if result.data else None

    def get_profil_par_email(self, email: str) -> Optional[dict]:
        result = self.client.table("ua_profils").select("*").eq("email", email).execute()
        return result.data[0] if result.data else None

    def lister_profils(self) -> list[dict]:
        result = self.client.table("ua_profils").select("*").order("nom").execute()
        return result.data or []

    def maj_profil(self, profil_id: str, data: dict) -> dict:
        result = self.client.table("ua_profils").update(_serialize(data)).eq("id", profil_id).execute()
        return result.data[0] if result.data else {}

    # ============================
    # ENTREPRISES
    # ============================

    def creer_entreprise(self, data: dict) -> dict:
        if not self.client:
            return {"error": "Supabase non connecte"}
        result = self.client.table("ua_entreprises").insert(_serialize(data)).execute()
        return result.data[0] if result.data else {}

    def get_entreprise(self, entreprise_id: str) -> Optional[dict]:
        result = self.client.table("ua_entreprises").select("*").eq("id", entreprise_id).execute()
        return result.data[0] if result.data else None

    def get_entreprise_par_siret(self, siret: str) -> Optional[dict]:
        result = self.client.table("ua_entreprises").select("*").eq("siret", siret).execute()
        return result.data[0] if result.data else None

    def rechercher_entreprises(self, terme: str) -> list[dict]:
        result = (
            self.client.table("ua_entreprises")
            .select("*")
            .or_(f"raison_sociale.ilike.%{terme}%,siret.ilike.%{terme}%,ville.ilike.%{terme}%")
            .order("raison_sociale")
            .execute()
        )
        return result.data or []

    def lister_entreprises(self) -> list[dict]:
        result = self.client.table("ua_entreprises").select("*").eq("actif", True).order("raison_sociale").execute()
        return result.data or []

    def maj_entreprise(self, entreprise_id: str, data: dict) -> dict:
        result = self.client.table("ua_entreprises").update(_serialize(data)).eq("id", entreprise_id).execute()
        return result.data[0] if result.data else {}

    # ============================
    # PROFILS INDEPENDANTS
    # ============================

    def creer_profil_independant(self, data: dict) -> dict:
        if not self.client:
            return {"error": "Supabase non connecte"}
        result = self.client.table("ua_profils_independants").insert(_serialize(data)).execute()
        return result.data[0] if result.data else {}

    def get_profils_independants(self, profil_id: str) -> list[dict]:
        result = (
            self.client.table("ua_profils_independants")
            .select("*")
            .eq("profil_id", profil_id)
            .order("created_at")
            .execute()
        )
        return result.data or []

    def maj_profil_independant(self, independant_id: str, data: dict) -> dict:
        result = (
            self.client.table("ua_profils_independants")
            .update(_serialize(data))
            .eq("id", independant_id)
            .execute()
        )
        return result.data[0] if result.data else {}

    # ============================
    # PORTEFEUILLE (MULTI-PROFIL)
    # ============================

    def assigner_entreprise(self, profil_id: str, entreprise_id: str, role: str = "gestionnaire") -> dict:
        data = {"profil_id": profil_id, "entreprise_id": entreprise_id, "role_sur_entreprise": role}
        result = self.client.table("ua_portefeuille").upsert(data).execute()
        return result.data[0] if result.data else {}

    def get_portefeuille(self, profil_id: str) -> list[dict]:
        """Retourne tout le portefeuille d'un utilisateur : entreprises + profils independants."""
        entreprises = (
            self.client.table("ua_portefeuille")
            .select("*, ua_entreprises(*)")
            .eq("profil_id", profil_id)
            .execute()
        )
        independants = self.get_profils_independants(profil_id)
        return {
            "entreprises": entreprises.data or [],
            "profils_independants": independants,
        }

    # ============================
    # BAREMES ET REGLEMENTATION (HISTORIQUE)
    # ============================

    def get_baremes(self, annee: int) -> list[dict]:
        """Recupere les baremes pour une annee donnee."""
        result = (
            self.client.table("ua_baremes_historique")
            .select("*")
            .eq("annee", annee)
            .order("type_cotisation")
            .execute()
        )
        return result.data or []

    def get_plafonds(self, annee: int) -> list[dict]:
        """Recupere les plafonds pour une annee donnee."""
        result = (
            self.client.table("ua_plafonds_historique")
            .select("*")
            .eq("annee", annee)
            .execute()
        )
        return result.data or []

    def get_annees_disponibles(self) -> list[int]:
        """Liste les annees disponibles en base."""
        result = (
            self.client.table("ua_baremes_historique")
            .select("annee")
            .order("annee")
            .execute()
        )
        annees = list(set(r["annee"] for r in (result.data or [])))
        return sorted(annees)

    def get_reglementation(self, annee: int, domaine: str = None) -> list[dict]:
        """Recupere la reglementation applicable pour une annee."""
        query = self.client.table("ua_reglementation").select("*").eq("annee_effet", annee)
        if domaine:
            query = query.eq("domaine", domaine)
        result = query.order("reference").execute()
        return result.data or []

    # ============================
    # ANALYSES (HISTORIQUE)
    # ============================

    def enregistrer_analyse(self, data: dict) -> dict:
        result = self.client.table("ua_analyses").insert(_serialize(data)).execute()
        return result.data[0] if result.data else {}

    def get_historique_analyses(self, entreprise_id: str = None, profil_id: str = None, limit: int = 50) -> list[dict]:
        query = self.client.table("ua_analyses").select("*")
        if entreprise_id:
            query = query.eq("entreprise_id", entreprise_id)
        if profil_id:
            query = query.eq("profil_id", profil_id)
        result = query.order("created_at", desc=True).limit(limit).execute()
        return result.data or []

    # ============================
    # PATCH MENSUEL REGLEMENTAIRE
    # ============================

    def executer_patch_mensuel(self, annee: int, mois: int, donnees_patch: dict) -> dict:
        """Execute un patch mensuel de mise a jour reglementaire.

        Le patch :
        1. Insere/met a jour les baremes pour l'annee en cours
        2. Conserve les donnees des annees anterieures (jamais supprimees)
        3. Journalise le patch dans ua_patches_log

        Args:
            annee: Annee du patch
            mois: Mois du patch
            donnees_patch: {
                "baremes": [...],
                "plafonds": [...],
                "reglementation": [...],
                "source": "urssaf.fr / legifrance",
            }
        """
        admin = self.admin
        if not admin:
            return {"error": "Client admin non disponible", "status": "failed"}

        resultats = {"baremes_maj": 0, "plafonds_maj": 0, "reglements_maj": 0}

        # 1. Baremes
        for bareme in donnees_patch.get("baremes", []):
            bareme["annee"] = annee
            bareme["mois_maj"] = mois
            bareme["date_maj"] = datetime.now().isoformat()
            admin.table("ua_baremes_historique").upsert(
                _serialize(bareme),
                on_conflict="annee,type_cotisation,code_ctp"
            ).execute()
            resultats["baremes_maj"] += 1

        # 2. Plafonds
        for plafond in donnees_patch.get("plafonds", []):
            plafond["annee"] = annee
            plafond["date_maj"] = datetime.now().isoformat()
            admin.table("ua_plafonds_historique").upsert(
                _serialize(plafond),
                on_conflict="annee,type_plafond"
            ).execute()
            resultats["plafonds_maj"] += 1

        # 3. Reglementation
        for reglement in donnees_patch.get("reglementation", []):
            reglement["annee_effet"] = annee
            reglement["date_maj"] = datetime.now().isoformat()
            admin.table("ua_reglementation").upsert(
                _serialize(reglement),
                on_conflict="reference,annee_effet"
            ).execute()
            resultats["reglements_maj"] += 1

        # 4. Log du patch
        admin.table("ua_patches_log").insert({
            "annee": annee,
            "mois": mois,
            "date_execution": datetime.now().isoformat(),
            "source": donnees_patch.get("source", ""),
            "nb_baremes": resultats["baremes_maj"],
            "nb_plafonds": resultats["plafonds_maj"],
            "nb_reglements": resultats["reglements_maj"],
            "statut": "success",
        }).execute()

        resultats["status"] = "success"
        resultats["message"] = f"Patch {annee}-{mois:02d} applique avec succes"
        return resultats

    def get_historique_patches(self, limit: int = 24) -> list[dict]:
        """Historique des patches appliques."""
        result = (
            self.client.table("ua_patches_log")
            .select("*")
            .order("date_execution", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []


# ===================================================================
# SCHEMA SQL SUPABASE (pour migration initiale)
# ===================================================================

SUPABASE_SCHEMA_SQL = """
-- ================================================
-- URSSAF Analyzer - Schema Supabase
-- Prefixe : ua_ (urssaf analyzer)
-- ================================================

-- Profils utilisateurs
CREATE TABLE IF NOT EXISTS ua_profils (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nom TEXT NOT NULL,
    prenom TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    role TEXT DEFAULT 'analyste',
    mot_de_passe_hash TEXT NOT NULL,
    actif BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    derniere_connexion TIMESTAMPTZ
);

-- Entreprises
CREATE TABLE IF NOT EXISTS ua_entreprises (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
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
    capital_social NUMERIC DEFAULT 0,
    taux_at NUMERIC DEFAULT 0.0208,
    taux_versement_mobilite NUMERIC DEFAULT 0,
    convention_collective_idcc TEXT DEFAULT '',
    convention_collective_titre TEXT DEFAULT '',
    adresse TEXT DEFAULT '',
    code_postal TEXT DEFAULT '',
    ville TEXT DEFAULT '',
    pays TEXT DEFAULT 'France',
    objet_social TEXT DEFAULT '',
    date_creation_entreprise DATE,
    date_immatriculation DATE,
    date_cloture_exercice TEXT DEFAULT '',
    regime_tva TEXT DEFAULT 'reel_normal',
    notes TEXT DEFAULT '',
    actif BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Profils independants (multi-profil : un user peut avoir entreprise(s) + independant(s))
CREATE TABLE IF NOT EXISTS ua_profils_independants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profil_id UUID NOT NULL REFERENCES ua_profils(id) ON DELETE CASCADE,
    type_statut TEXT NOT NULL, -- micro_entrepreneur, ei_ir, gerant_majoritaire, profession_liberale
    siret TEXT DEFAULT '',
    activite TEXT DEFAULT '',
    code_naf TEXT DEFAULT '',
    regime_fiscal TEXT DEFAULT '', -- micro, reel_simplifie, reel_normal
    option_is BOOLEAN DEFAULT false,
    tva_franchise BOOLEAN DEFAULT true,
    caisse_retraite TEXT DEFAULT '', -- SSI, CIPAV, CNAVPL
    acre BOOLEAN DEFAULT false,
    annee_creation INTEGER DEFAULT 0,
    chiffre_affaires_annuel NUMERIC DEFAULT 0,
    benefice_annuel NUMERIC DEFAULT 0,
    remuneration_nette NUMERIC DEFAULT 0,
    actif BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Portefeuille (profil <-> entreprises)
CREATE TABLE IF NOT EXISTS ua_portefeuille (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profil_id UUID NOT NULL REFERENCES ua_profils(id) ON DELETE CASCADE,
    entreprise_id UUID NOT NULL REFERENCES ua_entreprises(id) ON DELETE CASCADE,
    role_sur_entreprise TEXT DEFAULT 'gestionnaire',
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(profil_id, entreprise_id)
);

-- Analyses (historique)
CREATE TABLE IF NOT EXISTS ua_analyses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entreprise_id UUID REFERENCES ua_entreprises(id),
    profil_id UUID REFERENCES ua_profils(id),
    independant_id UUID REFERENCES ua_profils_independants(id),
    nb_documents INTEGER DEFAULT 0,
    nb_constats INTEGER DEFAULT 0,
    ecart_cotisations_total NUMERIC DEFAULT 0,
    ecart_assiette_total NUMERIC DEFAULT 0,
    montant_regularisation NUMERIC DEFAULT 0,
    chemin_rapport TEXT DEFAULT '',
    format_rapport TEXT DEFAULT 'json',
    statut TEXT DEFAULT 'termine',
    duree_secondes NUMERIC DEFAULT 0,
    resume TEXT DEFAULT '',
    detail_json JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Documents analyses
CREATE TABLE IF NOT EXISTS ua_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    analyse_id UUID REFERENCES ua_analyses(id) ON DELETE CASCADE,
    nom_fichier TEXT NOT NULL,
    type_fichier TEXT NOT NULL,
    hash_sha256 TEXT NOT NULL,
    taille_octets INTEGER DEFAULT 0,
    annee_detectee INTEGER,
    periode_debut DATE,
    periode_fin DATE,
    manuscrit_detecte BOOLEAN DEFAULT false,
    confiance_ocr NUMERIC DEFAULT 1.0,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- ==============================================
-- BAREMES HISTORIQUES (conservation multi-annees)
-- ==============================================

CREATE TABLE IF NOT EXISTS ua_baremes_historique (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    annee INTEGER NOT NULL,
    type_cotisation TEXT NOT NULL,
    code_ctp TEXT DEFAULT '',
    libelle TEXT DEFAULT '',
    taux_patronal NUMERIC,
    taux_salarial NUMERIC,
    taux_patronal_reduit NUMERIC,
    taux_salarial_reduit NUMERIC,
    plafond TEXT DEFAULT '',
    assiette TEXT DEFAULT '',
    seuil_effectif INTEGER,
    seuil_smic_multiple NUMERIC,
    reference_legale TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    source TEXT DEFAULT 'urssaf.fr',
    mois_maj INTEGER DEFAULT 1,
    date_maj TIMESTAMPTZ DEFAULT now(),
    UNIQUE(annee, type_cotisation, code_ctp)
);

CREATE TABLE IF NOT EXISTS ua_plafonds_historique (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    annee INTEGER NOT NULL,
    type_plafond TEXT NOT NULL, -- PASS, SMIC, plafond_chomage, etc.
    valeur_annuelle NUMERIC,
    valeur_mensuelle NUMERIC,
    valeur_journaliere NUMERIC,
    valeur_horaire NUMERIC,
    reference_legale TEXT DEFAULT '',
    source TEXT DEFAULT 'urssaf.fr',
    date_maj TIMESTAMPTZ DEFAULT now(),
    UNIQUE(annee, type_plafond)
);

-- Textes reglementaires (conservation historique)
CREATE TABLE IF NOT EXISTS ua_reglementation (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reference TEXT NOT NULL, -- ex: CSS art. L241-1
    titre TEXT NOT NULL,
    domaine TEXT DEFAULT '', -- cotisations, tva, travail, etc.
    annee_effet INTEGER NOT NULL,
    date_publication DATE,
    date_effet DATE,
    resume TEXT DEFAULT '',
    texte_complet TEXT DEFAULT '',
    url TEXT DEFAULT '',
    source TEXT DEFAULT 'legifrance.gouv.fr',
    impact TEXT DEFAULT '',
    date_maj TIMESTAMPTZ DEFAULT now(),
    UNIQUE(reference, annee_effet)
);

-- Journal des patches mensuels
CREATE TABLE IF NOT EXISTS ua_patches_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    annee INTEGER NOT NULL,
    mois INTEGER NOT NULL,
    date_execution TIMESTAMPTZ DEFAULT now(),
    source TEXT DEFAULT '',
    nb_baremes INTEGER DEFAULT 0,
    nb_plafonds INTEGER DEFAULT 0,
    nb_reglements INTEGER DEFAULT 0,
    statut TEXT DEFAULT 'pending',
    erreurs TEXT DEFAULT '',
    details JSONB DEFAULT '{}'
);

-- Veille : alertes
CREATE TABLE IF NOT EXISTS ua_alertes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profil_id UUID REFERENCES ua_profils(id),
    entreprise_id UUID REFERENCES ua_entreprises(id),
    titre TEXT NOT NULL,
    description TEXT DEFAULT '',
    severite TEXT DEFAULT 'info',
    type_alerte TEXT DEFAULT '', -- reglementaire, echeance, anomalie
    lue BOOLEAN DEFAULT false,
    traitee BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now(),
    date_traitement TIMESTAMPTZ
);

-- Veille : textes juridiques suivis (equivalent de veille_textes SQLite)
CREATE TABLE IF NOT EXISTS ua_veille_textes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT NOT NULL,
    reference TEXT NOT NULL,
    titre TEXT NOT NULL,
    resume TEXT DEFAULT '',
    url TEXT DEFAULT '',
    date_publication DATE,
    date_effet DATE,
    annee_reference INTEGER,
    categorie TEXT DEFAULT '',
    impact TEXT DEFAULT '',
    texte_complet TEXT DEFAULT '',
    actif BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- ==============================================
-- INDEX
-- ==============================================

CREATE INDEX IF NOT EXISTS idx_ua_entreprises_siret ON ua_entreprises(siret);
CREATE INDEX IF NOT EXISTS idx_ua_entreprises_siren ON ua_entreprises(siren);
CREATE INDEX IF NOT EXISTS idx_ua_portefeuille_profil ON ua_portefeuille(profil_id);
CREATE INDEX IF NOT EXISTS idx_ua_analyses_entreprise ON ua_analyses(entreprise_id);
CREATE INDEX IF NOT EXISTS idx_ua_analyses_profil ON ua_analyses(profil_id);
CREATE INDEX IF NOT EXISTS idx_ua_analyses_date ON ua_analyses(created_at);
CREATE INDEX IF NOT EXISTS idx_ua_baremes_annee ON ua_baremes_historique(annee);
CREATE INDEX IF NOT EXISTS idx_ua_plafonds_annee ON ua_plafonds_historique(annee);
CREATE INDEX IF NOT EXISTS idx_ua_reglementation_annee ON ua_reglementation(annee_effet);
CREATE INDEX IF NOT EXISTS idx_ua_alertes_profil ON ua_alertes(profil_id);
CREATE INDEX IF NOT EXISTS idx_ua_independants_profil ON ua_profils_independants(profil_id);
CREATE INDEX IF NOT EXISTS idx_ua_veille_textes_annee ON ua_veille_textes(annee_reference);

-- ==============================================
-- RLS (Row Level Security)
-- ==============================================

ALTER TABLE ua_profils ENABLE ROW LEVEL SECURITY;
ALTER TABLE ua_entreprises ENABLE ROW LEVEL SECURITY;
ALTER TABLE ua_portefeuille ENABLE ROW LEVEL SECURITY;
ALTER TABLE ua_profils_independants ENABLE ROW LEVEL SECURITY;
ALTER TABLE ua_analyses ENABLE ROW LEVEL SECURITY;
ALTER TABLE ua_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE ua_alertes ENABLE ROW LEVEL SECURITY;
ALTER TABLE ua_veille_textes ENABLE ROW LEVEL SECURITY;

-- Les baremes/plafonds/reglementation sont publics en lecture
ALTER TABLE ua_baremes_historique ENABLE ROW LEVEL SECURITY;
ALTER TABLE ua_plafonds_historique ENABLE ROW LEVEL SECURITY;
ALTER TABLE ua_reglementation ENABLE ROW LEVEL SECURITY;

-- Policies lecture publique pour les donnees reglementaires
CREATE POLICY IF NOT EXISTS "baremes_public_read" ON ua_baremes_historique FOR SELECT USING (true);
CREATE POLICY IF NOT EXISTS "plafonds_public_read" ON ua_plafonds_historique FOR SELECT USING (true);
CREATE POLICY IF NOT EXISTS "reglementation_public_read" ON ua_reglementation FOR SELECT USING (true);
CREATE POLICY IF NOT EXISTS "veille_textes_public_read" ON ua_veille_textes FOR SELECT USING (true);
"""


def generer_donnees_patch_mensuel(annee: int, mois: int) -> dict:
    """Genere les donnees de patch mensuel depuis les constantes locales.

    Utilise les baremes pre-charges dans le code pour alimenter Supabase.
    Cela permet une initialisation meme sans acces aux APIs externes.
    """
    from urssaf_analyzer.config.constants import (
        PASS_ANNUEL, PASS_MENSUEL, PASS_JOURNALIER, PASS_HORAIRE,
        SMIC_HORAIRE_BRUT, SMIC_MENSUEL_BRUT, SMIC_ANNUEL_BRUT,
        TAUX_COTISATIONS_2026, ContributionType,
    )
    from urssaf_analyzer.veille.urssaf_client import BAREMES_PAR_ANNEE

    baremes = []
    for ct, taux_info in TAUX_COTISATIONS_2026.items():
        bareme = {
            "type_cotisation": ct.value,
            "code_ctp": "",
            "libelle": ct.value.replace("_", " ").capitalize(),
            "taux_patronal": float(taux_info.get("patronal", taux_info.get("patronal_moyen", 0)) or 0),
            "taux_salarial": float(taux_info.get("salarial", taux_info.get("taux", 0)) or 0),
            "assiette": taux_info.get("assiette", ""),
            "reference_legale": taux_info.get("ref", ""),
            "notes": taux_info.get("note", ""),
            "source": "urssaf.fr / boss.gouv.fr",
        }
        baremes.append(bareme)

    plafonds = [
        {"type_plafond": "PASS", "valeur_annuelle": float(PASS_ANNUEL),
         "valeur_mensuelle": float(PASS_MENSUEL), "valeur_journaliere": float(PASS_JOURNALIER),
         "valeur_horaire": float(PASS_HORAIRE), "reference_legale": "CSS art. D242-17"},
        {"type_plafond": "SMIC", "valeur_annuelle": float(SMIC_ANNUEL_BRUT),
         "valeur_mensuelle": float(SMIC_MENSUEL_BRUT), "valeur_horaire": float(SMIC_HORAIRE_BRUT),
         "reference_legale": "Decret SMIC 2026"},
    ]

    # Ajouter baremes des annees anterieures si disponibles
    for annee_b, data_b in BAREMES_PAR_ANNEE.items():
        if annee_b != annee:
            for cle, valeur in data_b.items():
                baremes.append({
                    "annee": annee_b,
                    "type_cotisation": cle,
                    "taux_patronal": float(valeur) if isinstance(valeur, (Decimal, float, int)) else 0,
                    "source": "urssaf.fr (pre-charge)",
                })

    return {
        "baremes": baremes,
        "plafonds": plafonds,
        "reglementation": [],
        "source": f"urssaf_analyzer v2.1 - patch {annee}-{mois:02d}",
    }
