"""Verification d'integrite des fichiers via SHA-256."""

import hashlib
from pathlib import Path

from urssaf_analyzer.core.exceptions import IntegrityError

BUFFER_SIZE = 65536  # 64 KB


def calculer_hash_sha256(chemin: Path) -> str:
    """Calcule le hash SHA-256 d'un fichier."""
    sha256 = hashlib.sha256()
    try:
        with open(chemin, "rb") as f:
            while True:
                data = f.read(BUFFER_SIZE)
                if not data:
                    break
                sha256.update(data)
    except OSError as e:
        raise IntegrityError(f"Impossible de lire le fichier {chemin}: {e}") from e
    return sha256.hexdigest()


def verifier_hash(chemin: Path, hash_attendu: str) -> bool:
    """Verifie qu'un fichier correspond au hash attendu."""
    hash_calcule = calculer_hash_sha256(chemin)
    return hash_calcule == hash_attendu


def creer_manifeste(fichiers: list[Path]) -> dict[str, str]:
    """Cree un manifeste de hashes pour une liste de fichiers."""
    return {str(f): calculer_hash_sha256(f) for f in fichiers}


def verifier_manifeste(manifeste: dict[str, str]) -> list[str]:
    """Verifie un manifeste et retourne les fichiers dont le hash ne correspond pas."""
    fichiers_invalides = []
    for chemin_str, hash_attendu in manifeste.items():
        chemin = Path(chemin_str)
        if not chemin.exists():
            fichiers_invalides.append(chemin_str)
            continue
        if not verifier_hash(chemin, hash_attendu):
            fichiers_invalides.append(chemin_str)
    return fichiers_invalides
