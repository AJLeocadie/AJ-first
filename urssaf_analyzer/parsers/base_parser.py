"""Classe de base abstraite pour tous les parseurs de documents."""

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from urssaf_analyzer.core.exceptions import ParseError
from urssaf_analyzer.models.documents import Document, Declaration

logger = logging.getLogger(__name__)

# Limite de taille par defaut pour les fichiers texte (100 Mo)
_MAX_TEXT_FILE_BYTES = 100 * 1024 * 1024
# Limite du nombre de lignes pour eviter les DoS
_MAX_LINES = 500_000


class BaseParser(ABC):
    """Interface commune pour tous les parseurs."""

    @abstractmethod
    def peut_traiter(self, chemin: Path) -> bool:
        """Verifie si ce parseur peut traiter le fichier donne."""

    @abstractmethod
    def parser(self, chemin: Path, document: Document) -> list[Declaration]:
        """Parse le fichier et retourne les declarations extraites."""

    @abstractmethod
    def extraire_metadata(self, chemin: Path) -> dict[str, Any]:
        """Extrait les metadonnees du fichier."""

    def _verifier_taille_fichier(self, chemin: Path, max_bytes: int = _MAX_TEXT_FILE_BYTES) -> None:
        """Verifie que le fichier ne depasse pas la taille maximale."""
        try:
            taille = chemin.stat().st_size
        except OSError as e:
            raise ParseError(f"Impossible de lire le fichier {chemin}: {e}") from e
        if taille > max_bytes:
            raise ParseError(
                f"Fichier trop volumineux ({taille / 1024 / 1024:.1f} Mo). "
                f"Limite : {max_bytes / 1024 / 1024:.0f} Mo."
            )
        if taille == 0:
            raise ParseError(f"Le fichier {chemin.name} est vide.")

    @staticmethod
    def _sanitize_string(value: str, max_length: int = 500) -> str:
        """Nettoie et tronque une chaine pour eviter les injections et debordements."""
        if not value:
            return ""
        # Retirer les caracteres de controle (sauf newline et tab)
        cleaned = "".join(
            c for c in value
            if c in ("\n", "\t", "\r") or (ord(c) >= 32)
        )
        return cleaned[:max_length].strip()
