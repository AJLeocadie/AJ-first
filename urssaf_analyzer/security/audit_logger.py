"""Journal d'audit immutable pour tracer toutes les operations."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("urssaf_analyzer.audit")


class AuditLogger:
    """Journalise toutes les operations de maniere immutable (append-only)."""

    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        operation: str,
        session_id: str,
        *,
        details: Optional[dict] = None,
        fichier: Optional[str] = None,
        hash_fichier: Optional[str] = None,
        resultat: str = "succes",
    ) -> None:
        """Ajoute une entree au journal d'audit."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "session_id": session_id,
            "operation": operation,
            "resultat": resultat,
        }
        if fichier:
            entry["fichier"] = fichier
        if hash_fichier:
            entry["hash_fichier"] = hash_fichier
        if details:
            entry["details"] = details

        line = json.dumps(entry, ensure_ascii=False)
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as e:
            logger.error("Impossible d'ecrire dans le journal d'audit: %s", e)

    def log_import(self, session_id: str, fichier: str, hash_fichier: str) -> None:
        self.log("import_document", session_id, fichier=fichier, hash_fichier=hash_fichier)

    def log_analyse(self, session_id: str, analyseur: str, nb_findings: int) -> None:
        self.log(
            "analyse",
            session_id,
            details={"analyseur": analyseur, "nb_findings": nb_findings},
        )

    def log_rapport(self, session_id: str, format_rapport: str, chemin: str) -> None:
        self.log(
            "generation_rapport",
            session_id,
            details={"format": format_rapport, "chemin": chemin},
        )

    def log_chiffrement(self, session_id: str, fichier: str, operation: str) -> None:
        self.log(f"chiffrement_{operation}", session_id, fichier=fichier)

    def log_erreur(self, session_id: str, operation: str, erreur: str) -> None:
        self.log(operation, session_id, details={"erreur": erreur}, resultat="echec")

    def lire_journal(self) -> list[dict]:
        """Lit toutes les entrees du journal."""
        if not self.log_path.exists():
            return []
        entries = []
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries
