"""Etat partage de l'application NormaCheck.

Centralise toutes les variables d'etat (stores, singletons, configuration)
pour eviter les imports circulaires entre modules de routes.
"""

import contextvars
import logging
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures
from urssaf_analyzer.comptabilite.plan_comptable import PlanComptable
from urssaf_analyzer.database.db_manager import Database
from urssaf_analyzer.security.proof_chain import ProofChain

from auth import get_optional_user

logger = logging.getLogger("normacheck")

# --- Contexte de la requete courante pour tracabilite multi-utilisateur ---
_current_request: contextvars.ContextVar[Optional["Request"]] = contextvars.ContextVar(
    "_current_request", default=None
)

# --- Detection environnement ---
IS_OVH = os.getenv("NORMACHECK_ENV") in ("production", "development", "staging")
DATA_DIR = Path(os.getenv("NORMACHECK_DATA_DIR", "/data/normacheck")) if IS_OVH else Path("/tmp/normacheck_data")
PROOF_DIR = DATA_DIR / "proof"
PROOF_DIR.mkdir(parents=True, exist_ok=True)
proof_chain = ProofChain(PROOF_DIR / "score_proof_chain.jsonl")
MAX_FILES = int(os.getenv("NORMACHECK_MAX_FILES", "50" if IS_OVH else "20"))
MAX_UPLOAD_MB = int(os.getenv("NORMACHECK_MAX_UPLOAD_MB", "2000" if IS_OVH else "500"))
MAX_FILE_MB = int(os.getenv("NORMACHECK_MAX_FILE_MB", "50"))

# --- Tarification ---
PRICING = {
    "solo":    {"prix_mensuel": 59.99,   "profils": 1,  "label": "Solo"},
    "equipe":  {"prix_mensuel": 119.99,  "profils": 3,  "label": "Equipe"},
    "cabinet": {"prix_mensuel": 249.99,  "profils": 10, "label": "Cabinet"},
}

# --- Retention RGPD ---
RETENTION_UPLOADS_DAYS = int(os.getenv("NORMACHECK_RETENTION_UPLOADS_DAYS", "90"))
RETENTION_AUDIT_DAYS = int(os.getenv("NORMACHECK_RETENTION_AUDIT_DAYS", "1825"))

# --- Persistence ---
persist = None
_persistence_stores = {}

if IS_OVH:
    try:
        from persistence import (
            knowledge_store, doc_library_store, audit_log_store,
            rh_contrats_store, rh_avenants_store, rh_conges_store,
            rh_arrets_store, rh_sanctions_store, rh_attestations_store,
            rh_entretiens_store, rh_visites_med_store, rh_echanges_store,
            rh_planning_store, dsn_drafts_store, invitations_store,
            facture_statuses_store, entete_config_store,
            save_uploaded_file, save_report, get_data_stats,
            log_action as persistent_log_action,
        )
        persist = True
        _persistence_stores = {
            "knowledge": knowledge_store,
            "doc_library": doc_library_store,
            "audit_log": audit_log_store,
            "rh_contrats": rh_contrats_store,
            "rh_avenants": rh_avenants_store,
            "rh_conges": rh_conges_store,
            "rh_arrets": rh_arrets_store,
            "rh_sanctions": rh_sanctions_store,
            "rh_attestations": rh_attestations_store,
            "rh_entretiens": rh_entretiens_store,
            "rh_visites_med": rh_visites_med_store,
            "rh_echanges": rh_echanges_store,
            "rh_planning": rh_planning_store,
            "dsn_drafts": dsn_drafts_store,
            "invitations": invitations_store,
            "facture_statuses": facture_statuses_store,
            "entete_config": entete_config_store,
        }
    except ImportError:
        persist = False

# --- Donnees par defaut knowledge base ---
DEFAULT_KB = {
    "salaries": {},
    "employeurs": {},
    "cotisations": [],
    "declarations_dsn": [],
    "bulletins_paie": [],
    "documents_comptables": [],
    "taux_verifies": {},
    "periodes_couvertes": [],
    "anomalies_detectees": [],
    "pieces_justificatives": {},
    "contrats_detectes": [],
    "masse_salariale": {},
    "masse_salariale_totale": 0,
    "effectifs": {},
    "conventions_collectives": [],
    "exonerations_detectees": [],
    "derniere_maj": None,
    "contexte_entreprise": {
        "secteur_activite": "",
        "code_naf": "",
        "convention_collective": "",
        "code_idcc": "",
        "lieu_implantation": "",
        "forme_juridique": "",
        "effectif_moyen": 0,
        "accords_entreprise": [],
        "regime_fiscal": "",
    },
    "documents_par_type": {},
    "alertes_contextuelles": [],
}

# --- Stores (initialisation) ---
if persist:
    doc_library = doc_library_store.load()
    biblio_knowledge = knowledge_store.load()
    for k, v in DEFAULT_KB.items():
        if k not in biblio_knowledge:
            biblio_knowledge[k] = v
    invitations = invitations_store.load()
    facture_statuses = facture_statuses_store.load()
    audit_log = audit_log_store.load()
    dsn_drafts = dsn_drafts_store.load()
    rh_contrats = rh_contrats_store.load()
    rh_avenants = rh_avenants_store.load()
    rh_conges = rh_conges_store.load()
    rh_arrets = rh_arrets_store.load()
    rh_sanctions = rh_sanctions_store.load()
    rh_attestations = rh_attestations_store.load()
    rh_entretiens = rh_entretiens_store.load()
    rh_visites_med = rh_visites_med_store.load()
    rh_echanges = rh_echanges_store.load()
    rh_planning = rh_planning_store.load()
    entete_config = entete_config_store.load()
else:
    doc_library: list[dict] = []
    biblio_knowledge: dict = dict(DEFAULT_KB)
    invitations: list[dict] = []
    facture_statuses: dict[str, dict] = {}
    audit_log: list[dict] = []
    dsn_drafts: list[dict] = []
    rh_contrats: list[dict] = []
    rh_avenants: list[dict] = []
    rh_conges: list[dict] = []
    rh_arrets: list[dict] = []
    rh_sanctions: list[dict] = []
    rh_attestations: list[dict] = []
    rh_entretiens: list[dict] = []
    rh_visites_med: list[dict] = []
    rh_echanges: list[dict] = []
    rh_planning: list[dict] = []
    entete_config: dict = {}

# --- Singletons ---
_db: Optional[Database] = None
_moteur: Optional[MoteurEcritures] = None

# --- Etat additionnel (initialise au niveau module) ---
alertes_config: list[dict] = []
alertes_libres: list[dict] = []
planning_creneau_defaut: dict = {}
sous_comptes: list[dict] = []

# --- Rate limiting ---
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = int(os.getenv("NORMACHECK_RATE_LIMIT", "60"))
RATE_LIMIT_AUTH_MAX = 10
rate_store: dict[str, list[float]] = {}

# --- Pagination ---
DEFAULT_PAGE_LIMIT = 200


def get_db() -> Database:
    global _db
    if _db is None:
        db_path = str(DATA_DIR / "db" / "normacheck.db") if IS_OVH else "/tmp/urssaf_analyzer.db"
        _db = Database(db_path)
    return _db


def get_moteur() -> MoteurEcritures:
    global _moteur
    if _moteur is None:
        _moteur = MoteurEcritures(PlanComptable())
    return _moteur


def paginate(items: list, offset: int = 0, limit: int = DEFAULT_PAGE_LIMIT) -> dict:
    """Pagine une liste avec offset/limit et retourne total + items."""
    total = len(items)
    limit = min(limit, 500)
    page = items[offset:offset + limit]
    return {"total": total, "offset": offset, "limit": limit, "items": page}


def log_action(profil_email: str, action: str, details: str = "", user_override: dict = None):
    """Enregistre une action dans le journal d'audit avec tracabilite multi-utilisateur."""
    resolved_email = profil_email
    tenant_id = ""
    if user_override:
        if resolved_email == "utilisateur":
            resolved_email = user_override.get("email", profil_email)
        tenant_id = user_override.get("tenant_id", "")
    else:
        req = _current_request.get(None)
        if req is not None:
            try:
                u = get_optional_user(req)
                if u:
                    if resolved_email == "utilisateur":
                        resolved_email = u.get("email", profil_email)
                    tenant_id = u.get("tenant_id", "")
            except Exception:
                pass
    entry = {
        "id": str(uuid.uuid4())[:8],
        "date": datetime.now().isoformat(),
        "profil": resolved_email,
        "action": action,
        "details": details,
        "tenant_id": tenant_id,
    }
    audit_log.append(entry)
    if persist:
        from persistence import audit_log_store
        audit_log_store.append(entry)


def save_state():
    """Persiste l'etat complet sur disque (OVHcloud uniquement)."""
    if not persist:
        return
    from persistence import (
        knowledge_store, doc_library_store, audit_log_store,
        rh_contrats_store, rh_avenants_store, rh_conges_store,
        rh_arrets_store, rh_sanctions_store, rh_attestations_store,
        rh_entretiens_store, rh_visites_med_store, rh_echanges_store,
        rh_planning_store, dsn_drafts_store, invitations_store,
        facture_statuses_store, entete_config_store,
    )
    knowledge_store.save(biblio_knowledge)
    doc_library_store.save(doc_library)
    audit_log_store.save(audit_log)
    rh_contrats_store.save(rh_contrats)
    rh_avenants_store.save(rh_avenants)
    rh_conges_store.save(rh_conges)
    rh_arrets_store.save(rh_arrets)
    rh_sanctions_store.save(rh_sanctions)
    rh_attestations_store.save(rh_attestations)
    rh_entretiens_store.save(rh_entretiens)
    rh_visites_med_store.save(rh_visites_med)
    rh_echanges_store.save(rh_echanges)
    rh_planning_store.save(rh_planning)
    dsn_drafts_store.save(dsn_drafts)
    invitations_store.save(invitations)
    facture_statuses_store.save(facture_statuses)
    entete_config_store.save(entete_config)


async def safe_json(request):
    """Parse le body JSON avec gestion d'erreur propre."""
    from fastapi import HTTPException
    try:
        return await request.json()
    except Exception:
        raise HTTPException(400, "Corps de la requete invalide (JSON attendu)")


def get_client_ip(request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(key: str, max_requests: int) -> bool:
    """Retourne True si la requete est autorisee, False si rate limited."""
    now = time.time()
    timestamps = rate_store.get(key, [])
    timestamps = [t for t in timestamps if now - t < RATE_LIMIT_WINDOW]
    if len(timestamps) >= max_requests:
        rate_store[key] = timestamps
        return False
    timestamps.append(now)
    rate_store[key] = timestamps
    return True
