"""Verificateur de coherence inter-documents.

Detecte les incoherences entre :
- Declarations DSN et documents comptables
- Masse salariale declaree vs calculee
- Effectifs declares vs employes identifies
- Cotisations entre periodes successives
"""

from decimal import Decimal

from urssaf_analyzer.analyzers.base_analyzer import BaseAnalyzer
from urssaf_analyzer.config.constants import (
    Severity, FindingCategory, TOLERANCE_MONTANT, TOLERANCE_ARRONDI_PCT,
)
from urssaf_analyzer.models.documents import Declaration, Finding
from urssaf_analyzer.utils.number_utils import ecart_relatif


class ConsistencyChecker(BaseAnalyzer):
    """Verifie la coherence entre les differents documents."""

    @property
    def nom(self) -> str:
        return "Verificateur de coherence"

    def analyser(self, declarations: list[Declaration]) -> list[Finding]:
        findings = []

        for decl in declarations:
            findings.extend(self._verifier_coherence_interne(decl))

        if len(declarations) > 1:
            findings.extend(self._verifier_coherence_inter_documents(declarations))
            findings.extend(self._verifier_coherence_temporelle(declarations))

        return findings

    def _verifier_coherence_interne(self, decl: Declaration) -> list[Finding]:
        """Verifie la coherence interne d'une declaration."""
        findings = []

        # 1. Masse salariale declaree vs somme des bases brutes
        if decl.cotisations and decl.masse_salariale_brute > 0:
            somme_bases = sum(c.base_brute for c in decl.cotisations if c.base_brute > 0)
            if somme_bases > 0:
                # La somme des bases est normalement > masse salariale
                # car une meme base est utilisee pour plusieurs cotisations
                # Mais la masse salariale ne doit pas etre > a une base individuelle max
                bases_uniques = set()
                for c in decl.cotisations:
                    if c.base_brute > 0:
                        bases_uniques.add(c.base_brute)

                if bases_uniques:
                    max_base = max(bases_uniques)
                    if decl.masse_salariale_brute > max_base * Decimal("1.5"):
                        ecart = decl.masse_salariale_brute - max_base
                        findings.append(Finding(
                            categorie=FindingCategory.INCOHERENCE,
                            severite=Severity.MOYENNE,
                            titre="Ecart masse salariale / bases de cotisations",
                            description=(
                                f"La masse salariale declaree ({decl.masse_salariale_brute}) "
                                f"est significativement superieure aux bases de cotisation "
                                f"(max : {max_base}). Ecart : {ecart}."
                            ),
                            montant_impact=ecart,
                            score_risque=55,
                            recommandation=(
                                "Verifier la coherence entre la masse salariale declaree "
                                "et les lignes de cotisations."
                            ),
                            detecte_par=self.nom,
                            documents_concernes=[decl.source_document_id],
                        ))

        # 2. Effectif declare vs employes identifies
        if decl.effectif_declare > 0 and decl.employes:
            nb_employes = len(decl.employes)
            if nb_employes != decl.effectif_declare:
                ecart = abs(nb_employes - decl.effectif_declare)
                severite = Severity.HAUTE if ecart > 5 else Severity.MOYENNE
                findings.append(Finding(
                    categorie=FindingCategory.INCOHERENCE,
                    severite=severite,
                    titre="Ecart effectif declare / employes identifies",
                    description=(
                        f"L'effectif declare ({decl.effectif_declare}) ne correspond pas "
                        f"au nombre d'employes identifies ({nb_employes}). "
                        f"Ecart : {ecart}."
                    ),
                    valeur_constatee=str(nb_employes),
                    valeur_attendue=str(decl.effectif_declare),
                    score_risque=65,
                    recommandation=(
                        "Verifier la completude des declarations individuelles. "
                        "Un ecart peut indiquer des salaries non declares."
                    ),
                    detecte_par=self.nom,
                    documents_concernes=[decl.source_document_id],
                    reference_legale="Art. L242-1 CSS",
                ))

        # 3. Cotisations sans base ou sans montant
        for c in decl.cotisations:
            if c.base_brute > 0 and c.montant_patronal == 0 and c.taux_patronal > 0:
                findings.append(Finding(
                    categorie=FindingCategory.INCOHERENCE,
                    severite=Severity.MOYENNE,
                    titre=f"Cotisation avec base mais sans montant - {c.type_cotisation.value}",
                    description=(
                        f"La cotisation {c.type_cotisation.value} a une base "
                        f"de {c.base_brute} et un taux de {c.taux_patronal} "
                        f"mais un montant patronal de 0."
                    ),
                    montant_impact=c.base_brute * c.taux_patronal,
                    score_risque=50,
                    recommandation="Verifier si une exoneration s'applique, sinon corriger.",
                    detecte_par=self.nom,
                    documents_concernes=[c.source_document_id],
                ))

        return findings

    def _verifier_coherence_inter_documents(self, declarations: list[Declaration]) -> list[Finding]:
        """Compare les declarations entre elles."""
        findings = []

        # Regrouper par periode pour comparer
        par_periode = {}
        for decl in declarations:
            if decl.periode:
                key = (decl.periode.debut, decl.periode.fin)
                if key not in par_periode:
                    par_periode[key] = []
                par_periode[key].append(decl)

        for periode, decls in par_periode.items():
            if len(decls) < 2:
                continue

            # Comparer les masses salariales entre documents de meme periode
            masses = [(d, d.masse_salariale_brute) for d in decls if d.masse_salariale_brute > 0]
            if len(masses) >= 2:
                for i in range(len(masses)):
                    for j in range(i + 1, len(masses)):
                        d1, m1 = masses[i]
                        d2, m2 = masses[j]
                        ecart = ecart_relatif(m1, m2)
                        if ecart > TOLERANCE_ARRONDI_PCT:
                            findings.append(Finding(
                                categorie=FindingCategory.INCOHERENCE,
                                severite=Severity.HAUTE,
                                titre="Incoherence masse salariale entre documents",
                                description=(
                                    f"Ecart de {ecart:.1%} entre les masses salariales "
                                    f"declarees pour la meme periode ({periode[0]} - {periode[1]}). "
                                    f"Document 1 ({d1.type_declaration}): {m1}, "
                                    f"Document 2 ({d2.type_declaration}): {m2}."
                                ),
                                montant_impact=abs(m1 - m2),
                                score_risque=75,
                                recommandation=(
                                    "Identifier la source de l'ecart et reconcilier "
                                    "les declarations."
                                ),
                                detecte_par=self.nom,
                                documents_concernes=[d1.source_document_id, d2.source_document_id],
                            ))

        return findings

    def _verifier_coherence_temporelle(self, declarations: list[Declaration]) -> list[Finding]:
        """Verifie la coherence entre periodes successives."""
        findings = []

        decls_triees = sorted(
            [d for d in declarations if d.periode],
            key=lambda d: d.periode.debut,
        )

        for i in range(1, len(decls_triees)):
            prev = decls_triees[i - 1]
            curr = decls_triees[i]

            if prev.masse_salariale_brute > 0 and curr.masse_salariale_brute > 0:
                variation = ecart_relatif(curr.masse_salariale_brute, prev.masse_salariale_brute)
                if variation > Decimal("0.5"):  # Variation > 50%
                    findings.append(Finding(
                        categorie=FindingCategory.ANOMALIE,
                        severite=Severity.MOYENNE,
                        titre="Variation importante de masse salariale",
                        description=(
                            f"La masse salariale varie de {variation:.1%} entre "
                            f"{prev.periode.debut} ({prev.masse_salariale_brute}) et "
                            f"{curr.periode.debut} ({curr.masse_salariale_brute})."
                        ),
                        montant_impact=abs(curr.masse_salariale_brute - prev.masse_salariale_brute),
                        score_risque=45,
                        recommandation=(
                            "Verifier si cette variation est justifiee (embauches, licenciements, "
                            "primes exceptionnelles)."
                        ),
                        detecte_par=self.nom,
                        documents_concernes=[prev.source_document_id, curr.source_document_id],
                    ))

        return findings
