"""Moteur d'analyse coordonnant tous les analyseurs.

Inclut la deduplication inter-analyzers (SPEC §3.3) :
plusieurs analyseurs peuvent detecter le meme probleme sous des angles differents.
La deduplication garantit qu'un meme constat n'est pas compte deux fois
dans le scoring, evitant de penaliser injustement l'entite auditee.
"""

import logging
import re
import unicodedata
from decimal import Decimal

from urssaf_analyzer.analyzers.anomaly_detector import AnomalyDetector
from urssaf_analyzer.analyzers.consistency_checker import ConsistencyChecker
from urssaf_analyzer.analyzers.pattern_analyzer import PatternAnalyzer
from urssaf_analyzer.config.constants import Severity, FindingCategory
from urssaf_analyzer.models.documents import Declaration, Finding, AnalysisResult

logger = logging.getLogger("urssaf_analyzer.engine")


def _normalize_titre(titre: str) -> str:
    """Normalise un titre de finding pour la deduplication.

    - Supprime accents et diacritiques
    - Minuscules
    - Supprime ponctuation et espaces multiples
    - Supprime les suffixes numeriques variables (montants, pourcentages)
    """
    nfkd = unicodedata.normalize("NFKD", titre)
    sans_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    normalized = sans_accents.lower()
    # Supprimer les montants et pourcentages (ex: "1234.56 EUR", "12.5%")
    normalized = re.sub(r"\d+[.,]?\d*\s*(%|eur|euros?)\b", "", normalized)
    # Supprimer les nombres isoles
    normalized = re.sub(r"\b\d+[.,]?\d*\b", "", normalized)
    # Supprimer la ponctuation
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    # Espaces multiples -> simple
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _dedup_key(finding: Finding) -> str:
    """Genere une cle de deduplication pour un finding.

    Deux findings sont consideres comme doublons s'ils partagent
    le meme titre normalise et la meme categorie.
    """
    titre_norm = _normalize_titre(finding.titre)
    return f"{titre_norm}|{finding.categorie.value}"


class AnalyzerEngine:
    """Coordonne l'execution de tous les analyseurs et agregue les resultats."""

    def __init__(self, effectif: int = 0):
        self.analyzers = [
            AnomalyDetector(effectif=effectif),
            ConsistencyChecker(),
            PatternAnalyzer(),
        ]
        self._pre_dedup_count = 0
        self._post_dedup_count = 0

    def analyser(self, declarations: list[Declaration]) -> list[Finding]:
        """Execute tous les analyseurs et retourne les findings dedupliques."""
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

        # Deduplication inter-analyzers (SPEC §3.3)
        self._pre_dedup_count = len(all_findings)
        all_findings = self._deduplicate(all_findings)
        self._post_dedup_count = len(all_findings)

        if self._pre_dedup_count != self._post_dedup_count:
            logger.info(
                "Deduplication : %d -> %d constats (%d doublons supprimes)",
                self._pre_dedup_count,
                self._post_dedup_count,
                self._pre_dedup_count - self._post_dedup_count,
            )

        # Trier par severite puis par score de risque
        poids_severite = {
            Severity.CRITIQUE: 0,
            Severity.HAUTE: 1,
            Severity.MOYENNE: 2,
            Severity.FAIBLE: 3,
        }
        all_findings.sort(key=lambda f: (poids_severite.get(f.severite, 9), -f.score_risque))

        return all_findings

    @staticmethod
    def _deduplicate(findings: list[Finding]) -> list[Finding]:
        """Deduplique les findings en conservant le plus severe.

        Algorithme :
        1. Pour chaque finding, calculer une cle (titre_normalise, categorie)
        2. Si deux findings partagent la meme cle, garder celui de severite
           la plus haute (CRITIQUE > HAUTE > MOYENNE > FAIBLE)
        3. A severite egale, garder celui avec le score_risque le plus eleve
        4. Fusionner les detecte_par pour tracer tous les analyseurs source
        """
        severity_rank = {
            Severity.CRITIQUE: 4,
            Severity.HAUTE: 3,
            Severity.MOYENNE: 2,
            Severity.FAIBLE: 1,
        }

        best_by_key: dict[str, Finding] = {}
        sources_by_key: dict[str, set[str]] = {}

        for f in findings:
            key = _dedup_key(f)
            f_rank = severity_rank.get(f.severite, 0)

            if key not in best_by_key:
                best_by_key[key] = f
                sources_by_key[key] = {f.detecte_par}
            else:
                existing = best_by_key[key]
                existing_rank = severity_rank.get(existing.severite, 0)
                sources_by_key[key].add(f.detecte_par)

                if f_rank > existing_rank or (
                    f_rank == existing_rank and f.score_risque > existing.score_risque
                ):
                    best_by_key[key] = f

        # Annoter les findings retenus avec tous les analyseurs source
        result = []
        for key, f in best_by_key.items():
            sources = sources_by_key[key]
            if len(sources) > 1:
                f.detecte_par = " + ".join(sorted(sources))
            result.append(f)

        return result

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
                reference_legale="Art. L241-1 CSS - Cotisations de securite sociale obligatoires",
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
