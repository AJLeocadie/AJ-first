"""Gestion securisee du stockage de fichiers."""

import os
import secrets
import shutil
from pathlib import Path

from urssaf_analyzer.core.exceptions import SecurityError


def suppression_securisee(chemin: Path, passes: int = 3) -> None:
    """Supprime un fichier de maniere securisee en ecrasant son contenu."""
    if not chemin.exists():
        return
    if not chemin.is_file():
        raise SecurityError(f"Le chemin {chemin} n'est pas un fichier.")

    taille = chemin.stat().st_size
    try:
        for _ in range(passes):
            with open(chemin, "wb") as f:
                f.write(secrets.token_bytes(taille))
                f.flush()
                os.fsync(f.fileno())
        chemin.unlink()
    except OSError as e:
        raise SecurityError(f"Echec de la suppression securisee de {chemin}: {e}") from e


def nettoyer_repertoire_temp(temp_dir: Path, passes: int = 3) -> int:
    """Supprime de maniere securisee tous les fichiers d'un repertoire temporaire.

    Retourne le nombre de fichiers supprimes.
    """
    if not temp_dir.exists():
        return 0

    count = 0
    for f in temp_dir.rglob("*"):
        if f.is_file():
            suppression_securisee(f, passes=passes)
            count += 1

    # Supprimer les sous-repertoires vides
    for d in sorted(temp_dir.rglob("*"), reverse=True):
        if d.is_dir():
            try:
                d.rmdir()
            except OSError:
                pass

    return count


def verifier_taille_fichier(chemin: Path, max_mb: int = 100) -> None:
    """Verifie qu'un fichier ne depasse pas la taille maximale autorisee."""
    taille_mb = chemin.stat().st_size / (1024 * 1024)
    if taille_mb > max_mb:
        raise SecurityError(
            f"Le fichier {chemin.name} fait {taille_mb:.1f} MB, "
            f"la limite est de {max_mb} MB."
        )


def creer_repertoire_session(base_dir: Path, session_id: str) -> Path:
    """Cree un repertoire isole pour une session d'analyse."""
    session_dir = base_dir / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir
