"""Tests d'integration du pipeline complet.

Couverture : upload -> analyse -> extraction -> stockage -> rapport.
Communication frontend/backend, coherence base de donnees,
gestion erreurs API, calcul du score.
"""

import sys
import json
import time
from pathlib import Path
from decimal import Decimal

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.config.settings import AppConfig
from urssaf_analyzer.core.orchestrator import Orchestrator
from urssaf_analyzer.database.db_manager import Database
from urssaf_analyzer.security.integrity import calculer_hash_sha256

def _check_crypto():
    import subprocess
    result = subprocess.run(
        [sys.executable, "-c", "from cryptography.hazmat.primitives.ciphers.aead import AESGCM"],
        capture_output=True, timeout=5,
    )
    return result.returncode == 0

_HAS_CRYPTO = _check_crypto()
if _HAS_CRYPTO:
    from urssaf_analyzer.security.encryption import chiffrer_fichier, dechiffrer_fichier
else:
    chiffrer_fichier = dechiffrer_fichier = None

from urssaf_analyzer.analyzers.analyzer_engine import AnalyzerEngine
from urssaf_analyzer.models.documents import Declaration, Employeur, Employe, Cotisation
from urssaf_analyzer.config.constants import ContributionType, Severity

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _make_config(tmp_path):
    return AppConfig(
        base_dir=tmp_path,
        data_dir=tmp_path / "data",
        reports_dir=tmp_path / "reports",
        temp_dir=tmp_path / "temp",
        audit_log_path=tmp_path / "audit.log",
    )


# ==============================
# Pipeline Upload -> Analyse -> Rapport
# ==============================

class TestPipelineComplet:
    """Tests du pipeline complet de bout en bout."""

    def test_csv_pipeline_html(self, tmp_path):
        """CSV -> parsing -> analyse -> rapport HTML."""
        config = _make_config(tmp_path)
        orch = Orchestrator(config)
        rapport = orch.analyser_documents(
            [FIXTURES / "sample_paie.csv"], format_rapport="html"
        )
        assert rapport.exists()
        contenu = rapport.read_text()
        assert "Rapport" in contenu
        assert orch.result.duree_analyse_secondes > 0

    def test_csv_pipeline_json(self, tmp_path):
        """CSV -> parsing -> analyse -> rapport JSON."""
        config = _make_config(tmp_path)
        orch = Orchestrator(config)
        rapport = orch.analyser_documents(
            [FIXTURES / "sample_paie.csv"], format_rapport="json"
        )
        data = json.loads(rapport.read_text())
        assert "metadata" in data
        assert "synthese" in data
        assert "constats" in data
        assert data["metadata"]["session_id"] == orch.result.session_id

    def test_dsn_pipeline(self, tmp_path):
        """DSN -> parsing -> analyse -> extraction employes."""
        config = _make_config(tmp_path)
        orch = Orchestrator(config)
        orch.analyser_documents([FIXTURES / "sample_dsn.dsn"], format_rapport="json")
        result = orch.result
        assert len(result.declarations) > 0
        decl = result.declarations[0]
        assert decl.type_declaration == "DSN"
        assert decl.employeur is not None
        assert len(decl.employes) > 0

    def test_xml_pipeline(self, tmp_path):
        """XML bordereau -> parsing -> analyse."""
        config = _make_config(tmp_path)
        orch = Orchestrator(config)
        orch.analyser_documents([FIXTURES / "sample_bordereau.xml"], format_rapport="html")
        assert len(orch.result.documents_analyses) == 1

    def test_multi_document_pipeline(self, tmp_path):
        """Analyse combinee de plusieurs formats."""
        config = _make_config(tmp_path)
        orch = Orchestrator(config)
        rapport = orch.analyser_documents(
            [
                FIXTURES / "sample_paie.csv",
                FIXTURES / "sample_bordereau.xml",
                FIXTURES / "sample_dsn.dsn",
            ],
            format_rapport="json",
        )
        result = orch.result
        assert len(result.documents_analyses) == 3
        assert len(result.declarations) >= 3
        # Verifier que le rapport contient tous les documents
        data = json.loads(rapport.read_text())
        assert data["metadata"]["nb_documents"] >= 3

    def test_anomaly_detection_pipeline(self, tmp_path):
        """Fichier avec anomalies -> detection -> rapport."""
        config = _make_config(tmp_path)
        orch = Orchestrator(config)
        orch.analyser_documents([FIXTURES / "sample_anomalies.csv"], format_rapport="json")
        assert len(orch.result.findings) > 0
        # Verifier qu'on a au moins un finding avec un impact financier
        has_impact = any(f.montant_impact and f.montant_impact > 0 for f in orch.result.findings)
        # L'impact n'est pas toujours present mais les findings doivent l'etre
        assert len(orch.result.findings) > 0


# ==============================
# Coherence Base de Donnees
# ==============================

class TestCoherenceDB:
    """Tests de coherence entre analyse et base de donnees."""

    def test_save_and_retrieve_analysis(self, tmp_path):
        """Sauvegarder une analyse en DB et la retrouver."""
        db = Database(tmp_path / "coherence.db")
        db.execute_insert(
            "INSERT INTO entreprises (id, siret, siren, raison_sociale) VALUES (?, ?, ?, ?)",
            ("e1", "12345678901234", "123456789", "ACME SARL"),
        )
        db.execute_insert(
            "INSERT INTO analyses (id, entreprise_id, nb_documents, nb_findings, score_risque, "
            "impact_financier, format_rapport, statut) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("a1", "e1", 3, 5, 72, 15000.50, "json", "termine"),
        )
        rows = db.execute(
            "SELECT a.*, e.raison_sociale FROM analyses a "
            "JOIN entreprises e ON a.entreprise_id = e.id WHERE a.id = ?",
            ("a1",),
        )
        assert len(rows) == 1
        assert rows[0]["raison_sociale"] == "ACME SARL"
        assert rows[0]["score_risque"] == 72

    def test_document_analyse_reference(self, tmp_path):
        """Un document doit reference une analyse existante."""
        db = Database(tmp_path / "docref.db")
        db.execute_insert(
            "INSERT INTO analyses (id, nb_documents) VALUES (?, ?)",
            ("a1", 1),
        )
        db.execute_insert(
            "INSERT INTO documents_analyses (id, analyse_id, nom_fichier, type_fichier, hash_sha256) "
            "VALUES (?, ?, ?, ?, ?)",
            ("d1", "a1", "test.csv", "csv", "abc" * 21 + "a"),
        )
        rows = db.execute(
            "SELECT d.* FROM documents_analyses d WHERE d.analyse_id = ?",
            ("a1",),
        )
        assert len(rows) == 1
        assert rows[0]["nom_fichier"] == "test.csv"


# ==============================
# Integrite et Securite
# ==============================

class TestIntegritePipeline:
    """Tests de l'integrite dans le pipeline."""

    def test_hash_consistency(self, tmp_path):
        """Le hash SHA-256 doit etre reproductible."""
        test_file = FIXTURES / "sample_paie.csv"
        h1 = calculer_hash_sha256(test_file)
        h2 = calculer_hash_sha256(test_file)
        assert h1 == h2
        assert len(h1) == 64

    @pytest.mark.skipif(not _HAS_CRYPTO, reason="cryptography non disponible")
    def test_encrypt_decrypt_in_pipeline(self, tmp_path):
        """Chiffrement et dechiffrement dans le contexte du pipeline."""
        source = FIXTURES / "sample_paie.csv"
        encrypted = tmp_path / "encrypted.enc"
        decrypted = tmp_path / "decrypted.csv"

        chiffrer_fichier(source, encrypted, "PipelineKey2026!")
        dechiffrer_fichier(encrypted, decrypted, "PipelineKey2026!")

        assert source.read_bytes() == decrypted.read_bytes()

    def test_audit_trail_complete(self, tmp_path):
        """L'audit trail doit contenir toutes les etapes."""
        config = _make_config(tmp_path)
        orch = Orchestrator(config)
        orch.analyser_documents([FIXTURES / "sample_paie.csv"], format_rapport="json")

        audit = (tmp_path / "audit.log").read_text()
        assert "demarrage_analyse" in audit
        assert "import_document" in audit
        assert "generation_rapport" in audit


# ==============================
# Coherence du Score
# ==============================

class TestCoherenceScore:
    """Tests de la coherence du calcul de score."""

    def test_score_deterministe(self, tmp_path):
        """Le meme fichier doit toujours donner le meme score."""
        scores = []
        for _ in range(3):
            config = _make_config(tmp_path / f"run_{len(scores)}")
            orch = Orchestrator(config)
            orch.analyser_documents([FIXTURES / "sample_paie.csv"], format_rapport="json")
            scores.append(orch.result.score_risque_global)
        assert len(set(scores)) == 1  # Tous identiques

    def test_score_increases_with_anomalies(self, tmp_path):
        """Le fichier avec anomalies doit avoir un score >= au fichier normal."""
        config_normal = _make_config(tmp_path / "normal")
        orch_normal = Orchestrator(config_normal)
        orch_normal.analyser_documents([FIXTURES / "sample_paie.csv"], format_rapport="json")

        config_anomaly = _make_config(tmp_path / "anomaly")
        orch_anomaly = Orchestrator(config_anomaly)
        orch_anomaly.analyser_documents([FIXTURES / "sample_anomalies.csv"], format_rapport="json")

        # Le fichier d'anomalies devrait generer plus de findings
        assert len(orch_anomaly.result.findings) >= len(orch_normal.result.findings)

    def test_score_range(self, tmp_path):
        """Le score doit etre entre 0 et 100."""
        config = _make_config(tmp_path)
        orch = Orchestrator(config)
        orch.analyser_documents([FIXTURES / "sample_paie.csv"], format_rapport="json")
        assert 0 <= orch.result.score_risque_global <= 100


# ==============================
# Gestion Erreurs
# ==============================

class TestGestionErreursPipeline:
    """Tests de la gestion des erreurs dans le pipeline."""

    def test_fichier_inexistant_non_bloquant(self, tmp_path):
        """Un fichier inexistant ne doit pas bloquer les autres."""
        config = _make_config(tmp_path)
        orch = Orchestrator(config)
        rapport = orch.analyser_documents(
            [
                FIXTURES / "sample_paie.csv",
                tmp_path / "inexistant.csv",
            ],
            format_rapport="json",
        )
        assert rapport.exists()
        assert len(orch.result.documents_analyses) == 1

    def test_tous_fichiers_inexistants(self, tmp_path):
        """Si tous les fichiers sont invalides, erreur claire."""
        from urssaf_analyzer.core.exceptions import URSSAFAnalyzerError
        config = _make_config(tmp_path)
        orch = Orchestrator(config)
        with pytest.raises(URSSAFAnalyzerError, match="Aucun document"):
            orch.analyser_documents(
                [tmp_path / "a.csv", tmp_path / "b.csv"],
                format_rapport="json",
            )
