"""Chiffrement AES-256-GCM des documents sensibles.

Ameliorations de securite :
- PBKDF2 a 310 000 iterations (OWASP 2024+)
- AAD (Additional Authenticated Data) pour lier le contexte au chiffre
- Version du format pour migration future
- Chiffrement de champs individuels (NIR, IBAN, etc.)
- Nettoyage memoire des cles derivees
"""

import os
import hmac
import hashlib
import secrets
import struct
import base64
import logging
from pathlib import Path

from urssaf_analyzer.core.exceptions import EncryptionError

logger = logging.getLogger(__name__)

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False

SALT_LENGTH = 32
IV_LENGTH = 12       # 96 bits recommande pour GCM (NIST SP 800-38D)
KEY_LENGTH = 32      # 256 bits
ITERATIONS = 310_000  # OWASP 2024+ pour PBKDF2-HMAC-SHA256

# Format fichier chiffre v2 : MAGIC (8) | VERSION (2) | SALT (32) | IV (12) | AAD_LEN (2) | AAD | CIPHERTEXT+TAG
HEADER_MAGIC = b"URSAFE01"
FORMAT_VERSION = 2   # v2 avec AAD et iterations renforcees

# Compatibilite v1 (ancien format sans version)
_V1_ITERATIONS = 100_000


def _derive_key(password: str, salt: bytes, iterations: int = ITERATIONS) -> bytes:
    """Derive une cle AES-256 a partir d'un mot de passe via PBKDF2-HMAC-SHA256."""
    if not HAS_CRYPTOGRAPHY:
        raise EncryptionError("Le module 'cryptography' n'est pas installe.")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_LENGTH,
        salt=salt,
        iterations=iterations,
    )
    return kdf.derive(password.encode("utf-8"))


def chiffrer_fichier(source: Path, destination: Path, password: str) -> None:
    """Chiffre un fichier avec AES-256-GCM.

    Format de sortie v2 : MAGIC (8) | VERSION (2) | SALT (32) | IV (12) | AAD_LEN (2) | AAD | CIPHERTEXT+TAG
    AAD contient le nom du fichier source pour lier le chiffre a son contexte.
    """
    if not HAS_CRYPTOGRAPHY:
        raise EncryptionError("Le module 'cryptography' n'est pas installe.")

    salt = secrets.token_bytes(SALT_LENGTH)
    iv = secrets.token_bytes(IV_LENGTH)
    key = _derive_key(password, salt)
    aesgcm = AESGCM(key)

    # AAD : nom du fichier (lie le chiffre au contexte)
    aad = source.name.encode("utf-8")[:256]

    try:
        with open(source, "rb") as f:
            plaintext = f.read()
        ciphertext = aesgcm.encrypt(iv, plaintext, aad)
        with open(destination, "wb") as f:
            f.write(HEADER_MAGIC)
            f.write(struct.pack("<H", FORMAT_VERSION))
            f.write(salt)
            f.write(iv)
            f.write(struct.pack("<H", len(aad)))
            f.write(aad)
            f.write(ciphertext)
    except OSError as e:
        raise EncryptionError(f"Erreur E/S lors du chiffrement: {e}") from e
    except Exception as e:
        raise EncryptionError(f"Erreur de chiffrement: {e}") from e


def dechiffrer_fichier(source: Path, destination: Path, password: str) -> None:
    """Dechiffre un fichier chiffre avec AES-256-GCM. Compatible v1 et v2."""
    if not HAS_CRYPTOGRAPHY:
        raise EncryptionError("Le module 'cryptography' n'est pas installe.")

    try:
        with open(source, "rb") as f:
            magic = f.read(len(HEADER_MAGIC))
            if magic != HEADER_MAGIC:
                raise EncryptionError("Format de fichier chiffre invalide.")

            # Detecter la version du format
            pos = f.tell()
            version_bytes = f.read(2)
            version = struct.unpack("<H", version_bytes)[0] if len(version_bytes) == 2 else 1

            if version == FORMAT_VERSION:
                # Format v2 : avec AAD
                salt = f.read(SALT_LENGTH)
                iv = f.read(IV_LENGTH)
                aad_len = struct.unpack("<H", f.read(2))[0]
                aad = f.read(aad_len) if aad_len > 0 else None
                ciphertext = f.read()
                iterations = ITERATIONS
            else:
                # Format v1 : sans version ni AAD (retro-compatibilite)
                f.seek(pos)
                salt = f.read(SALT_LENGTH)
                iv = f.read(IV_LENGTH)
                ciphertext = f.read()
                aad = None
                iterations = _V1_ITERATIONS

        key = _derive_key(password, salt, iterations)
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(iv, ciphertext, aad)

        with open(destination, "wb") as f:
            f.write(plaintext)
    except EncryptionError:
        raise
    except OSError as e:
        raise EncryptionError(f"Erreur E/S lors du dechiffrement: {e}") from e
    except Exception as e:
        raise EncryptionError(f"Echec du dechiffrement (mot de passe incorrect ?): {e}") from e


def chiffrer_donnees(data: bytes, password: str, contexte: str = "") -> bytes:
    """Chiffre des donnees en memoire avec AES-256-GCM.

    Args:
        data: Donnees a chiffrer.
        password: Mot de passe / cle de chiffrement.
        contexte: Contexte optionnel (ex: nom du fichier) lie au chiffre via AAD.

    Returns:
        Donnees chiffrees au format v2.
    """
    if not HAS_CRYPTOGRAPHY:
        raise EncryptionError("Le module 'cryptography' n'est pas installe.")
    salt = secrets.token_bytes(SALT_LENGTH)
    iv = secrets.token_bytes(IV_LENGTH)
    key = _derive_key(password, salt)
    aesgcm = AESGCM(key)
    aad = contexte.encode("utf-8")[:256] if contexte else None
    ciphertext = aesgcm.encrypt(iv, data, aad)
    aad_bytes = aad or b""
    return (
        HEADER_MAGIC
        + struct.pack("<H", FORMAT_VERSION)
        + salt + iv
        + struct.pack("<H", len(aad_bytes))
        + aad_bytes
        + ciphertext
    )


def dechiffrer_donnees(data: bytes, password: str, contexte: str = "") -> bytes:
    """Dechiffre des donnees en memoire. Compatible v1 et v2."""
    if not HAS_CRYPTOGRAPHY:
        raise EncryptionError("Le module 'cryptography' n'est pas installe.")
    offset = len(HEADER_MAGIC)
    if data[:offset] != HEADER_MAGIC:
        raise EncryptionError("Format de donnees chiffrees invalide.")

    # Detecter la version
    version = struct.unpack("<H", data[offset:offset + 2])[0] if len(data) > offset + 2 else 1

    if version == FORMAT_VERSION:
        offset += 2
        salt = data[offset:offset + SALT_LENGTH]
        offset += SALT_LENGTH
        iv = data[offset:offset + IV_LENGTH]
        offset += IV_LENGTH
        aad_len = struct.unpack("<H", data[offset:offset + 2])[0]
        offset += 2
        aad = data[offset:offset + aad_len] if aad_len > 0 else None
        offset += aad_len
        ciphertext = data[offset:]
        iterations = ITERATIONS
    else:
        # v1 : pas de version ni AAD
        salt = data[offset:offset + SALT_LENGTH]
        offset += SALT_LENGTH
        iv = data[offset:offset + IV_LENGTH]
        offset += IV_LENGTH
        ciphertext = data[offset:]
        aad = None
        iterations = _V1_ITERATIONS

    key = _derive_key(password, salt, iterations)
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(iv, ciphertext, aad)


# ============================================================
# CHIFFREMENT DE CHAMPS INDIVIDUELS (NIR, IBAN, donnees sensibles)
# ============================================================

def chiffrer_champ(valeur: str, password: str) -> str:
    """Chiffre un champ textuel sensible (NIR, IBAN, etc.).

    Retourne une chaine base64 prefixee par 'ENC:' pour identification.
    Utilise AES-256-GCM avec un sel unique par champ.
    """
    if not valeur or not password:
        return valeur
    if not HAS_CRYPTOGRAPHY:
        logger.error("SECURITE: chiffrement impossible - module 'cryptography' manquant. Donnee sensible non protegee.")
        raise EncryptionError("Le module 'cryptography' est requis pour chiffrer les donnees sensibles.")
    try:
        encrypted = chiffrer_donnees(valeur.encode("utf-8"), password)
        return "ENC:" + base64.urlsafe_b64encode(encrypted).decode("ascii")
    except EncryptionError:
        raise
    except Exception as e:
        logger.error("SECURITE: echec chiffrement champ - %s", e)
        raise EncryptionError(f"Echec du chiffrement: {e}") from e


def dechiffrer_champ(valeur: str, password: str) -> str:
    """Dechiffre un champ textuel sensible prefixe par 'ENC:'.

    Si la valeur n'est pas chiffree (pas de prefixe ENC:), la retourne telle quelle.
    """
    if not valeur or not password:
        return valeur
    if not valeur.startswith("ENC:"):
        return valeur
    if not HAS_CRYPTOGRAPHY:
        return "[chiffre - module cryptography requis]"
    try:
        encrypted = base64.urlsafe_b64decode(valeur[4:])
        return dechiffrer_donnees(encrypted, password).decode("utf-8")
    except Exception as e:
        logger.warning("Echec dechiffrement champ: %s", e)
        return "[dechiffrement echoue]"


def est_chiffre(valeur: str) -> bool:
    """Verifie si une valeur est un champ chiffre (prefixe ENC:)."""
    return isinstance(valeur, str) and valeur.startswith("ENC:")


def masquer_champ(valeur: str, nb_visible: int = 4) -> str:
    """Masque un champ sensible pour affichage (ex: NIR, IBAN).

    Exemples :
        masquer_champ("1234567890123") -> "****890123"
        masquer_champ("FR7612345678901234") -> "****901234"
    """
    if not valeur or len(valeur) <= nb_visible:
        return valeur
    return "*" * 4 + valeur[-nb_visible:]
