"""Tests du module de securite."""

import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.security.integrity import (
    calculer_hash_sha256, verifier_hash, creer_manifeste,
)
from urssaf_analyzer.security.audit_logger import AuditLogger
from urssaf_analyzer.security.secure_storage import (
    suppression_securisee, verifier_taille_fichier,
)


class TestIntegrity:
    """Tests de verification d'integrite."""

    def test_hash_sha256(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Hello World")
        h = calculer_hash_sha256(f)
        assert len(h) == 64  # SHA-256 = 64 hex chars
        assert h == calculer_hash_sha256(f)  # Deterministe

    def test_verifier_hash_valide(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Test data")
        h = calculer_hash_sha256(f)
        assert verifier_hash(f, h) is True

    def test_verifier_hash_invalide(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Test data")
        assert verifier_hash(f, "fakehash") is False

    def test_creer_manifeste(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("AAA")
        f2.write_text("BBB")
        manifeste = creer_manifeste([f1, f2])
        assert len(manifeste) == 2
        assert str(f1) in manifeste

    def test_hash_fichiers_differents(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("AAA")
        f2.write_text("BBB")
        assert calculer_hash_sha256(f1) != calculer_hash_sha256(f2)


class TestAuditLogger:
    """Tests du journal d'audit."""

    def test_log_et_lecture(self, tmp_path):
        log_path = tmp_path / "audit.log"
        audit = AuditLogger(log_path)

        audit.log("test_op", "session123", details={"key": "value"})
        entries = audit.lire_journal()
        assert len(entries) == 1
        assert entries[0]["operation"] == "test_op"
        assert entries[0]["session_id"] == "session123"

    def test_log_import(self, tmp_path):
        log_path = tmp_path / "audit.log"
        audit = AuditLogger(log_path)
        audit.log_import("s1", "/path/to/file.csv", "abc123")
        entries = audit.lire_journal()
        assert entries[0]["operation"] == "import_document"
        assert entries[0]["hash_fichier"] == "abc123"

    def test_log_erreur(self, tmp_path):
        log_path = tmp_path / "audit.log"
        audit = AuditLogger(log_path)
        audit.log_erreur("s1", "parsing", "fichier corrompu")
        entries = audit.lire_journal()
        assert entries[0]["resultat"] == "echec"

    def test_append_only(self, tmp_path):
        log_path = tmp_path / "audit.log"
        audit = AuditLogger(log_path)
        audit.log("op1", "s1")
        audit.log("op2", "s1")
        audit.log("op3", "s1")
        entries = audit.lire_journal()
        assert len(entries) == 3

    def test_journal_vide(self, tmp_path):
        log_path = tmp_path / "audit.log"
        audit = AuditLogger(log_path)
        entries = audit.lire_journal()
        assert entries == []


class TestSecureStorage:
    """Tests du stockage securise."""

    def test_suppression_securisee(self, tmp_path):
        f = tmp_path / "secret.txt"
        f.write_text("Donnees sensibles" * 100)
        assert f.exists()
        suppression_securisee(f, passes=1)
        assert not f.exists()

    def test_suppression_fichier_inexistant(self, tmp_path):
        f = tmp_path / "nonexistent.txt"
        # Ne doit pas lever d'exception
        suppression_securisee(f)

    def test_verifier_taille_ok(self, tmp_path):
        f = tmp_path / "small.txt"
        f.write_text("petit fichier")
        # Ne doit pas lever d'exception
        verifier_taille_fichier(f, max_mb=1)

    def test_verifier_taille_trop_grand(self, tmp_path):
        f = tmp_path / "big.bin"
        # Creer un fichier de 2MB
        f.write_bytes(b"x" * (2 * 1024 * 1024))
        import pytest
        from urssaf_analyzer.core.exceptions import SecurityError
        with pytest.raises(SecurityError):
            verifier_taille_fichier(f, max_mb=1)
