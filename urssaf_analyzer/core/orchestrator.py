"""Orchestrateur principal de l'analyse URSSAF.

Coordonne l'ensemble du workflow :
1. Import et verification d'integrite des documents
2. Parsing multi-format
3. Analyse et detection d'anomalies
4. Generation du rapport
5. Nettoyage securise
"""

import logging
import time
from pathlib import Path

from urssaf_analyzer.config.settings import AppConfig
from urssaf_analyzer.core.exceptions import ParseError, URSSAFAnalyzerError
from urssaf_analyzer.models.documents import (
    AnalysisResult, Document, FileType,
)
from urssaf_analyzer.parsers.parser_factory import ParserFactory
from urssaf_analyzer.analyzers.analyzer_engine import AnalyzerEngine
from urssaf_analyzer.reporting.report_generator import ReportGenerator
from urssaf_analyzer.security.integrity import calculer_hash_sha256
from urssaf_analyzer.security.audit_logger import AuditLogger
from urssaf_analyzer.security.secure_storage import (
    verifier_taille_fichier, nettoyer_repertoire_temp,
)
from urssaf_analyzer.config.constants import SUPPORTED_EXTENSIONS

logger = logging.getLogger("urssaf_analyzer")


class Orchestrator:
    """Coordonne l'ensemble de l'analyse URSSAF."""

    def __init__(self, config: AppConfig | None = None):
        self.config = config or AppConfig()
        self.parser_factory = ParserFactory()
        self.report_generator = ReportGenerator()
        self.audit = AuditLogger(self.config.audit_log_path)
        self.result = AnalysisResult()

    def analyser_documents(self, chemins: list[Path], format_rapport: str = "html") -> Path:
        """Point d'entree principal : analyse une liste de documents.

        Args:
            chemins: Liste des chemins vers les fichiers a analyser.
            format_rapport: Format de sortie ("html" ou "json").

        Returns:
            Chemin vers le rapport genere.
        """
        debut = time.time()
        session_id = self.result.session_id
        logger.info("Demarrage de l'analyse - Session %s", session_id)
        self.audit.log("demarrage_analyse", session_id, details={
            "nb_fichiers": len(chemins),
            "format_rapport": format_rapport,
        })

        # --- Phase 1 : Import et verification ---
        logger.info("Phase 1/4 : Import et verification des documents")
        documents = []
        for chemin in chemins:
            try:
                doc = self._importer_document(chemin, session_id)
                documents.append(doc)
            except URSSAFAnalyzerError as e:
                logger.warning("Impossible d'importer %s : %s", chemin, e)
                self.audit.log_erreur(session_id, "import", str(e))

        if not documents:
            raise URSSAFAnalyzerError("Aucun document n'a pu etre importe.")

        self.result.documents_analyses = documents

        # --- Phase 2 : Parsing ---
        logger.info("Phase 2/4 : Parsing des documents (%d fichiers)", len(documents))
        declarations = []
        for doc in documents:
            try:
                parser = self.parser_factory.get_parser(doc.chemin)
                decls = parser.parser(doc.chemin, doc)
                declarations.extend(decls)
                logger.info(
                    "  %s : %d declaration(s), %d cotisation(s)",
                    doc.nom_fichier, len(decls),
                    sum(len(d.cotisations) for d in decls),
                )
            except ParseError as e:
                logger.warning("Erreur de parsing pour %s : %s", doc.nom_fichier, e)
                self.audit.log_erreur(session_id, "parsing", str(e))

        if not declarations:
            logger.warning("Aucune declaration extraite des documents.")

        self.result.declarations = declarations

        # --- Phase 3 : Analyse ---
        logger.info("Phase 3/4 : Analyse et detection d'anomalies")
        effectif = 0
        for decl in declarations:
            if decl.employeur and decl.employeur.effectif > 0:
                effectif = max(effectif, decl.employeur.effectif)

        engine = AnalyzerEngine(effectif=effectif)
        findings = engine.analyser(declarations)
        self.result.findings = findings

        synthese = engine.generer_synthese(findings)
        logger.info(
            "  Resultats : %d constats, impact total = %s EUR",
            synthese["total_findings"],
            synthese["impact_financier_total"],
        )
        self.audit.log_analyse(session_id, "AnalyzerEngine", len(findings))

        # --- Phase 4 : Rapport ---
        logger.info("Phase 4/4 : Generation du rapport (%s)", format_rapport)
        self.result.duree_analyse_secondes = time.time() - debut

        timestamp = self.result.date_analyse.strftime("%Y%m%d_%H%M%S")
        if format_rapport == "json":
            nom_rapport = f"rapport_urssaf_{timestamp}.json"
            chemin_rapport = self.config.reports_dir / nom_rapport
            self.report_generator.generer_json(self.result, chemin_rapport)
        else:
            nom_rapport = f"rapport_urssaf_{timestamp}.html"
            chemin_rapport = self.config.reports_dir / nom_rapport
            self.report_generator.generer_html(self.result, chemin_rapport)

        self.audit.log_rapport(session_id, format_rapport, str(chemin_rapport))
        logger.info("Rapport genere : %s", chemin_rapport)
        logger.info("Analyse terminee en %.1f secondes.", self.result.duree_analyse_secondes)

        return chemin_rapport

    def _importer_document(self, chemin: Path, session_id: str) -> Document:
        """Importe un document avec verification d'integrite."""
        if not chemin.exists():
            raise URSSAFAnalyzerError(f"Fichier introuvable : {chemin}")

        ext = chemin.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise URSSAFAnalyzerError(
                f"Format non supporte : {ext}. "
                f"Formats acceptes : {', '.join(SUPPORTED_EXTENSIONS.keys())}"
            )

        verifier_taille_fichier(chemin, self.config.analysis.max_file_size_mb)

        hash_sha256 = calculer_hash_sha256(chemin)

        doc = Document(
            nom_fichier=chemin.name,
            chemin=chemin,
            type_fichier=FileType(SUPPORTED_EXTENSIONS[ext]),
            hash_sha256=hash_sha256,
            taille_octets=chemin.stat().st_size,
        )

        self.audit.log_import(session_id, str(chemin), hash_sha256)
        return doc

    def nettoyer(self) -> None:
        """Nettoie les fichiers temporaires de maniere securisee."""
        nb = nettoyer_repertoire_temp(
            self.config.temp_dir,
            passes=self.config.security.secure_delete_passes,
        )
        if nb > 0:
            logger.info("%d fichier(s) temporaire(s) supprime(s).", nb)
