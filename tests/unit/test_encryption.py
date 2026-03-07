"""Tests exhaustifs du module de chiffrement (encryption.py).

Couverture cible : 80%+ sur encryption.py
Marqueurs : securite (ISO 27001 A.10)
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.core.exceptions import EncryptionError

# Verifier si cryptography est disponible (subprocess pour eviter pyo3 panic)
import subprocess
_crypto_check = subprocess.run(
    [sys.executable, "-c", "from cryptography.hazmat.primitives.ciphers.aead import AESGCM"],
    capture_output=True, timeout=5,
)
HAS_CRYPTOGRAPHY = _crypto_check.returncode == 0

if HAS_CRYPTOGRAPHY:
    from urssaf_analyzer.security.encryption import (
        chiffrer_fichier,
        dechiffrer_fichier,
        chiffrer_donnees,
        dechiffrer_donnees,
        HEADER_MAGIC,
        SALT_LENGTH,
        IV_LENGTH,
        KEY_LENGTH,
        ITERATIONS,
        _derive_key,
    )

pytestmark = pytest.mark.skipif(
    not HAS_CRYPTOGRAPHY,
    reason="Module 'cryptography' non installe"
)


# ──────────────────────────────────────────────
# Tests constantes
# ──────────────────────────────────────────────

class TestConstantesChiffrement:
    """Tests des constantes de chiffrement."""

    def test_header_magic(self):
        assert HEADER_MAGIC == b"URSAFE01"
        assert len(HEADER_MAGIC) == 8

    def test_salt_length(self):
        """Sel de 32 octets (256 bits) conforme NIST SP 800-132."""
        assert SALT_LENGTH == 32

    def test_iv_length(self):
        """IV de 12 octets (96 bits) recommande pour GCM (NIST SP 800-38D)."""
        assert IV_LENGTH == 12

    def test_key_length(self):
        """Cle de 32 octets (256 bits) pour AES-256."""
        assert KEY_LENGTH == 32

    def test_iterations(self):
        """Au moins 100 000 iterations PBKDF2 (recommandation OWASP 2024)."""
        assert ITERATIONS >= 100_000


# ──────────────────────────────────────────────
# Tests derivation de cle
# ──────────────────────────────────────────────

class TestDerivationCle:
    """Tests de la derivation de cle PBKDF2."""

    def test_derive_key_longueur(self):
        """La cle derivee fait 32 octets."""
        salt = b"0" * SALT_LENGTH
        key = _derive_key("password", salt)
        assert len(key) == KEY_LENGTH

    def test_derive_key_deterministe(self):
        """Meme mot de passe + sel = meme cle."""
        salt = b"1" * SALT_LENGTH
        k1 = _derive_key("monmotdepasse", salt)
        k2 = _derive_key("monmotdepasse", salt)
        assert k1 == k2

    def test_derive_key_sel_different(self):
        """Sel different = cle differente."""
        s1 = b"a" * SALT_LENGTH
        s2 = b"b" * SALT_LENGTH
        k1 = _derive_key("password", s1)
        k2 = _derive_key("password", s2)
        assert k1 != k2

    def test_derive_key_mdp_different(self):
        """Mot de passe different = cle differente."""
        salt = b"c" * SALT_LENGTH
        k1 = _derive_key("password1", salt)
        k2 = _derive_key("password2", salt)
        assert k1 != k2


# ──────────────────────────────────────────────
# Tests chiffrement/dechiffrement de fichiers
# ──────────────────────────────────────────────

class TestChiffrementFichier:
    """Tests du chiffrement et dechiffrement de fichiers."""

    def test_chiffrer_dechiffrer_roundtrip(self, tmp_path):
        """Chiffrer puis dechiffrer retourne le contenu original."""
        source = tmp_path / "original.txt"
        chiffre = tmp_path / "chiffre.enc"
        resultat = tmp_path / "resultat.txt"

        contenu = b"Donnees sensibles de paie"
        source.write_bytes(contenu)

        chiffrer_fichier(source, chiffre, "MotDePasseSecurise2026!")
        dechiffrer_fichier(chiffre, resultat, "MotDePasseSecurise2026!")

        assert resultat.read_bytes() == contenu

    def test_chiffrer_fichier_format(self, tmp_path):
        """Le fichier chiffre commence par le magic header."""
        source = tmp_path / "source.txt"
        chiffre = tmp_path / "chiffre.enc"
        source.write_bytes(b"Test content")

        chiffrer_fichier(source, chiffre, "password")

        data = chiffre.read_bytes()
        assert data[:8] == HEADER_MAGIC
        # Le fichier doit etre plus grand que l'original (header + tag)
        assert len(data) > len(b"Test content")

    def test_chiffrer_fichier_structure(self, tmp_path):
        """Le fichier chiffre a la structure : MAGIC | SALT | IV | CIPHERTEXT."""
        source = tmp_path / "source.txt"
        chiffre = tmp_path / "chiffre.enc"
        source.write_bytes(b"Structure test")

        chiffrer_fichier(source, chiffre, "password")

        data = chiffre.read_bytes()
        assert len(data) >= 8 + SALT_LENGTH + IV_LENGTH  # Au minimum header

    def test_dechiffrer_mauvais_mot_de_passe(self, tmp_path):
        """Le dechiffrement echoue avec un mauvais mot de passe."""
        source = tmp_path / "source.txt"
        chiffre = tmp_path / "chiffre.enc"
        resultat = tmp_path / "resultat.txt"

        source.write_bytes(b"Donnees confidentielles")
        chiffrer_fichier(source, chiffre, "bon_mot_de_passe")

        with pytest.raises(EncryptionError):
            dechiffrer_fichier(chiffre, resultat, "mauvais_mot_de_passe")

    def test_dechiffrer_format_invalide(self, tmp_path):
        """Le dechiffrement d'un fichier non chiffre echoue."""
        fichier = tmp_path / "pas_chiffre.txt"
        resultat = tmp_path / "resultat.txt"
        fichier.write_bytes(b"Ceci n'est pas un fichier chiffre")

        with pytest.raises(EncryptionError, match="invalide"):
            dechiffrer_fichier(fichier, resultat, "password")

    def test_chiffrer_fichier_vide(self, tmp_path):
        """Le chiffrement d'un fichier vide fonctionne."""
        source = tmp_path / "vide.txt"
        chiffre = tmp_path / "chiffre.enc"
        resultat = tmp_path / "resultat.txt"

        source.write_bytes(b"")
        chiffrer_fichier(source, chiffre, "password")
        dechiffrer_fichier(chiffre, resultat, "password")

        assert resultat.read_bytes() == b""

    def test_chiffrer_fichier_gros(self, tmp_path):
        """Le chiffrement d'un fichier de 1 MB fonctionne."""
        source = tmp_path / "gros.bin"
        chiffre = tmp_path / "chiffre.enc"
        resultat = tmp_path / "resultat.txt"

        contenu = b"x" * (1024 * 1024)
        source.write_bytes(contenu)

        chiffrer_fichier(source, chiffre, "password")
        dechiffrer_fichier(chiffre, resultat, "password")

        assert resultat.read_bytes() == contenu

    def test_chiffrer_fichier_contenu_binaire(self, tmp_path):
        """Le chiffrement de contenu binaire fonctionne."""
        source = tmp_path / "binary.bin"
        chiffre = tmp_path / "chiffre.enc"
        resultat = tmp_path / "resultat.bin"

        contenu = bytes(range(256)) * 4
        source.write_bytes(contenu)

        chiffrer_fichier(source, chiffre, "password")
        dechiffrer_fichier(chiffre, resultat, "password")

        assert resultat.read_bytes() == contenu

    def test_chiffrement_non_deterministe(self, tmp_path):
        """Deux chiffrements du meme contenu produisent des resultats differents (sel aleatoire)."""
        source = tmp_path / "source.txt"
        c1 = tmp_path / "chiffre1.enc"
        c2 = tmp_path / "chiffre2.enc"

        source.write_bytes(b"Meme contenu")
        chiffrer_fichier(source, c1, "password")
        chiffrer_fichier(source, c2, "password")

        assert c1.read_bytes() != c2.read_bytes()

    def test_fichier_source_inexistant(self, tmp_path):
        """Chiffrer un fichier inexistant leve une exception."""
        source = tmp_path / "inexistant.txt"
        chiffre = tmp_path / "chiffre.enc"

        with pytest.raises(EncryptionError):
            chiffrer_fichier(source, chiffre, "password")

    def test_fichier_chiffre_altere(self, tmp_path):
        """Un fichier chiffre altere ne peut pas etre dechiffre (GCM tag check)."""
        source = tmp_path / "source.txt"
        chiffre = tmp_path / "chiffre.enc"
        resultat = tmp_path / "resultat.txt"

        source.write_bytes(b"Donnees importantes")
        chiffrer_fichier(source, chiffre, "password")

        # Alterer un octet du ciphertext
        data = bytearray(chiffre.read_bytes())
        if len(data) > 60:
            data[60] ^= 0xFF  # Flip bits
        chiffre.write_bytes(bytes(data))

        with pytest.raises(EncryptionError):
            dechiffrer_fichier(chiffre, resultat, "password")


# ──────────────────────────────────────────────
# Tests chiffrement/dechiffrement en memoire
# ──────────────────────────────────────────────

class TestChiffrementDonnees:
    """Tests du chiffrement et dechiffrement en memoire."""

    def test_chiffrer_dechiffrer_roundtrip(self):
        """Chiffrer puis dechiffrer retourne les donnees originales."""
        data = b"Donnees en memoire"
        chiffre = chiffrer_donnees(data, "password")
        resultat = dechiffrer_donnees(chiffre, "password")
        assert resultat == data

    def test_chiffrer_donnees_format(self):
        """Les donnees chiffrees commencent par le magic header."""
        chiffre = chiffrer_donnees(b"test", "password")
        assert chiffre[:8] == HEADER_MAGIC

    def test_chiffrer_donnees_structure(self):
        """Structure : MAGIC(8) + SALT(32) + IV(12) + CIPHERTEXT."""
        chiffre = chiffrer_donnees(b"test", "password")
        min_size = 8 + SALT_LENGTH + IV_LENGTH
        assert len(chiffre) >= min_size

    def test_dechiffrer_mauvais_mot_de_passe(self):
        """Le dechiffrement echoue avec un mauvais mot de passe."""
        chiffre = chiffrer_donnees(b"secret", "bon_mdp")
        with pytest.raises(Exception):
            dechiffrer_donnees(chiffre, "mauvais_mdp")

    def test_dechiffrer_format_invalide(self):
        """Le dechiffrement de donnees non chiffrees echoue."""
        with pytest.raises(EncryptionError, match="invalide"):
            dechiffrer_donnees(b"pas chiffre du tout", "password")

    def test_chiffrer_donnees_vides(self):
        """Le chiffrement de donnees vides fonctionne."""
        chiffre = chiffrer_donnees(b"", "password")
        resultat = dechiffrer_donnees(chiffre, "password")
        assert resultat == b""

    def test_chiffrer_donnees_unicode(self):
        """Le chiffrement de donnees UTF-8 fonctionne."""
        data = "Données avec accents éàü".encode("utf-8")
        chiffre = chiffrer_donnees(data, "password")
        resultat = dechiffrer_donnees(chiffre, "password")
        assert resultat == data

    def test_chiffrement_memoire_non_deterministe(self):
        """Deux chiffrements du meme contenu donnent des resultats differents."""
        data = b"meme contenu"
        c1 = chiffrer_donnees(data, "password")
        c2 = chiffrer_donnees(data, "password")
        assert c1 != c2

    def test_donnees_alterees_detectees(self):
        """Des donnees chiffrees alterees sont detectees (GCM authentification)."""
        chiffre = bytearray(chiffrer_donnees(b"donnees", "password"))
        if len(chiffre) > 60:
            chiffre[60] ^= 0xFF
        with pytest.raises(Exception):
            dechiffrer_donnees(bytes(chiffre), "password")

    def test_chiffrer_gros_volume(self):
        """Le chiffrement de 1 MB en memoire fonctionne."""
        data = b"x" * (1024 * 1024)
        chiffre = chiffrer_donnees(data, "password")
        resultat = dechiffrer_donnees(chiffre, "password")
        assert resultat == data


# ──────────────────────────────────────────────
# Tests HAS_CRYPTOGRAPHY=False (garde defensive)
# ──────────────────────────────────────────────

class TestSansCryptography:
    """Tests des branches defensives quand cryptography est absent."""

    def test_derive_key_sans_crypto(self):
        """_derive_key leve EncryptionError sans cryptography."""
        import urssaf_analyzer.security.encryption as enc_module
        original = enc_module.HAS_CRYPTOGRAPHY
        try:
            enc_module.HAS_CRYPTOGRAPHY = False
            with pytest.raises(EncryptionError, match="cryptography"):
                _derive_key("password", b"0" * SALT_LENGTH)
        finally:
            enc_module.HAS_CRYPTOGRAPHY = original

    def test_chiffrer_fichier_sans_crypto(self, tmp_path):
        """chiffrer_fichier leve EncryptionError sans cryptography."""
        import urssaf_analyzer.security.encryption as enc_module
        original = enc_module.HAS_CRYPTOGRAPHY
        try:
            enc_module.HAS_CRYPTOGRAPHY = False
            source = tmp_path / "s.txt"
            source.write_bytes(b"test")
            with pytest.raises(EncryptionError, match="cryptography"):
                chiffrer_fichier(source, tmp_path / "out.enc", "pwd")
        finally:
            enc_module.HAS_CRYPTOGRAPHY = original

    def test_dechiffrer_fichier_sans_crypto(self, tmp_path):
        """dechiffrer_fichier leve EncryptionError sans cryptography."""
        import urssaf_analyzer.security.encryption as enc_module
        original = enc_module.HAS_CRYPTOGRAPHY
        try:
            enc_module.HAS_CRYPTOGRAPHY = False
            with pytest.raises(EncryptionError, match="cryptography"):
                dechiffrer_fichier(tmp_path / "in.enc", tmp_path / "out.txt", "pwd")
        finally:
            enc_module.HAS_CRYPTOGRAPHY = original

    def test_chiffrer_donnees_sans_crypto(self):
        """chiffrer_donnees leve EncryptionError sans cryptography."""
        import urssaf_analyzer.security.encryption as enc_module
        original = enc_module.HAS_CRYPTOGRAPHY
        try:
            enc_module.HAS_CRYPTOGRAPHY = False
            with pytest.raises(EncryptionError, match="cryptography"):
                chiffrer_donnees(b"test", "pwd")
        finally:
            enc_module.HAS_CRYPTOGRAPHY = original

    def test_dechiffrer_donnees_sans_crypto(self):
        """dechiffrer_donnees leve EncryptionError sans cryptography."""
        import urssaf_analyzer.security.encryption as enc_module
        original = enc_module.HAS_CRYPTOGRAPHY
        try:
            enc_module.HAS_CRYPTOGRAPHY = False
            with pytest.raises(EncryptionError, match="cryptography"):
                dechiffrer_donnees(HEADER_MAGIC + b"x" * 100, "pwd")
        finally:
            enc_module.HAS_CRYPTOGRAPHY = original


# ──────────────────────────────────────────────
# Tests erreurs E/S (OSError paths)
# ──────────────────────────────────────────────

class TestErreursES:
    """Tests des chemins d'erreur E/S."""

    def test_dechiffrer_fichier_destination_interdite(self, tmp_path):
        """Dechiffrement echoue si la destination est non-inscriptible."""
        source = tmp_path / "source.txt"
        chiffre = tmp_path / "chiffre.enc"
        source.write_bytes(b"test content")
        chiffrer_fichier(source, chiffre, "password")

        # Destination dans un repertoire inexistant
        dest = tmp_path / "nonexistent_dir" / "subdir" / "result.txt"
        with pytest.raises(EncryptionError):
            dechiffrer_fichier(chiffre, dest, "password")

    def test_chiffrer_fichier_destination_interdite(self, tmp_path):
        """Chiffrement echoue si la destination est non-inscriptible."""
        source = tmp_path / "source.txt"
        source.write_bytes(b"test content")

        dest = tmp_path / "nonexistent_dir" / "subdir" / "result.enc"
        with pytest.raises(EncryptionError):
            chiffrer_fichier(source, dest, "password")
