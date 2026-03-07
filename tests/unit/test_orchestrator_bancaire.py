"""Tests unitaires de l'orchestrateur d'analyse.

Couverture niveau bancaire : workflow complet, gestion d'erreurs, securite.
"""

import pytest
import tempfile
from pathlib import Path
from decimal import Decimal
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestOrchestratorImport:
    """Tests d'import de documents par l'orchestrateur."""

    @pytest.fixture
    def orchestrator(self, app_config):
        from urssaf_analyzer.core.orchestrator import Orchestrator
        return Orchestrator(config=app_config)

    def test_import_fichier_inexistant(self, orchestrator):
        from urssaf_analyzer.core.exceptions import URSSAFAnalyzerError
        with pytest.raises(URSSAFAnalyzerError, match="introuvable"):
            orchestrator._importer_document(Path("/nonexistent.csv"), "session-1")

    def test_import_format_non_supporte(self, orchestrator, tmp_path):
        from urssaf_analyzer.core.exceptions import URSSAFAnalyzerError
        f = tmp_path / "test.xyz"
        f.write_text("content")
        with pytest.raises(URSSAFAnalyzerError, match="non supporte"):
            orchestrator._importer_document(f, "session-1")

    def test_import_csv_valide(self, orchestrator, sample_csv_file):
        doc = orchestrator._importer_document(sample_csv_file, "session-1")
        assert doc.nom_fichier == sample_csv_file.name
        assert doc.hash_sha256 != ""
        assert doc.taille_octets > 0

    def test_import_genere_hash_sha256(self, orchestrator, sample_csv_file):
        doc = orchestrator._importer_document(sample_csv_file, "session-1")
        assert len(doc.hash_sha256) == 64
        # Hash reproductible
        doc2 = orchestrator._importer_document(sample_csv_file, "session-2")
        assert doc.hash_sha256 == doc2.hash_sha256


class TestOrchestratorAnalyse:
    """Tests du workflow d'analyse complet."""

    @pytest.fixture
    def orchestrator(self, app_config):
        from urssaf_analyzer.core.orchestrator import Orchestrator
        return Orchestrator(config=app_config)

    def test_aucun_document_importe(self, orchestrator):
        from urssaf_analyzer.core.exceptions import URSSAFAnalyzerError
        with pytest.raises(URSSAFAnalyzerError, match="Aucun document"):
            orchestrator.analyser_documents([Path("/nonexistent.csv")])

    def test_analyse_csv_complete(self, orchestrator, sample_csv_file):
        rapport = orchestrator.analyser_documents([sample_csv_file])
        assert rapport.exists()
        assert rapport.suffix == ".html"

    def test_analyse_format_json(self, orchestrator, sample_csv_file):
        rapport = orchestrator.analyser_documents([sample_csv_file], format_rapport="json")
        assert rapport.exists()
        assert rapport.suffix == ".json"

    def test_analyse_avec_anomalies(self, orchestrator, sample_anomaly_csv):
        rapport = orchestrator.analyser_documents([sample_anomaly_csv])
        assert rapport.exists()
        # Les anomalies doivent etre detectees
        assert len(orchestrator.result.findings) > 0

    def test_analyse_result_populated(self, orchestrator, sample_csv_file):
        orchestrator.analyser_documents([sample_csv_file])
        result = orchestrator.result
        assert result.session_id is not None
        assert result.duree_analyse_secondes > 0
        assert len(result.documents_analyses) == 1


class TestOrchestratorNettoyage:
    """Tests du nettoyage securise."""

    def test_nettoyer_sans_erreur(self, app_config):
        from urssaf_analyzer.core.orchestrator import Orchestrator
        orch = Orchestrator(config=app_config)
        # Ne doit pas lever d'exception
        orch.nettoyer()
