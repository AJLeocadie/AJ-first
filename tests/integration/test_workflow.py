"""Test d'integration du workflow complet d'analyse."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.config.settings import AppConfig
from urssaf_analyzer.core.orchestrator import Orchestrator

FIXTURES = Path(__file__).parent.parent / "fixtures"


class TestWorkflowComplet:
    """Tests du workflow d'analyse de bout en bout."""

    def test_analyse_csv_html(self, tmp_path):
        """Teste l'analyse d'un CSV avec generation de rapport HTML."""
        config = AppConfig(
            base_dir=tmp_path,
            data_dir=tmp_path / "data",
            reports_dir=tmp_path / "reports",
            temp_dir=tmp_path / "temp",
            audit_log_path=tmp_path / "audit.log",
        )
        orchestrator = Orchestrator(config)

        chemin_rapport = orchestrator.analyser_documents(
            [FIXTURES / "sample_paie.csv"],
            format_rapport="html",
        )

        assert chemin_rapport.exists()
        assert chemin_rapport.suffix == ".html"

        contenu = chemin_rapport.read_text()
        assert "Rapport d'Analyse" in contenu
        assert "CONFIDENTIEL" in contenu

        # Verifier le resultat
        result = orchestrator.result
        assert len(result.documents_analyses) == 1
        assert len(result.declarations) > 0

    def test_analyse_csv_json(self, tmp_path):
        """Teste la generation de rapport JSON."""
        config = AppConfig(
            base_dir=tmp_path,
            data_dir=tmp_path / "data",
            reports_dir=tmp_path / "reports",
            temp_dir=tmp_path / "temp",
            audit_log_path=tmp_path / "audit.log",
        )
        orchestrator = Orchestrator(config)

        chemin_rapport = orchestrator.analyser_documents(
            [FIXTURES / "sample_paie.csv"],
            format_rapport="json",
        )

        assert chemin_rapport.exists()
        assert chemin_rapport.suffix == ".json"

        import json
        with open(chemin_rapport) as f:
            data = json.load(f)

        assert "metadata" in data
        assert "synthese" in data
        assert "constats" in data
        assert "recommandations" in data

    def test_analyse_avec_anomalies(self, tmp_path):
        """Teste la detection d'anomalies."""
        config = AppConfig(
            base_dir=tmp_path,
            data_dir=tmp_path / "data",
            reports_dir=tmp_path / "reports",
            temp_dir=tmp_path / "temp",
            audit_log_path=tmp_path / "audit.log",
        )
        orchestrator = Orchestrator(config)

        chemin_rapport = orchestrator.analyser_documents(
            [FIXTURES / "sample_anomalies.csv"],
            format_rapport="json",
        )

        result = orchestrator.result
        # Le fichier d'anomalies contient : base negative, taux incorrect,
        # depassement PASS, erreur de calcul, doublon
        assert len(result.findings) > 0

        # Verifier qu'on detecte bien des anomalies
        categories = {f.categorie.value for f in result.findings}
        assert len(categories) > 0  # Au moins une categorie de findings

    def test_analyse_xml(self, tmp_path):
        """Teste l'analyse d'un bordereau XML."""
        config = AppConfig(
            base_dir=tmp_path,
            data_dir=tmp_path / "data",
            reports_dir=tmp_path / "reports",
            temp_dir=tmp_path / "temp",
            audit_log_path=tmp_path / "audit.log",
        )
        orchestrator = Orchestrator(config)

        chemin_rapport = orchestrator.analyser_documents(
            [FIXTURES / "sample_bordereau.xml"],
            format_rapport="html",
        )

        assert chemin_rapport.exists()
        result = orchestrator.result
        assert len(result.documents_analyses) == 1

    def test_analyse_dsn(self, tmp_path):
        """Teste l'analyse d'un fichier DSN."""
        config = AppConfig(
            base_dir=tmp_path,
            data_dir=tmp_path / "data",
            reports_dir=tmp_path / "reports",
            temp_dir=tmp_path / "temp",
            audit_log_path=tmp_path / "audit.log",
        )
        orchestrator = Orchestrator(config)

        chemin_rapport = orchestrator.analyser_documents(
            [FIXTURES / "sample_dsn.dsn"],
            format_rapport="json",
        )

        assert chemin_rapport.exists()
        result = orchestrator.result
        assert len(result.declarations) > 0

        # Verifier les donnees DSN extraites
        decl = result.declarations[0]
        assert decl.type_declaration == "DSN"
        assert len(decl.employes) == 3
        assert decl.employeur is not None

    def test_analyse_multi_documents(self, tmp_path):
        """Teste l'analyse de plusieurs documents simultanement."""
        config = AppConfig(
            base_dir=tmp_path,
            data_dir=tmp_path / "data",
            reports_dir=tmp_path / "reports",
            temp_dir=tmp_path / "temp",
            audit_log_path=tmp_path / "audit.log",
        )
        orchestrator = Orchestrator(config)

        chemin_rapport = orchestrator.analyser_documents(
            [
                FIXTURES / "sample_paie.csv",
                FIXTURES / "sample_bordereau.xml",
                FIXTURES / "sample_dsn.dsn",
            ],
            format_rapport="html",
        )

        assert chemin_rapport.exists()
        result = orchestrator.result
        assert len(result.documents_analyses) == 3
        assert len(result.declarations) >= 3

    def test_audit_trail(self, tmp_path):
        """Verifie que le journal d'audit est alimente."""
        audit_path = tmp_path / "audit.log"
        config = AppConfig(
            base_dir=tmp_path,
            data_dir=tmp_path / "data",
            reports_dir=tmp_path / "reports",
            temp_dir=tmp_path / "temp",
            audit_log_path=audit_path,
        )
        orchestrator = Orchestrator(config)

        orchestrator.analyser_documents(
            [FIXTURES / "sample_paie.csv"],
            format_rapport="json",
        )

        assert audit_path.exists()
        contenu = audit_path.read_text()
        assert "demarrage_analyse" in contenu
        assert "import_document" in contenu
        assert "generation_rapport" in contenu

    def test_hash_integrite(self, tmp_path):
        """Verifie que les hashes d'integrite sont calcules."""
        config = AppConfig(
            base_dir=tmp_path,
            data_dir=tmp_path / "data",
            reports_dir=tmp_path / "reports",
            temp_dir=tmp_path / "temp",
            audit_log_path=tmp_path / "audit.log",
        )
        orchestrator = Orchestrator(config)

        orchestrator.analyser_documents(
            [FIXTURES / "sample_paie.csv"],
            format_rapport="json",
        )

        result = orchestrator.result
        for doc in result.documents_analyses:
            assert doc.hash_sha256 != ""
            assert len(doc.hash_sha256) == 64
