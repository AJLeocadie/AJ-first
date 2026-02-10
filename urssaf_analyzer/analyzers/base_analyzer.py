"""Classe de base pour tous les analyseurs."""

from abc import ABC, abstractmethod

from urssaf_analyzer.models.documents import Declaration, Finding


class BaseAnalyzer(ABC):
    """Interface commune pour les analyseurs."""

    @property
    @abstractmethod
    def nom(self) -> str:
        """Nom de l'analyseur."""

    @abstractmethod
    def analyser(self, declarations: list[Declaration]) -> list[Finding]:
        """Analyse les declarations et retourne les constats."""
