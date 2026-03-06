"""Tests des modules de securite (integrity, secure_storage)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.security.integrity import (
    calculer_hash_sha256,
    verifier_hash,
    creer_manifeste,
    verifier_manifeste,
    BUFFER_SIZE,
)
from urssaf_analyzer.security.secure_storage import (
    suppression_securisee,
    nettoyer_repertoire_temp,
    verifier_taille_fichier,
    creer_repertoire_session,
)
from urssaf_analyzer.core.exceptions import IntegrityError, SecurityError


# =====================================================
# INTEGRITY
# =====================================================

class TestIntegrity:
    """Tests de verification d'integrite SHA-256."""

    def test_calculer_hash_fichier(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Hello, NormaCheck!")
        h = calculer_hash_sha256(f)
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex digest

    def test_calculer_hash_deterministe(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Same content")
        h1 = calculer_hash_sha256(f)
        h2 = calculer_hash_sha256(f)
        assert h1 == h2

    def test_calculer_hash_different_content(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("content A")
        f2.write_text("content B")
        assert calculer_hash_sha256(f1) != calculer_hash_sha256(f2)

    def test_calculer_hash_fichier_vide(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_bytes(b"")
        h = calculer_hash_sha256(f)
        assert len(h) == 64

    def test_calculer_hash_gros_fichier(self, tmp_path):
        f = tmp_path / "big.bin"
        f.write_bytes(b"x" * (BUFFER_SIZE * 3))
        h = calculer_hash_sha256(f)
        assert len(h) == 64

    def test_calculer_hash_fichier_inexistant(self, tmp_path):
        with pytest.raises(IntegrityError):
            calculer_hash_sha256(tmp_path / "nope.txt")

    def test_verifier_hash_correct(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("verify me")
        h = calculer_hash_sha256(f)
        assert verifier_hash(f, h) is True

    def test_verifier_hash_incorrect(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("verify me")
        assert verifier_hash(f, "0" * 64) is False

    def test_creer_manifeste(self, tmp_path):
        files = []
        for i in range(3):
            f = tmp_path / f"file{i}.txt"
            f.write_text(f"content {i}")
            files.append(f)
        manifeste = creer_manifeste(files)
        assert len(manifeste) == 3
        for path_str, h in manifeste.items():
            assert len(h) == 64

    def test_verifier_manifeste_ok(self, tmp_path):
        files = []
        for i in range(3):
            f = tmp_path / f"file{i}.txt"
            f.write_text(f"content {i}")
            files.append(f)
        manifeste = creer_manifeste(files)
        invalides = verifier_manifeste(manifeste)
        assert invalides == []

    def test_verifier_manifeste_fichier_modifie(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("original")
        manifeste = creer_manifeste([f])
        f.write_text("modified")
        invalides = verifier_manifeste(manifeste)
        assert len(invalides) == 1

    def test_verifier_manifeste_fichier_supprime(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("will be deleted")
        manifeste = creer_manifeste([f])
        f.unlink()
        invalides = verifier_manifeste(manifeste)
        assert len(invalides) == 1


# =====================================================
# SECURE STORAGE
# =====================================================

class TestSecureStorage:
    """Tests du stockage securise."""

    def test_suppression_securisee(self, tmp_path):
        f = tmp_path / "secret.txt"
        f.write_text("sensitive data")
        suppression_securisee(f)
        assert not f.exists()

    def test_suppression_securisee_fichier_inexistant(self, tmp_path):
        # Should not raise
        suppression_securisee(tmp_path / "nope.txt")

    def test_suppression_securisee_directory_raises(self, tmp_path):
        d = tmp_path / "subdir"
        d.mkdir()
        with pytest.raises(SecurityError):
            suppression_securisee(d)

    def test_suppression_securisee_passes(self, tmp_path):
        f = tmp_path / "secret.txt"
        f.write_text("sensitive data " * 100)
        suppression_securisee(f, passes=5)
        assert not f.exists()

    def test_nettoyer_repertoire_temp(self, tmp_path):
        temp = tmp_path / "temp"
        temp.mkdir()
        for i in range(5):
            (temp / f"file{i}.txt").write_text(f"data {i}")
        count = nettoyer_repertoire_temp(temp)
        assert count == 5

    def test_nettoyer_repertoire_temp_vide(self, tmp_path):
        temp = tmp_path / "temp"
        temp.mkdir()
        count = nettoyer_repertoire_temp(temp)
        assert count == 0

    def test_nettoyer_repertoire_temp_inexistant(self, tmp_path):
        count = nettoyer_repertoire_temp(tmp_path / "nope")
        assert count == 0

    def test_nettoyer_repertoire_temp_sous_repertoires(self, tmp_path):
        temp = tmp_path / "temp"
        sub = temp / "sub"
        sub.mkdir(parents=True)
        (sub / "file.txt").write_text("data")
        (temp / "root.txt").write_text("data")
        count = nettoyer_repertoire_temp(temp)
        assert count == 2

    def test_verifier_taille_fichier_ok(self, tmp_path):
        f = tmp_path / "small.txt"
        f.write_text("small")
        verifier_taille_fichier(f, max_mb=100)

    def test_verifier_taille_fichier_trop_gros(self, tmp_path):
        f = tmp_path / "big.bin"
        # Write just over 1MB
        f.write_bytes(b"x" * (1024 * 1024 + 1))
        with pytest.raises(SecurityError):
            verifier_taille_fichier(f, max_mb=1)

    def test_creer_repertoire_session(self, tmp_path):
        session_dir = creer_repertoire_session(tmp_path, "session-123")
        assert session_dir.exists()
        assert session_dir.name == "session-123"

    def test_creer_repertoire_session_idempotent(self, tmp_path):
        d1 = creer_repertoire_session(tmp_path, "sess-1")
        d2 = creer_repertoire_session(tmp_path, "sess-1")
        assert d1 == d2
