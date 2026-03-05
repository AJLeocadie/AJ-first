"""
NormaCheck - Module de persistance OVHcloud
Remplace les stores in-memory par des fichiers JSON persistants.
Compatible multi-worker Gunicorn via file locking.
"""
import json
import os
import fcntl
import time
import shutil
from pathlib import Path
from datetime import datetime
from typing import Any


DATA_DIR = Path(os.getenv("NORMACHECK_DATA_DIR", "/data/normacheck"))
DB_DIR = DATA_DIR / "db"
UPLOADS_DIR = DATA_DIR / "uploads"
REPORTS_DIR = DATA_DIR / "reports"
LOGS_DIR = DATA_DIR / "logs"


def _ensure_dirs():
    """Cree les repertoires persistants si absents."""
    for d in [DB_DIR, UPLOADS_DIR, REPORTS_DIR, LOGS_DIR, DATA_DIR / "temp", DATA_DIR / "encrypted", DATA_DIR / "backups"]:
        d.mkdir(parents=True, exist_ok=True)


_ensure_dirs()


class PersistentStore:
    """Store JSON persistant avec file locking pour multi-worker."""

    def __init__(self, name: str, default: Any = None):
        self.path = DB_DIR / f"{name}.json"
        self.lock_path = DB_DIR / f"{name}.lock"
        self.name = name
        self._default = default if default is not None else {}
        if not self.path.exists():
            self._write(self._default)

    def _read(self) -> Any:
        """Lecture thread-safe avec lock partage."""
        try:
            with open(self.lock_path, "a+") as lf:
                fcntl.flock(lf, fcntl.LOCK_SH)
                try:
                    with open(self.path, "r", encoding="utf-8") as f:
                        return json.load(f)
                finally:
                    fcntl.flock(lf, fcntl.LOCK_UN)
        except (FileNotFoundError, json.JSONDecodeError):
            return self._default

    def _write(self, data: Any):
        """Ecriture atomique avec lock exclusif."""
        tmp_path = self.path.with_suffix(".tmp")
        with open(self.lock_path, "a+") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, default=str)
                os.replace(str(tmp_path), str(self.path))
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)

    def load(self) -> Any:
        return self._read()

    def save(self, data: Any):
        self._write(data)

    def update(self, updater_fn):
        """Lecture-modification-ecriture atomique."""
        with open(self.lock_path, "a+") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                try:
                    with open(self.path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except (FileNotFoundError, json.JSONDecodeError):
                    data = self._default
                result = updater_fn(data)
                tmp_path = self.path.with_suffix(".tmp")
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, default=str)
                os.replace(str(tmp_path), str(self.path))
                return result
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)


class PersistentList:
    """Liste persistante (wraps PersistentStore avec interface list-like)."""

    def __init__(self, name: str):
        self._store = PersistentStore(name, default=[])

    def load(self) -> list:
        return self._store.load()

    def append(self, item: dict):
        def _append(data):
            data.append(item)
        self._store.update(_append)

    def save(self, data: list):
        self._store.save(data)

    def __len__(self):
        return len(self.load())

    def __iter__(self):
        return iter(self.load())

    def __bool__(self):
        return len(self.load()) > 0


# --- Stores persistants ---
# Remplacent les variables globales in-memory de api/index.py

knowledge_store = PersistentStore("biblio_knowledge", default={
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
})

doc_library_store = PersistentList("doc_library")
audit_log_store = PersistentList("audit_log")
rh_contrats_store = PersistentList("rh_contrats")
rh_avenants_store = PersistentList("rh_avenants")
rh_conges_store = PersistentList("rh_conges")
rh_arrets_store = PersistentList("rh_arrets")
rh_sanctions_store = PersistentList("rh_sanctions")
rh_attestations_store = PersistentList("rh_attestations")
rh_entretiens_store = PersistentList("rh_entretiens")
rh_visites_med_store = PersistentList("rh_visites_med")
rh_echanges_store = PersistentList("rh_echanges")
rh_planning_store = PersistentList("rh_planning")
dsn_drafts_store = PersistentList("dsn_drafts")
invitations_store = PersistentList("invitations")
facture_statuses_store = PersistentStore("facture_statuses", default={})
entete_config_store = PersistentStore("entete_config", default={})


def save_uploaded_file(filename: str, content: bytes, analysis_id: str = "") -> Path:
    """Sauvegarde un fichier uploade sur disque persistant."""
    date_dir = UPLOADS_DIR / datetime.now().strftime("%Y-%m")
    if analysis_id:
        date_dir = date_dir / analysis_id
    date_dir.mkdir(parents=True, exist_ok=True)
    dest = date_dir / filename
    dest.write_bytes(content)
    return dest


def save_report(report_id: str, content: str, fmt: str = "html") -> Path:
    """Sauvegarde un rapport genere."""
    dest = REPORTS_DIR / f"{report_id}.{fmt}"
    dest.write_text(content, encoding="utf-8")
    return dest


def log_action(profil: str, action: str, details: str = ""):
    """Log persistant des actions pour conformite."""
    audit_log_store.append({
        "id": os.urandom(4).hex(),
        "date": datetime.now().isoformat(),
        "profil": profil,
        "action": action,
        "details": details,
    })


def get_data_stats() -> dict:
    """Statistiques sur les donnees persistantes."""
    kb = knowledge_store.load()
    return {
        "db_size_mb": round(sum(f.stat().st_size for f in DB_DIR.glob("*.json")) / 1048576, 2),
        "uploads_count": sum(1 for _ in UPLOADS_DIR.rglob("*") if _.is_file()),
        "uploads_size_mb": round(sum(f.stat().st_size for f in UPLOADS_DIR.rglob("*") if f.is_file()) / 1048576, 2),
        "reports_count": sum(1 for _ in REPORTS_DIR.glob("*")),
        "salaries_count": len(kb.get("salaries", {})),
        "documents_count": len(doc_library_store.load()),
        "contrats_rh_count": len(rh_contrats_store.load()),
        "derniere_maj": kb.get("derniere_maj"),
    }
