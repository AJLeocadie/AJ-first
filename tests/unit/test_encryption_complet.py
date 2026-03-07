"""Tests exhaustifs du module de chiffrement.

Couverture : AES-256-GCM, PBKDF2, chiffrement fichiers/donnees/champs,
masquage, formats v1/v2, cas d'erreur.
Niveau : bancaire (ISO 27001, RGPD art. 32).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import subprocess
_crypto_check = subprocess.run(
    [sys.executable, "-c", "from cryptography.hazmat.primitives.ciphers.aead import AESGCM"],
    capture_output=True, timeout=5,
)
_HAS_CRYPTO = _crypto_check.returncode == 0

if _HAS_CRYPTO:
    from urssaf_analyzer.security.encryption import (
        chiffrer_fichier, dechiffrer_fichier,
        chiffrer_donnees, dechiffrer_donnees,
        chiffrer_champ, dechiffrer_champ,
        est_chiffre, masquer_champ,
        HEADER_MAGIC, FORMAT_VERSION,
        SALT_LENGTH, IV_LENGTH, KEY_LENGTH, ITERATIONS,
    )
from urssaf_analyzer.core.exceptions import EncryptionError

pytestmark = pytest.mark.skipif(not _HAS_CRYPTO, reason="cryptography non disponible")


# ==============================
# Constants
# ==============================

class TestEncryptionConstants:
    """Verifie les constantes de securite."""

    def test_salt_length(self):
        assert SALT_LENGTH == 32

    def test_iv_length(self):
        assert IV_LENGTH == 12  # 96 bits pour GCM (NIST SP 800-38D)

    def test_key_length(self):
        assert KEY_LENGTH == 32  # 256 bits

    def test_iterations(self):
        assert ITERATIONS >= 310_000  # OWASP 2024+

    def test_format_version(self):
        assert FORMAT_VERSION == 2


# ==============================
# File Encryption
# ==============================

class TestFileEncryption:
    """Tests du chiffrement/dechiffrement de fichiers."""

    def test_encrypt_decrypt_roundtrip(self, tmp_path):
        source = tmp_path / "plain.txt"
        source.write_text("Donnees sensibles RGPD", encoding="utf-8")
        encrypted = tmp_path / "encrypted.enc"
        decrypted = tmp_path / "decrypted.txt"

        chiffrer_fichier(source, encrypted, "MotDePasse123!")
        dechiffrer_fichier(encrypted, decrypted, "MotDePasse123!")

        assert decrypted.read_text(encoding="utf-8") == "Donnees sensibles RGPD"

    def test_encrypted_file_has_magic(self, tmp_path):
        source = tmp_path / "test.txt"
        source.write_text("test", encoding="utf-8")
        encrypted = tmp_path / "test.enc"

        chiffrer_fichier(source, encrypted, "password")

        with open(encrypted, "rb") as f:
            magic = f.read(len(HEADER_MAGIC))
        assert magic == HEADER_MAGIC

    def test_wrong_password_fails(self, tmp_path):
        source = tmp_path / "test.txt"
        source.write_text("secret", encoding="utf-8")
        encrypted = tmp_path / "test.enc"
        decrypted = tmp_path / "result.txt"

        chiffrer_fichier(source, encrypted, "correct_password")
        with pytest.raises(EncryptionError):
            dechiffrer_fichier(encrypted, decrypted, "wrong_password")

    def test_invalid_format_fails(self, tmp_path):
        bad_file = tmp_path / "bad.enc"
        bad_file.write_bytes(b"not an encrypted file")
        decrypted = tmp_path / "result.txt"

        with pytest.raises(EncryptionError, match="invalide"):
            dechiffrer_fichier(bad_file, decrypted, "password")

    def test_empty_file(self, tmp_path):
        source = tmp_path / "empty.txt"
        source.write_text("", encoding="utf-8")
        encrypted = tmp_path / "empty.enc"
        decrypted = tmp_path / "empty_result.txt"

        chiffrer_fichier(source, encrypted, "password")
        dechiffrer_fichier(encrypted, decrypted, "password")

        assert decrypted.read_text() == ""

    def test_large_file(self, tmp_path):
        source = tmp_path / "large.txt"
        content = "X" * (1024 * 1024)  # 1 MB
        source.write_text(content)
        encrypted = tmp_path / "large.enc"
        decrypted = tmp_path / "large_result.txt"

        chiffrer_fichier(source, encrypted, "password")
        dechiffrer_fichier(encrypted, decrypted, "password")

        assert decrypted.read_text() == content

    def test_binary_file(self, tmp_path):
        source = tmp_path / "binary.bin"
        data = bytes(range(256)) * 100
        source.write_bytes(data)
        encrypted = tmp_path / "binary.enc"
        decrypted = tmp_path / "binary_result.bin"

        chiffrer_fichier(source, encrypted, "password")
        dechiffrer_fichier(encrypted, decrypted, "password")

        assert decrypted.read_bytes() == data

    def test_different_passwords_different_output(self, tmp_path):
        source = tmp_path / "test.txt"
        source.write_text("same content")
        enc1 = tmp_path / "enc1.enc"
        enc2 = tmp_path / "enc2.enc"

        chiffrer_fichier(source, enc1, "password1")
        chiffrer_fichier(source, enc2, "password2")

        assert enc1.read_bytes() != enc2.read_bytes()

    def test_same_password_different_output(self, tmp_path):
        """Chaque chiffrement doit produire un resultat different (sel aleatoire)."""
        source = tmp_path / "test.txt"
        source.write_text("same content")
        enc1 = tmp_path / "enc1.enc"
        enc2 = tmp_path / "enc2.enc"

        chiffrer_fichier(source, enc1, "same_password")
        chiffrer_fichier(source, enc2, "same_password")

        assert enc1.read_bytes() != enc2.read_bytes()


# ==============================
# Data Encryption (in-memory)
# ==============================

class TestDataEncryption:
    """Tests du chiffrement en memoire."""

    def test_encrypt_decrypt_roundtrip(self):
        data = b"Donnees sensibles NIR: 1850175123456"
        encrypted = chiffrer_donnees(data, "password")
        decrypted = dechiffrer_donnees(encrypted, "password")
        assert decrypted == data

    def test_encrypt_with_context(self):
        data = b"IBAN: FR7612345678901234"
        encrypted = chiffrer_donnees(data, "password", contexte="iban_field")
        decrypted = dechiffrer_donnees(encrypted, "password", contexte="iban_field")
        assert decrypted == data

    def test_empty_data(self):
        encrypted = chiffrer_donnees(b"", "password")
        decrypted = dechiffrer_donnees(encrypted, "password")
        assert decrypted == b""

    def test_wrong_password(self):
        encrypted = chiffrer_donnees(b"secret", "correct")
        with pytest.raises(Exception):
            dechiffrer_donnees(encrypted, "wrong")

    def test_invalid_data(self):
        with pytest.raises(EncryptionError):
            dechiffrer_donnees(b"invalid data", "password")


# ==============================
# Field Encryption
# ==============================

class TestFieldEncryption:
    """Tests du chiffrement de champs individuels."""

    def test_encrypt_decrypt_field(self):
        nir = "1850175123456"
        encrypted = chiffrer_champ(nir, "key123")
        assert encrypted.startswith("ENC:")
        decrypted = dechiffrer_champ(encrypted, "key123")
        assert decrypted == nir

    def test_empty_field(self):
        assert chiffrer_champ("", "key") == ""
        assert dechiffrer_champ("", "key") == ""

    def test_empty_password(self):
        assert chiffrer_champ("test", "") == "test"
        assert dechiffrer_champ("test", "") == "test"

    def test_non_encrypted_field(self):
        assert dechiffrer_champ("plain text", "key") == "plain text"

    def test_est_chiffre(self):
        assert est_chiffre("ENC:abc123") is True
        assert est_chiffre("plain text") is False
        assert est_chiffre("") is False
        assert est_chiffre(None) is False

    def test_iban_roundtrip(self):
        iban = "FR7630006000011234567890189"
        encrypted = chiffrer_champ(iban, "banking_key")
        assert est_chiffre(encrypted)
        decrypted = dechiffrer_champ(encrypted, "banking_key")
        assert decrypted == iban


# ==============================
# Field Masking
# ==============================

class TestFieldMasking:
    """Tests du masquage de champs sensibles."""

    def test_mask_nir(self):
        result = masquer_champ("1850175123456")
        assert result == "****3456"
        assert "1850175" not in result

    def test_mask_iban(self):
        result = masquer_champ("FR7612345678901234")
        assert result == "****1234"

    def test_mask_short_value(self):
        assert masquer_champ("abc") == "abc"  # Trop court pour masquer
        assert masquer_champ("") == ""

    def test_mask_custom_visible(self):
        result = masquer_champ("1234567890", nb_visible=6)
        assert result == "****567890"

    def test_mask_exact_length(self):
        assert masquer_champ("abcd", nb_visible=4) == "abcd"
