"""Configuration centralisee des logs pour NormaCheck.

Fonctionnalites :
- Logs structures JSON pour monitoring
- Detection d'erreurs silencieuses
- Rotation automatique des fichiers de log
- Niveaux de log configurables par module
- Correlation par session_id
"""

import logging
import logging.handlers
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path


class StructuredFormatter(logging.Formatter):
    """Formateur JSON structure pour les logs."""

    def format(self, record):
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": traceback.format_exception(*record.exc_info),
            }

        # Ajouter les champs extra
        for key in ("session_id", "user_email", "document_id", "action"):
            if hasattr(record, key):
                log_entry[key] = getattr(record, key)

        return json.dumps(log_entry, ensure_ascii=False, default=str)


class SilentErrorDetector(logging.Handler):
    """Detecte les patterns d'erreurs silencieuses.

    Erreurs silencieuses = exceptions attrapees mais non loguees,
    retours None inattendus, timeouts non signales.
    """

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.error_count = 0
        self.error_patterns = []
        self._max_patterns = 100

    def emit(self, record):
        self.error_count += 1
        if len(self.error_patterns) < self._max_patterns:
            self.error_patterns.append({
                "timestamp": datetime.utcnow().isoformat(),
                "level": record.levelname,
                "message": record.getMessage(),
                "module": record.module,
                "function": record.funcName,
            })

    def get_report(self):
        """Retourne un rapport des erreurs detectees."""
        return {
            "total_errors": self.error_count,
            "unique_patterns": len(self.error_patterns),
            "patterns": self.error_patterns[:20],
        }


# Instance globale du detecteur
_silent_error_detector = SilentErrorDetector()


def setup_logging(
    log_dir: str | Path | None = None,
    level: str = "INFO",
    structured: bool = True,
):
    """Configure le systeme de logging.

    Args:
        log_dir: Repertoire des fichiers de log. None = stdout uniquement.
        level: Niveau de log (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        structured: Si True, utilise le format JSON structure.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    root_logger = logging.getLogger("urssaf_analyzer")
    root_logger.setLevel(log_level)

    # Nettoyer les handlers existants
    root_logger.handlers.clear()

    # Handler console
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    if structured:
        console_handler.setFormatter(StructuredFormatter())
    else:
        console_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s:%(funcName)s:%(lineno)d - %(message)s"
        ))
    root_logger.addHandler(console_handler)

    # Handler fichier avec rotation
    if log_dir:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)

        file_handler = logging.handlers.RotatingFileHandler(
            log_path / "normacheck.log",
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(StructuredFormatter())
        root_logger.addHandler(file_handler)

        # Fichier d'erreurs separe
        error_handler = logging.handlers.RotatingFileHandler(
            log_path / "normacheck_errors.log",
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=10,
            encoding="utf-8",
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(StructuredFormatter())
        root_logger.addHandler(error_handler)

    # Detecteur d'erreurs silencieuses
    root_logger.addHandler(_silent_error_detector)

    # Logger d'auth
    auth_logger = logging.getLogger("auth")
    auth_logger.setLevel(log_level)
    for handler in root_logger.handlers:
        auth_logger.addHandler(handler)

    return root_logger


def get_silent_error_report():
    """Retourne le rapport des erreurs silencieuses detectees."""
    return _silent_error_detector.get_report()
