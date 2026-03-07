"""Tests du module base_analyzer (classe abstraite)."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.analyzers.base_analyzer import BaseAnalyzer
from urssaf_analyzer.models.documents import Declaration, Finding


class ConcreteAnalyzer(BaseAnalyzer):
    """Implementation concrete pour tester l'interface abstraite."""

    @property
    def nom(self) -> str:
        return "test_analyzer"

    def analyser(self, declarations: list[Declaration]) -> list[Finding]:
        return [
            Finding(
                categorie="test",
                severite="info",
                titre="Test finding",
                description="Constat de test",
            )
            for _ in declarations
        ]


class TestBaseAnalyzer:
    """Tests de l'interface BaseAnalyzer."""

    def test_nom_property(self):
        analyzer = ConcreteAnalyzer()
        assert analyzer.nom == "test_analyzer"

    def test_analyser_retourne_findings(self):
        analyzer = ConcreteAnalyzer()
        decl = Declaration(type_declaration="test", reference="REF001")
        findings = analyzer.analyser([decl])
        assert len(findings) == 1
        assert findings[0].titre == "Test finding"

    def test_analyser_vide(self):
        analyzer = ConcreteAnalyzer()
        findings = analyzer.analyser([])
        assert findings == []

    def test_cannot_instantiate_abstract(self):
        import pytest
        with pytest.raises(TypeError):
            BaseAnalyzer()

    def test_analyser_multiple_declarations(self):
        analyzer = ConcreteAnalyzer()
        decls = [
            Declaration(type_declaration="test", reference=f"REF{i}")
            for i in range(5)
        ]
        findings = analyzer.analyser(decls)
        assert len(findings) == 5
