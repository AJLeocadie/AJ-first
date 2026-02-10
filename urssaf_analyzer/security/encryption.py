"""Chiffrement AES-256-GCM des documents sensibles."""

import os
import secrets
import struct
from pathlib import Path

from urssaf_analyzer.core.exceptions import EncryptionError

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False

SALT_LENGTH = 32
IV_LENGTH = 12       # 96 bits recommande pour GCM
KEY_LENGTH = 32      # 256 bits
ITERATIONS = 100_000
CHUNK_SIZE = 64 * 1024  # 64 KB

# Format fichier chiffre : SALT (32) | IV (12) | TAG (16) | CIPHERTEXT
HEADER_MAGIC = b"URSAFE01"


def _derive_key(password: str, salt: bytes) -> bytes:
    """Derive une cle AES-256 a partir d'un mot de passe via PBKDF2."""
    if not HAS_CRYPTOGRAPHY:
        raise EncryptionError("Le module 'cryptography' n'est pas installe.")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_LENGTH,
        salt=salt,
        iterations=ITERATIONS,
    )
    return kdf.derive(password.encode("utf-8"))


def chiffrer_fichier(source: Path, destination: Path, password: str) -> None:
    """Chiffre un fichier avec AES-256-GCM.

    Format de sortie : MAGIC (8) | SALT (32) | IV (12) | donnees chiffrees+tag
    """
    if not HAS_CRYPTOGRAPHY:
        raise EncryptionError("Le module 'cryptography' n'est pas installe.")

    salt = secrets.token_bytes(SALT_LENGTH)
    iv = secrets.token_bytes(IV_LENGTH)
    key = _derive_key(password, salt)
    aesgcm = AESGCM(key)

    try:
        with open(source, "rb") as f:
            plaintext = f.read()
        ciphertext = aesgcm.encrypt(iv, plaintext, None)
        with open(destination, "wb") as f:
            f.write(HEADER_MAGIC)
            f.write(salt)
            f.write(iv)
            f.write(ciphertext)
    except OSError as e:
        raise EncryptionError(f"Erreur E/S lors du chiffrement: {e}") from e
    except Exception as e:
        raise EncryptionError(f"Erreur de chiffrement: {e}") from e


def dechiffrer_fichier(source: Path, destination: Path, password: str) -> None:
    """Dechiffre un fichier chiffre avec AES-256-GCM."""
    if not HAS_CRYPTOGRAPHY:
        raise EncryptionError("Le module 'cryptography' n'est pas installe.")

    try:
        with open(source, "rb") as f:
            magic = f.read(len(HEADER_MAGIC))
            if magic != HEADER_MAGIC:
                raise EncryptionError("Format de fichier chiffre invalide.")
            salt = f.read(SALT_LENGTH)
            iv = f.read(IV_LENGTH)
            ciphertext = f.read()

        key = _derive_key(password, salt)
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(iv, ciphertext, None)

        with open(destination, "wb") as f:
            f.write(plaintext)
    except EncryptionError:
        raise
    except OSError as e:
        raise EncryptionError(f"Erreur E/S lors du dechiffrement: {e}") from e
    except Exception as e:
        raise EncryptionError(f"Echec du dechiffrement (mot de passe incorrect ?): {e}") from e


def chiffrer_donnees(data: bytes, password: str) -> bytes:
    """Chiffre des donnees en memoire. Retourne salt+iv+ciphertext."""
    if not HAS_CRYPTOGRAPHY:
        raise EncryptionError("Le module 'cryptography' n'est pas installe.")
    salt = secrets.token_bytes(SALT_LENGTH)
    iv = secrets.token_bytes(IV_LENGTH)
    key = _derive_key(password, salt)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(iv, data, None)
    return HEADER_MAGIC + salt + iv + ciphertext


def dechiffrer_donnees(data: bytes, password: str) -> bytes:
    """Dechiffre des donnees en memoire."""
    if not HAS_CRYPTOGRAPHY:
        raise EncryptionError("Le module 'cryptography' n'est pas installe.")
    offset = len(HEADER_MAGIC)
    if data[:offset] != HEADER_MAGIC:
        raise EncryptionError("Format de donnees chiffrees invalide.")
    salt = data[offset:offset + SALT_LENGTH]
    offset += SALT_LENGTH
    iv = data[offset:offset + IV_LENGTH]
    offset += IV_LENGTH
    ciphertext = data[offset:]
    key = _derive_key(password, salt)
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(iv, ciphertext, None)
