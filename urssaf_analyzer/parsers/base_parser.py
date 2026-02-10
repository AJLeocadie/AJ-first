"""Classe de base abstraite pour tous les parseurs de documents."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from urssaf_analyzer.models.documents import Document, Declaration


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
