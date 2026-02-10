"""Point d'entree CLI pour URSSAF Analyzer.

Usage :
    python -m urssaf_analyzer fichier1.pdf fichier2.csv [--format html|json] [--output DIR]
"""

import argparse
import logging
import sys
from pathlib import Path

from urssaf_analyzer.config.settings import AppConfig
from urssaf_analyzer.core.orchestrator import Orchestrator
from urssaf_analyzer.core.exceptions import URSSAFAnalyzerError
from urssaf_analyzer.config.constants import SUPPORTED_EXTENSIONS


BANNER = r"""
  _   _ ____  ____ ____    _    _____     _                _
 | | | |  _ \/ ___/ ___|  / \  |  ___|   / \   _ __   __ _| |_   _ _______ _ __
 | | | | |_) \___ \___ \ / _ \ | |_     / _ \ | '_ \ / _` | | | | |_  / _ \ '__|
 | |_| |  _ < ___) |__) / ___ \|  _|   / ___ \| | | | (_| | | |_| |/ /  __/ |
  \___/|_| \_\____/____/_/   \_\_|    /_/   \_\_| |_|\__,_|_|\__, /___\___|_|
                                                              |___/
  v1.0.0 - Analyse securisee de documents sociaux et fiscaux
"""


def configurer_logging(verbose: bool = False) -> None:
    """Configure le logging de l'application."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def creer_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="urssaf_analyzer",
        description="Analyse securisee de documents sociaux et fiscaux URSSAF.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"Formats supportes : {', '.join(SUPPORTED_EXTENSIONS.keys())}",
    )
    parser.add_argument(
        "fichiers",
        nargs="+",
        type=Path,
        help="Chemin(s) vers les fichiers a analyser",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["html", "json"],
        default="html",
        help="Format du rapport de sortie (defaut: html)",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="Repertoire de sortie pour le rapport",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Mode verbeux (debug)",
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Ne pas nettoyer les fichiers temporaires apres l'analyse",
    )
    return parser


def main() -> int:
    """Point d'entree principal."""
    print(BANNER)

    parser = creer_argument_parser()
    args = parser.parse_args()

    configurer_logging(args.verbose)
    logger = logging.getLogger("urssaf_analyzer")

    # Verifier que les fichiers existent
    fichiers_valides = []
    for f in args.fichiers:
        if not f.exists():
            logger.error("Fichier introuvable : %s", f)
            continue
        if f.suffix.lower() not in SUPPORTED_EXTENSIONS:
            logger.error(
                "Format non supporte : %s (acceptes : %s)",
                f.suffix, ", ".join(SUPPORTED_EXTENSIONS.keys()),
            )
            continue
        fichiers_valides.append(f)

    if not fichiers_valides:
        logger.error("Aucun fichier valide a analyser.")
        return 1

    logger.info("Fichiers a analyser : %d", len(fichiers_valides))
    for f in fichiers_valides:
        logger.info("  - %s (%s)", f.name, f.suffix)

    # Configuration
    config = AppConfig()
    if args.output:
        config.reports_dir = args.output
        config.reports_dir.mkdir(parents=True, exist_ok=True)

    # Lancement de l'analyse
    orchestrator = Orchestrator(config)

    try:
        chemin_rapport = orchestrator.analyser_documents(
            fichiers_valides,
            format_rapport=args.format,
        )
        print(f"\n{'='*60}")
        print(f"  ANALYSE TERMINEE")
        print(f"  Rapport : {chemin_rapport}")
        print(f"  Constats : {len(orchestrator.result.findings)}")
        print(f"  Score de risque : {orchestrator.result.score_risque_global}/100")
        print(f"{'='*60}\n")
        return 0

    except URSSAFAnalyzerError as e:
        logger.error("Erreur d'analyse : %s", e)
        return 1
    except Exception as e:
        logger.exception("Erreur inattendue : %s", e)
        return 2
    finally:
        if not args.no_cleanup:
            orchestrator.nettoyer()


if __name__ == "__main__":
    sys.exit(main())
