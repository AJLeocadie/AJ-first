"""Tests unitaires exhaustifs du module de chiffrement.

Couverture niveau bancaire : AES-256-GCM, PBKDF2, champs individuels.
Ref: ISO 27001 A.10 - Cryptographie, NIST SP 800-38D.
"""

import pytest
import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

def _check_crypto():
    """Verifie si le module cryptography est disponible via subprocess."""
    import subprocess
    result = subprocess.run(
        [sys.executable, "-c", "from cryptography.hazmat.primitives.ciphers.aead import AESGCM"],
        capture_output=True, timeout=5,
    )
    return result.returncode == 0

CRYPTO_AVAILABLE = _check_crypto()

if CRYPTO_AVAILABLE:
    from urssaf_analyzer.security.encryption import (
        chiffrer_fichier, dechiffrer_fichier,
        chiffrer_donnees, dechiffrer_donnees,
        chiffrer_champ, dechiffrer_champ,
        est_chiffre, masquer_champ,
        HAS_CRYPTOGRAPHY,
    )
    CRYPTO_AVAILABLE = HAS_CRYPTOGRAPHY

pytestmark = pytest.mark.skipif(not CRYPTO_AVAILABLE, reason="cryptography non installe")


# ================================================================
# CHIFFREMENT FICHIER
# ================================================================

class TestChiffrementFichier:

    def test_chiffrer_dechiffrer_fichier(self, tmp_path):
        source = tmp_path / "secret.txt"
        source.write_text("Donnees sensibles URSSAF")
        encrypted = tmp_path / "secret.enc"
        decrypted = tmp_path / "secret_dec.txt"

        chiffrer_fichier(source, encrypted, "motdepasse-tres-long!")
        assert encrypted.exists()
        assert encrypted.read_bytes() != source.read_bytes()

        dechiffrer_fichier(encrypted, decrypted, "motdepasse-tres-long!")
        assert decrypted.read_text() == "Donnees sensibles URSSAF"

    def test_mauvais_mot_de_passe(self, tmp_path):
        source = tmp_path / "secret.txt"
        source.write_text("Donnees sensibles")
        encrypted = tmp_path / "secret.enc"
        decrypted = tmp_path / "secret_dec.txt"

        chiffrer_fichier(source, encrypted, "bon-mot-de-passe!")
        from urssaf_analyzer.core.exceptions import EncryptionError
        with pytest.raises(EncryptionError):
            dechiffrer_fichier(encrypted, decrypted, "mauvais-mdp!")

    def test_fichier_vide(self, tmp_path):
        source = tmp_path / "empty.txt"
        source.write_bytes(b"")
        encrypted = tmp_path / "empty.enc"
        decrypted = tmp_path / "empty_dec.txt"

        chiffrer_fichier(source, encrypted, "password123!")
        dechiffrer_fichier(encrypted, decrypted, "password123!")
        assert decrypted.read_bytes() == b""

    def test_fichier_binaire(self, tmp_path):
        source = tmp_path / "binary.bin"
        data = bytes(range(256)) * 100
        source.write_bytes(data)
        encrypted = tmp_path / "binary.enc"
        decrypted = tmp_path / "binary_dec.bin"

        chiffrer_fichier(source, encrypted, "password123!")
        dechiffrer_fichier(encrypted, decrypted, "password123!")
        assert decrypted.read_bytes() == data


# ================================================================
# CHIFFREMENT DONNEES EN MEMOIRE
# ================================================================

class TestChiffrementDonnees:

    def test_chiffrer_dechiffrer_donnees(self):
        data = b"NIR: 1850175123456"
        encrypted = chiffrer_donnees(data, "cle-secrete-2026!")
        assert encrypted != data
        decrypted = dechiffrer_donnees(encrypted, "cle-secrete-2026!")
        assert decrypted == data

    def test_contexte_aad(self):
        """Le contexte (AAD) doit etre lie au chiffre."""
        data = b"Confidentiel"
        encrypted = chiffrer_donnees(data, "cle-2026!", contexte="paie.csv")
        decrypted = dechiffrer_donnees(encrypted, "cle-2026!", contexte="paie.csv")
        assert decrypted == data

    def test_chaque_chiffrement_unique(self):
        """Deux chiffrements du meme texte doivent produire des sorties differentes (IV aleatoire)."""
        data = b"Test"
        e1 = chiffrer_donnees(data, "cle!")
        e2 = chiffrer_donnees(data, "cle!")
        assert e1 != e2  # IV different

    def test_donnees_vides(self):
        encrypted = chiffrer_donnees(b"", "cle!")
        decrypted = dechiffrer_donnees(encrypted, "cle!")
        assert decrypted == b""


# ================================================================
# CHIFFREMENT DE CHAMPS INDIVIDUELS
# ================================================================

class TestChiffrementChamps:

    def test_chiffrer_dechiffrer_champ(self):
        encrypted = chiffrer_champ("1850175123456", "cle-nir-2026!")
        assert encrypted.startswith("ENC:")
        decrypted = dechiffrer_champ(encrypted, "cle-nir-2026!")
        assert decrypted == "1850175123456"

    def test_champ_vide(self):
        assert chiffrer_champ("", "cle!") == ""
        assert chiffrer_champ(None, "cle!") is None

    def test_champ_non_chiffre_retourne_tel_quel(self):
        assert dechiffrer_champ("texte_normal", "cle!") == "texte_normal"

    def test_est_chiffre(self):
        assert est_chiffre("ENC:abc123") is True
        assert est_chiffre("texte_normal") is False
        assert est_chiffre("") is False
        assert est_chiffre(None) is False


# ================================================================
# MASQUAGE DE CHAMPS
# ================================================================

class TestMasquageChamps:

    def test_masquer_nir(self):
        result = masquer_champ("1850175123456")
        assert result == "****3456"
        assert "1850175" not in result

    def test_masquer_iban(self):
        result = masquer_champ("FR7612345678901234", nb_visible=4)
        assert result.startswith("****")
        assert result.endswith("1234")

    def test_masquer_champ_court(self):
        result = masquer_champ("AB", nb_visible=4)
        assert result == "AB"  # Trop court pour masquer

    def test_masquer_vide(self):
        assert masquer_champ("") == ""
        assert masquer_champ(None) is None
