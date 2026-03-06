"""Tests exhaustifs de l'orchestrateur d'analyse.

Couverture : workflow complet, import documents, gestion erreurs,
formats non supportes, nettoyage.
"""

import sys
from pathlib import Path
from decimal import Decimal

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.core.orchestrator import Orchestrator
from urssaf_analyzer.core.exceptions import URSSAFAnalyzerError
from urssaf_analyzer.config.settings import AppConfig


FIXTURES = Path(__file__).parent.parent / "fixtures"


def _make_config(tmp_path):
    return AppConfig(
        base_dir=tmp_path,
        data_dir=tmp_path / "data",
        reports_dir=tmp_path / "reports",
        temp_dir=tmp_path / "temp",
        audit_log_path=tmp_path / "audit.log",
    )


class TestOrchestratorInit:
    """Tests d'initialisation de l'orchestrateur."""

    def test_default_init(self, tmp_path):
        config = _make_config(tmp_path)
        orch = Orchestrator(config)
        assert orch.config is config
        assert orch.parser_factory is not None
        assert orch.report_generator is not None
        assert orch.result is not None

    def test_result_has_session_id(self, tmp_path):
        orch = Orchestrator(_make_config(tmp_path))
        assert orch.result.session_id is not None
        assert len(orch.result.session_id) > 0


class TestOrchestratorImport:
    """Tests de l'import de documents."""

    def test_import_csv(self, tmp_path):
        config = _make_config(tmp_path)
        orch = Orchestrator(config)
        doc = orch._importer_document(FIXTURES / "sample_paie.csv", "test-session")
        assert doc.nom_fichier == "sample_paie.csv"
        assert doc.hash_sha256 != ""
        assert len(doc.hash_sha256) == 64
        assert doc.taille_octets > 0

    def test_import_xml(self, tmp_path):
        config = _make_config(tmp_path)
        orch = Orchestrator(config)
        doc = orch._importer_document(FIXTURES / "sample_bordereau.xml", "test-session")
        assert doc.nom_fichier == "sample_bordereau.xml"

    def test_import_dsn(self, tmp_path):
        config = _make_config(tmp_path)
        orch = Orchestrator(config)
        doc = orch._importer_document(FIXTURES / "sample_dsn.dsn", "test-session")
        assert doc.nom_fichier == "sample_dsn.dsn"

    def test_import_fichier_inexistant(self, tmp_path):
        config = _make_config(tmp_path)
        orch = Orchestrator(config)
        with pytest.raises(URSSAFAnalyzerError, match="introuvable"):
            orch._importer_document(tmp_path / "inexistant.csv", "test-session")

    def test_import_format_non_supporte(self, tmp_path):
        config = _make_config(tmp_path)
        orch = Orchestrator(config)
        bad_file = tmp_path / "test.xyz"
        bad_file.write_text("contenu")
        with pytest.raises(URSSAFAnalyzerError, match="non supporte"):
            orch._importer_document(bad_file, "test-session")


class TestOrchestratorAnalyse:
    """Tests de l'analyse complete."""

    def test_analyse_csv_html(self, tmp_path):
        config = _make_config(tmp_path)
        orch = Orchestrator(config)
        rapport = orch.analyser_documents(
            [FIXTURES / "sample_paie.csv"], format_rapport="html"
        )
        assert rapport.exists()
        assert rapport.suffix == ".html"
        assert orch.result.duree_analyse_secondes > 0

    def test_analyse_csv_json(self, tmp_path):
        import json
        config = _make_config(tmp_path)
        orch = Orchestrator(config)
        rapport = orch.analyser_documents(
            [FIXTURES / "sample_paie.csv"], format_rapport="json"
        )
        assert rapport.exists()
        data = json.loads(rapport.read_text())
        assert "metadata" in data
        assert "synthese" in data

    def test_analyse_multi_documents(self, tmp_path):
        config = _make_config(tmp_path)
        orch = Orchestrator(config)
        rapport = orch.analyser_documents(
            [
                FIXTURES / "sample_paie.csv",
                FIXTURES / "sample_bordereau.xml",
                FIXTURES / "sample_dsn.dsn",
            ],
            format_rapport="html",
        )
        assert rapport.exists()
        assert len(orch.result.documents_analyses) == 3

    def test_analyse_aucun_document_valide(self, tmp_path):
        config = _make_config(tmp_path)
        orch = Orchestrator(config)
        with pytest.raises(URSSAFAnalyzerError, match="Aucun document"):
            orch.analyser_documents([tmp_path / "inexistant.csv"])

    def test_analyse_detecte_anomalies(self, tmp_path):
        config = _make_config(tmp_path)
        orch = Orchestrator(config)
        orch.analyser_documents(
            [FIXTURES / "sample_anomalies.csv"], format_rapport="json"
        )
        assert len(orch.result.findings) > 0

    def test_audit_trail_genere(self, tmp_path):
        config = _make_config(tmp_path)
        orch = Orchestrator(config)
        orch.analyser_documents([FIXTURES / "sample_paie.csv"], format_rapport="json")
        audit_path = tmp_path / "audit.log"
        assert audit_path.exists()
        contenu = audit_path.read_text()
        assert "demarrage_analyse" in contenu
        assert "import_document" in contenu

    def test_hash_integrite_calcule(self, tmp_path):
        config = _make_config(tmp_path)
        orch = Orchestrator(config)
        orch.analyser_documents([FIXTURES / "sample_paie.csv"])
        for doc in orch.result.documents_analyses:
            assert len(doc.hash_sha256) == 64

    def test_nettoyage(self, tmp_path):
        config = _make_config(tmp_path)
        orch = Orchestrator(config)
        # Le nettoyage ne doit pas lever d'erreur meme sans fichiers temp
        orch.nettoyer()
