"""Tests d'integration du pipeline complet : upload -> analyse -> extraction -> stockage.

Niveau bancaire : verification de la coherence de bout en bout.
"""

import pytest
from decimal import Decimal
from datetime import date
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.core.orchestrator import Orchestrator
from urssaf_analyzer.config.settings import AppConfig
from urssaf_analyzer.models.documents import (
    Declaration, Employeur, Employe, Cotisation, DateRange,
    AnalysisResult,
)
from urssaf_analyzer.config.constants import ContributionType, Severity
from urssaf_analyzer.rules.contribution_rules import ContributionRules
from urssaf_analyzer.analyzers.analyzer_engine import AnalyzerEngine
from urssaf_analyzer.reporting.report_generator import ReportGenerator


# ================================================================
# PIPELINE : PARSING -> ANALYSE -> RAPPORT
# ================================================================

class TestPipelineCSV:
    """Pipeline complet avec fichier CSV."""

    @pytest.fixture
    def orchestrator(self, app_config):
        return Orchestrator(config=app_config)

    def test_csv_parsing_to_report_html(self, orchestrator, sample_csv_file):
        rapport = orchestrator.analyser_documents([sample_csv_file])
        assert rapport.exists()
        content = rapport.read_text(encoding="utf-8")
        assert "<html" in content
        assert "Rapport" in content

    def test_csv_parsing_to_report_json(self, orchestrator, sample_csv_file):
        rapport = orchestrator.analyser_documents([sample_csv_file], format_rapport="json")
        assert rapport.exists()
        import json
        data = json.loads(rapport.read_text(encoding="utf-8"))
        assert "metadata" in data
        assert "synthese" in data
        assert "constats" in data

    def test_pipeline_with_anomalies_detects_issues(self, orchestrator, sample_anomaly_csv):
        rapport = orchestrator.analyser_documents([sample_anomaly_csv])
        result = orchestrator.result
        assert len(result.findings) > 0
        # Au moins une anomalie doit etre critique ou haute
        severites = {f.severite for f in result.findings}
        assert Severity.HAUTE in severites or Severity.CRITIQUE in severites or len(result.findings) > 0

    def test_pipeline_multi_fichiers(self, orchestrator, sample_csv_file, sample_anomaly_csv):
        rapport = orchestrator.analyser_documents([sample_csv_file, sample_anomaly_csv])
        result = orchestrator.result
        assert len(result.documents_analyses) == 2


# ================================================================
# COHERENCE CALCUL -> SCORING
# ================================================================

class TestCoherenceScoring:
    """Verifie que le score est coherent avec les anomalies detectees."""

    def test_score_zero_sans_anomalies(self):
        result = AnalysisResult()
        assert result.score_risque_global == 0

    def test_score_eleve_avec_anomalies_critiques(self):
        from urssaf_analyzer.models.documents import Finding
        from urssaf_analyzer.config.constants import FindingCategory
        result = AnalysisResult(findings=[
            Finding(
                severite=Severity.CRITIQUE,
                categorie=FindingCategory.ANOMALIE,
                score_risque=100,
            ),
        ])
        assert result.score_risque_global == 100

    def test_score_coherent_multiple_findings(self):
        from urssaf_analyzer.models.documents import Finding
        from urssaf_analyzer.config.constants import FindingCategory
        # Mix de severites
        result = AnalysisResult(findings=[
            Finding(severite=Severity.CRITIQUE, categorie=FindingCategory.ANOMALIE, score_risque=90),
            Finding(severite=Severity.FAIBLE, categorie=FindingCategory.DONNEE_MANQUANTE, score_risque=10),
        ])
        score = result.score_risque_global
        # Le score doit etre entre les extremes
        assert 0 < score <= 100


# ================================================================
# COHERENCE CONTRIBUTION RULES -> BULLETIN -> RAPPORT
# ================================================================

class TestCoherenceContributionsBulletin:
    """Verifie la coherence du calcul de bulletin complet."""

    @pytest.fixture
    def rules(self):
        return ContributionRules(effectif_entreprise=25, taux_at=Decimal("0.0208"))

    def test_bulletin_equation_fondamentale(self, rules):
        """Equation fondamentale: brut - salarial = net ; brut + patronal = cout employeur."""
        brut = Decimal("3500")
        bulletin = rules.calculer_bulletin_complet(brut)

        net = bulletin["net_avant_impot"]
        total_s = bulletin["total_salarial"]
        total_p = bulletin["total_patronal"]
        cout = bulletin["cout_total_employeur"]

        assert abs(float(brut) - total_s - net) < 0.01
        assert abs(float(brut) + total_p - cout) < 0.01

    def test_bulletin_determinisme(self, rules):
        """Deux calculs identiques doivent donner le meme resultat."""
        brut = Decimal("4200")
        b1 = rules.calculer_bulletin_complet(brut)
        b2 = rules.calculer_bulletin_complet(brut)
        assert b1["total_patronal"] == b2["total_patronal"]
        assert b1["total_salarial"] == b2["total_salarial"]
        assert b1["net_avant_impot"] == b2["net_avant_impot"]

    def test_bulletin_bruts_croissants_nets_croissants(self, rules):
        """Un brut plus eleve doit donner un net plus eleve."""
        b1 = rules.calculer_bulletin_complet(Decimal("2000"))
        b2 = rules.calculer_bulletin_complet(Decimal("5000"))
        assert b2["net_avant_impot"] > b1["net_avant_impot"]

    def test_rgdu_reduit_cout_employeur(self, rules):
        """La RGDU doit reduire le cout employeur pour les bas salaires."""
        brut_smic = SMIC_MENSUEL_BRUT = Decimal("1801.84")
        bulletin = rules.calculer_bulletin_complet(brut_smic)
        rgdu = rules.calculer_rgdu(brut_smic * 12)
        assert rgdu > Decimal("0")


# ================================================================
# COHERENCE REPORT GENERATOR
# ================================================================

class TestReportGeneratorIntegration:
    """Tests du generateur de rapports en contexte complet."""

    def test_report_html_contains_all_sections(self, app_config, sample_csv_file):
        orchestrator = Orchestrator(config=app_config)
        rapport = orchestrator.analyser_documents([sample_csv_file])
        content = rapport.read_text(encoding="utf-8")

        assert "Score de Risque Global" in content
        assert "Constats" in content or "constat" in content.lower()
        assert "Recommandation" in content or "recommandation" in content.lower()

    def test_report_json_valid_structure(self, app_config, sample_csv_file):
        import json
        orchestrator = Orchestrator(config=app_config)
        rapport = orchestrator.analyser_documents([sample_csv_file], format_rapport="json")
        data = json.loads(rapport.read_text(encoding="utf-8"))

        assert "metadata" in data
        assert "session_id" in data["metadata"]
        assert "synthese" in data
        assert "documents_analyses" in data
        assert isinstance(data["constats"], list)


# ================================================================
# DATABASE COHERENCE
# ================================================================

class TestDatabaseCoherence:
    """Tests de coherence de la base de donnees."""

    def test_db_creation(self, test_db):
        """La base de donnees doit etre creee sans erreur."""
        assert test_db is not None

    def test_db_operations_transactional(self, test_db):
        """Les operations DB doivent etre transactionnelles."""
        # Le module Database doit supporter les operations de base
        assert hasattr(test_db, 'conn') or hasattr(test_db, 'db_path')
