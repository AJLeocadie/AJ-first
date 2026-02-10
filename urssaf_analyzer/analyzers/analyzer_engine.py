"""Moteur d'analyse coordonnant tous les analyseurs."""

import logging

from urssaf_analyzer.analyzers.anomaly_detector import AnomalyDetector
from urssaf_analyzer.analyzers.consistency_checker import ConsistencyChecker
from urssaf_analyzer.analyzers.pattern_analyzer import PatternAnalyzer
from urssaf_analyzer.config.constants import Severity, FindingCategory
from urssaf_analyzer.models.documents import Declaration, Finding, AnalysisResult

logger = logging.getLogger("urssaf_analyzer.engine")


class AnalyzerEngine:
    """Coordonne l'execution de tous les analyseurs et agregue les resultats."""

    def __init__(self, effectif: int = 0):
        self.analyzers = [
            AnomalyDetector(effectif=effectif),
            ConsistencyChecker(),
            PatternAnalyzer(),
        ]

    def analyser(self, declarations: list[Declaration]) -> list[Finding]:
        """Execute tous les analyseurs et retourne les findings agrges."""
        all_findings: list[Finding] = []

        for analyzer in self.analyzers:
            try:
                findings = analyzer.analyser(declarations)
                all_findings.extend(findings)
                logger.info(
                    "%s : %d constat(s) detecte(s)",
                    analyzer.nom, len(findings),
                )
            except Exception as e:
                logger.error("Erreur dans %s : %s", analyzer.nom, e)
                all_findings.append(Finding(
                    categorie=FindingCategory.ANOMALIE,
                    severite=Severity.FAIBLE,
                    titre=f"Erreur d'analyse - {analyzer.nom}",
                    description=f"L'analyseur {analyzer.nom} a rencontre une erreur : {e}",
                    score_risque=10,
                    recommandation="Verifier les donnees d'entree.",
                    detecte_par="AnalyzerEngine",
                ))

        # Trier par severite puis par score de risque
        poids_severite = {
            Severity.CRITIQUE: 0,
            Severity.HAUTE: 1,
            Severity.MOYENNE: 2,
            Severity.FAIBLE: 3,
        }
        all_findings.sort(key=lambda f: (poids_severite.get(f.severite, 9), -f.score_risque))

        return all_findings

    def generer_synthese(self, findings: list[Finding]) -> dict:
        """Genere une synthese des findings."""
        par_severite = {}
        par_categorie = {}
        impact_total = sum(f.montant_impact or 0 for f in findings)

        for f in findings:
            par_severite[f.severite.value] = par_severite.get(f.severite.value, 0) + 1
            par_categorie[f.categorie.value] = par_categorie.get(f.categorie.value, 0) + 1

        return {
            "total_findings": len(findings),
            "par_severite": par_severite,
            "par_categorie": par_categorie,
            "impact_financier_total": float(impact_total),
            "score_risque_moyen": (
                sum(f.score_risque for f in findings) / len(findings)
                if findings else 0
            ),
        }
