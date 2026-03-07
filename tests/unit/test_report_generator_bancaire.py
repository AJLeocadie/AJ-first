"""Tests unitaires du generateur de rapports.

Couverture niveau bancaire : HTML, JSON, recommandations.
"""

import json
import pytest
from decimal import Decimal
from datetime import datetime
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.reporting.report_generator import ReportGenerator
from urssaf_analyzer.models.documents import (
    AnalysisResult, Document, Finding, FileType,
)
from urssaf_analyzer.config.constants import Severity, FindingCategory


@pytest.fixture
def generator():
    return ReportGenerator()


@pytest.fixture
def sample_result():
    return AnalysisResult(
        documents_analyses=[
            Document(nom_fichier="test.csv", type_fichier=FileType.CSV,
                     hash_sha256="a" * 64, taille_octets=1024),
        ],
        findings=[
            Finding(
                categorie=FindingCategory.ANOMALIE,
                severite=Severity.CRITIQUE,
                titre="Taux maladie incorrect",
                description="Le taux patronal maladie est de 10% au lieu de 7%",
                montant_impact=Decimal("500"),
                score_risque=85,
                recommandation="Corriger le taux maladie",
                detecte_par="AnomalyDetector",
                reference_legale="CSS art. L241-2",
            ),
            Finding(
                categorie=FindingCategory.INCOHERENCE,
                severite=Severity.MOYENNE,
                titre="Ecart masse salariale",
                description="La masse salariale ne correspond pas",
                montant_impact=Decimal("200"),
                score_risque=50,
                recommandation="Verifier les calculs",
                detecte_par="ConsistencyChecker",
            ),
        ],
        duree_analyse_secondes=2.5,
    )


# ================================================================
# RAPPORT HTML
# ================================================================

class TestRapportHTML:

    def test_generer_html(self, generator, sample_result, tmp_path):
        output = tmp_path / "rapport.html"
        generator.generer_html(sample_result, output)
        assert output.exists()
        content = output.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content

    def test_html_contains_score(self, generator, sample_result, tmp_path):
        output = tmp_path / "rapport.html"
        generator.generer_html(sample_result, output)
        content = output.read_text(encoding="utf-8")
        assert "Score de Risque Global" in content or "score" in content.lower()

    def test_html_contains_findings(self, generator, sample_result, tmp_path):
        output = tmp_path / "rapport.html"
        generator.generer_html(sample_result, output)
        content = output.read_text(encoding="utf-8")
        assert "Taux maladie incorrect" in content

    def test_html_contains_recommendations(self, generator, sample_result, tmp_path):
        output = tmp_path / "rapport.html"
        generator.generer_html(sample_result, output)
        content = output.read_text(encoding="utf-8")
        assert "Recommandation" in content or "recommandation" in content.lower()

    def test_html_contains_documents(self, generator, sample_result, tmp_path):
        output = tmp_path / "rapport.html"
        generator.generer_html(sample_result, output)
        content = output.read_text(encoding="utf-8")
        assert "test.csv" in content

    def test_html_empty_findings(self, generator, tmp_path):
        result = AnalysisResult()
        output = tmp_path / "rapport.html"
        generator.generer_html(result, output)
        assert output.exists()

    def test_html_confidentiality_notice(self, generator, sample_result, tmp_path):
        output = tmp_path / "rapport.html"
        generator.generer_html(sample_result, output)
        content = output.read_text(encoding="utf-8")
        assert "CONFIDENTIEL" in content


# ================================================================
# RAPPORT JSON
# ================================================================

class TestRapportJSON:

    def test_generer_json(self, generator, sample_result, tmp_path):
        output = tmp_path / "rapport.json"
        generator.generer_json(sample_result, output)
        assert output.exists()
        data = json.loads(output.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_json_structure(self, generator, sample_result, tmp_path):
        output = tmp_path / "rapport.json"
        generator.generer_json(sample_result, output)
        data = json.loads(output.read_text(encoding="utf-8"))
        assert "metadata" in data
        assert "synthese" in data
        assert "documents_analyses" in data
        assert "constats" in data
        assert "recommandations" in data

    def test_json_metadata(self, generator, sample_result, tmp_path):
        output = tmp_path / "rapport.json"
        generator.generer_json(sample_result, output)
        data = json.loads(output.read_text(encoding="utf-8"))
        meta = data["metadata"]
        assert "session_id" in meta
        assert "date_analyse" in meta
        assert meta["nb_documents"] == 1

    def test_json_synthese(self, generator, sample_result, tmp_path):
        output = tmp_path / "rapport.json"
        generator.generer_json(sample_result, output)
        data = json.loads(output.read_text(encoding="utf-8"))
        synthese = data["synthese"]
        assert synthese["nb_constats"] == 2
        assert synthese["nb_critiques"] == 1

    def test_json_constats_detail(self, generator, sample_result, tmp_path):
        output = tmp_path / "rapport.json"
        generator.generer_json(sample_result, output)
        data = json.loads(output.read_text(encoding="utf-8"))
        constats = data["constats"]
        assert len(constats) == 2
        assert constats[0]["titre"] == "Taux maladie incorrect"


# ================================================================
# RECOMMANDATIONS
# ================================================================

class TestRecommandations:

    def test_recommandations_generated(self, generator, sample_result):
        recos = generator._generer_recommandations(sample_result.findings)
        assert len(recos) > 0

    def test_recommandations_sorted_by_score(self, generator, sample_result):
        recos = generator._generer_recommandations(sample_result.findings)
        if len(recos) >= 2:
            assert recos[0]["score"] >= recos[1]["score"]

    def test_recommandations_max_15(self, generator):
        findings = [
            Finding(
                titre=f"Anomalie {i}",
                recommandation=f"Corriger anomalie {i}",
                score_risque=i,
            )
            for i in range(20)
        ]
        recos = generator._generer_recommandations(findings)
        assert len(recos) <= 15

    def test_compter_par_severite(self):
        findings = [
            Finding(severite=Severity.CRITIQUE),
            Finding(severite=Severity.CRITIQUE),
            Finding(severite=Severity.HAUTE),
        ]
        result = ReportGenerator._compter_par_severite(findings)
        assert result["critique"] == 2
        assert result["haute"] == 1
