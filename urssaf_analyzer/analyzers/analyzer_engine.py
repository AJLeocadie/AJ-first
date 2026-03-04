"""Moteur d'analyse coordonnant tous les analyseurs."""

import logging
from decimal import Decimal

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

        # Constats structurels : document unique, employeur manquant
        all_findings.extend(self._constats_structurels(declarations))

        # Trier par severite puis par score de risque
        poids_severite = {
            Severity.CRITIQUE: 0,
            Severity.HAUTE: 1,
            Severity.MOYENNE: 2,
            Severity.FAIBLE: 3,
        }
        all_findings.sort(key=lambda f: (poids_severite.get(f.severite, 9), -f.score_risque))

        return all_findings

    def _constats_structurels(
        self, declarations: list[Declaration],
    ) -> list[Finding]:
        """Genere des constats structurels quand les donnees sont insuffisantes.

        Ces constats identifient les cas ou le score pourrait etre
        artificiellement eleve faute de controles possibles.
        """
        findings: list[Finding] = []

        # 1. Document unique : verification inter-documents impossible
        if len(declarations) == 1:
            findings.append(Finding(
                categorie=FindingCategory.DONNEE_MANQUANTE,
                severite=Severity.MOYENNE,
                titre="Document unique - verification inter-documents impossible",
                description=(
                    "L'analyse ne porte que sur un seul document. "
                    "Les controles de coherence inter-documents (masse salariale, "
                    "effectif, cotisations par employe, SIRET, exonerations) "
                    "n'ont pas pu etre executes. Le score ne reflete que la "
                    "coherence interne du document, pas sa fiabilite croisee."
                ),
                score_risque=40,
                recommandation=(
                    "Pour une analyse fiable, fournir au minimum 2 documents "
                    "couvrant la meme periode (ex: DSN + journal de paie, "
                    "ou DSN + bordereau URSSAF). L'absence de recoupement "
                    "limite significativement la portee de l'audit."
                ),
                detecte_par="AnalyzerEngine",
                reference_legale="NEP 500 - Elements probants (recoupement multi-sources)",
            ))

        # 2. Aucun employeur identifie : controles de seuil impossibles
        has_employeur = any(
            d.employeur and (d.employeur.effectif > 0 or d.employeur.siret)
            for d in declarations
        )
        if not has_employeur and declarations:
            findings.append(Finding(
                categorie=FindingCategory.DONNEE_MANQUANTE,
                severite=Severity.MOYENNE,
                titre="Employeur non identifie - controles de seuil impossibles",
                description=(
                    "Aucune declaration ne contient les donnees de l'employeur "
                    "(SIRET, effectif). Les controles dependant de l'effectif "
                    "(FNAL deplafonne >= 50, versement mobilite >= 11, PEEC >= 20) "
                    "et les verifications SIRET/SIREN n'ont pas pu etre executes. "
                    "Les cotisations obligatoires conditionnelles ne sont pas "
                    "verifiees."
                ),
                score_risque=50,
                recommandation=(
                    "Fournir des documents contenant les donnees de l'employeur "
                    "(SIRET, effectif) pour activer les controles de seuil. "
                    "Sans ces informations, le score peut etre artificiellement "
                    "eleve."
                ),
                detecte_par="AnalyzerEngine",
                reference_legale="Art. R243-14 CSS - Identification de l'etablissement",
            ))

        # 3. Aucun employe identifie : controles individuels impossibles
        has_employes = any(len(d.employes) > 0 for d in declarations)
        if not has_employes and declarations:
            total_cots = sum(len(d.cotisations) for d in declarations)
            if total_cots > 0:
                findings.append(Finding(
                    categorie=FindingCategory.DONNEE_MANQUANTE,
                    severite=Severity.MOYENNE,
                    titre="Aucun employe identifie - controles individuels impossibles",
                    description=(
                        f"Les declarations contiennent {total_cots} ligne(s) de "
                        f"cotisations mais aucun employe identifie (NIR). Les controles "
                        f"individuels (SMIC, net > brut, reconciliation inter-documents "
                        f"par NIR, comparaison des bases par employe) n'ont pas pu "
                        f"etre executes."
                    ),
                    score_risque=45,
                    recommandation=(
                        "Fournir des documents contenant les donnees individuelles "
                        "des salaries (NIR, nom, statut) pour activer les controles "
                        "de coherence par employe."
                    ),
                    detecte_par="AnalyzerEngine",
                    reference_legale="Art. L133-5-3 CSS - DSN nominative",
                ))

        # 4. Declarations sans cotisations
        decls_sans_cots = [
            d for d in declarations
            if not d.cotisations
        ]
        if decls_sans_cots and len(decls_sans_cots) == len(declarations):
            findings.append(Finding(
                categorie=FindingCategory.DONNEE_MANQUANTE,
                severite=Severity.HAUTE,
                titre="Aucune cotisation dans les documents analyses",
                description=(
                    f"Les {len(declarations)} document(s) analyse(s) ne contiennent "
                    f"aucune ligne de cotisation. L'analyse de conformite ne peut "
                    f"porter que sur les metadonnees (effectif, masse salariale). "
                    f"Le score est non significatif sans donnees de cotisations."
                ),
                score_risque=60,
                recommandation=(
                    "Verifier que les documents ont ete correctement importes "
                    "et que les cotisations ont ete extraites. Fournir des "
                    "documents contenant des lignes de cotisations detaillees."
                ),
                detecte_par="AnalyzerEngine",
            ))

        # 5. Accumulation d'incoherences inter-documents = alerte aggregate
        if len(declarations) >= 2:
            nb_incoherences = sum(
                1 for f in findings
                if f.categorie == FindingCategory.INCOHERENCE
            )
            # Note: les incoherences comptees ici sont uniquement les structurelles.
            # Les incoherences des analyseurs sont dans all_findings (caller).
            # Ce constat sera ajoute apres le tri, donc on ne peut pas compter
            # les incoherences des analyseurs ici. Ce constat est un placeholder
            # pour le cas ou des constats structurels ont genere des incoherences.

        return findings

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
