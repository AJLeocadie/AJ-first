"""Analyseur de patterns suspects.

Detecte :
- Nombres ronds suspects (montants toujours arrondis)
- Doublons (declarations identiques)
- Anomalies temporelles (mois manquants)
- Loi de Benford (distribution anormale du premier chiffre)
- Outliers statistiques (methode IQR)
"""

import math
from collections import Counter
from decimal import Decimal
from typing import Optional

from urssaf_analyzer.analyzers.base_analyzer import BaseAnalyzer
from urssaf_analyzer.config.constants import (
    Severity, FindingCategory,
    SEUIL_NOMBRES_RONDS_PCT, SEUIL_BENFORD_CHI2, SEUIL_OUTLIER_IQR,
)
from urssaf_analyzer.models.documents import Declaration, Finding, Cotisation

# Distribution theorique de Benford pour le premier chiffre
BENFORD_EXPECTED = {
    1: 0.301, 2: 0.176, 3: 0.125, 4: 0.097,
    5: 0.079, 6: 0.067, 7: 0.058, 8: 0.051, 9: 0.046,
}


class PatternAnalyzer(BaseAnalyzer):
    """Analyse les patterns statistiques pour detecter les irregularites."""

    @property
    def nom(self) -> str:
        return "Analyseur de patterns"

    def analyser(self, declarations: list[Declaration]) -> list[Finding]:
        findings = []
        toutes_cotisations = []
        for decl in declarations:
            toutes_cotisations.extend(decl.cotisations)

        if not toutes_cotisations:
            return findings

        findings.extend(self._detecter_nombres_ronds(toutes_cotisations))
        findings.extend(self._detecter_doublons(declarations))
        findings.extend(self._detecter_anomalies_temporelles(declarations))
        findings.extend(self._appliquer_benford(toutes_cotisations))
        findings.extend(self._detecter_outliers(toutes_cotisations))

        return findings

    def _detecter_nombres_ronds(self, cotisations: list[Cotisation]) -> list[Finding]:
        """Detecte une proportion anormale de montants arrondis."""
        findings = []
        montants = [c.montant_patronal for c in cotisations if c.montant_patronal > 0]
        if len(montants) < 10:
            return findings

        # Nombres ronds = divisibles par 100
        ronds = sum(1 for m in montants if m % 100 == 0)
        ratio = Decimal(str(ronds)) / Decimal(str(len(montants)))

        if ratio > SEUIL_NOMBRES_RONDS_PCT:
            findings.append(Finding(
                categorie=FindingCategory.PATTERN_SUSPECT,
                severite=Severity.FAIBLE,
                titre="Proportion elevee de montants arrondis",
                description=(
                    f"{ronds}/{len(montants)} montants ({ratio:.0%}) sont des nombres "
                    f"ronds (divisibles par 100). Ce pattern peut indiquer une "
                    f"estimation plutot qu'un calcul reel. Cependant, certains baremes "
                    f"reglementaires produisent legitimement des montants ronds. "
                    f"Indicateur statistique non probant a lui seul."
                ),
                score_risque=25,
                recommandation=(
                    "Indicateur a croiser avec d'autres constats. "
                    "Verifier que les montants de cotisations sont effectivement "
                    "calcules et non estimes ou forfaitises."
                ),
                detecte_par=self.nom,
            ))
        return findings

    def _detecter_doublons(self, declarations: list[Declaration]) -> list[Finding]:
        """Detecte les declarations ou lignes en doublon."""
        findings = []
        vus = {}

        for decl in declarations:
            for c in decl.cotisations:
                cle = (
                    c.type_cotisation, c.employe_id,
                    str(c.base_brute), str(c.montant_patronal),
                    str(c.periode) if c.periode else "",
                )
                if cle in vus:
                    doc_ids = [c.source_document_id, vus[cle]]
                    findings.append(Finding(
                        categorie=FindingCategory.PATTERN_SUSPECT,
                        severite=Severity.HAUTE,
                        titre=f"Doublon detecte - {c.type_cotisation.value}",
                        description=(
                            f"Ligne de cotisation identique trouvee dans plusieurs "
                            f"documents : {c.type_cotisation.value}, base={c.base_brute}, "
                            f"montant={c.montant_patronal}."
                        ),
                        montant_impact=c.montant_patronal,
                        score_risque=75,
                        recommandation=(
                            "Verifier s'il s'agit d'un doublon accidentel (double soumission) "
                            "ou de deux declarations distinctes."
                        ),
                        detecte_par=self.nom,
                        documents_concernes=doc_ids,
                    ))
                else:
                    vus[cle] = c.source_document_id

        return findings

    def _detecter_anomalies_temporelles(self, declarations: list[Declaration]) -> list[Finding]:
        """Detecte les mois manquants dans les declarations."""
        findings = []
        mois_declares = set()

        for decl in declarations:
            if decl.periode:
                mois_declares.add((decl.periode.debut.year, decl.periode.debut.month))

        if len(mois_declares) < 3:
            return findings

        # Trouver la plage
        annee_min = min(m[0] for m in mois_declares)
        mois_min = min(m[1] for m in mois_declares if m[0] == annee_min)
        annee_max = max(m[0] for m in mois_declares)
        mois_max = max(m[1] for m in mois_declares if m[0] == annee_max)

        mois_attendus = set()
        y, m = annee_min, mois_min
        while (y, m) <= (annee_max, mois_max):
            mois_attendus.add((y, m))
            m += 1
            if m > 12:
                m = 1
                y += 1

        mois_manquants = mois_attendus - mois_declares
        if mois_manquants:
            mois_str = ", ".join(f"{m:02d}/{y}" for y, m in sorted(mois_manquants))
            # Adapter la severite selon le ratio de mois manquants
            # Si > 50% des mois manquent, c'est probablement un audit par sondage
            ratio_manquants = len(mois_manquants) / len(mois_attendus) if mois_attendus else 0
            severite = Severity.MOYENNE if ratio_manquants > 0.5 else Severity.HAUTE
            findings.append(Finding(
                categorie=FindingCategory.DONNEE_MANQUANTE,
                severite=severite,
                titre="Mois de declaration manquants",
                description=(
                    f"Les mois suivants sont absents des declarations : {mois_str}. "
                    f"Cela peut indiquer des declarations non transmises, ou un "
                    f"perimetre d'audit par sondage (echantillonnage). "
                    f"{'Proportion elevee de mois manquants : audit par sondage probable.' if ratio_manquants > 0.5 else ''}"
                ),
                score_risque=50 if ratio_manquants > 0.5 else 80,
                recommandation=(
                    "Verifier si l'absence de certains mois resulte d'un choix "
                    "d'echantillonnage (audit par sondage) ou d'un defaut de transmission. "
                    "En cas d'audit par sondage, ce constat n'est pas significatif."
                ),
                detecte_par=self.nom,
                reference_legale="Art. L133-5-3 CSS - Obligation de declaration mensuelle (DSN)",
            ))

        return findings

    def _appliquer_benford(self, cotisations: list[Cotisation]) -> list[Finding]:
        """Applique la loi de Benford pour detecter la manipulation de donnees."""
        findings = []
        montants = [float(c.montant_patronal) for c in cotisations if c.montant_patronal > 0]

        if len(montants) < 50:
            return findings  # Pas assez de donnees

        # Extraire le premier chiffre
        premiers_chiffres = []
        for m in montants:
            s = str(abs(m)).lstrip("0").lstrip(".")
            if s and s[0].isdigit() and s[0] != "0":
                premiers_chiffres.append(int(s[0]))

        if len(premiers_chiffres) < 50:
            return findings

        # Distribution observee
        counts = Counter(premiers_chiffres)
        n = len(premiers_chiffres)

        # Test chi-deux
        chi2 = 0.0
        for digit in range(1, 10):
            observed = counts.get(digit, 0)
            expected = BENFORD_EXPECTED[digit] * n
            if expected > 0:
                chi2 += ((observed - expected) ** 2) / expected

        if chi2 > float(SEUIL_BENFORD_CHI2):
            # Distribution anormale
            details_parts = []
            for d in range(1, 10):
                obs_pct = counts.get(d, 0) / n * 100
                exp_pct = BENFORD_EXPECTED[d] * 100
                details_parts.append(f"  Chiffre {d}: observe={obs_pct:.1f}%, attendu={exp_pct:.1f}%")
            details = "\n".join(details_parts)

            findings.append(Finding(
                categorie=FindingCategory.PATTERN_SUSPECT,
                severite=Severity.FAIBLE,
                titre="Distribution non conforme a la loi de Benford",
                description=(
                    f"La distribution des premiers chiffres des montants de cotisations "
                    f"ne suit pas la loi de Benford (chi2={chi2:.2f}, seuil={SEUIL_BENFORD_CHI2}). "
                    f"ATTENTION : les cotisations sociales (salaire x taux reglementaire) ne suivent "
                    f"pas necessairement la loi de Benford. Ce constat est un indicateur statistique "
                    f"non probant, insuffisant a lui seul pour etablir une irregularite.\n{details}"
                ),
                score_risque=15,
                recommandation=(
                    "Indicateur statistique a interpreter avec prudence. "
                    "La non-conformite a Benford sur des montants de cotisations (derives de "
                    "salaires x taux fixes) n'est PAS une preuve de fraude et ne constitue "
                    "pas un element probant au sens de l'art. L243-7 CSS. "
                    "A croiser avec d'autres constats avant toute conclusion."
                ),
                detecte_par=self.nom,
            ))

        return findings

    def _detecter_outliers(self, cotisations: list[Cotisation]) -> list[Finding]:
        """Detecte les valeurs aberrantes par la methode IQR."""
        findings = []

        # Regrouper par type de cotisation
        par_type: dict[str, list[Cotisation]] = {}
        for c in cotisations:
            key = c.type_cotisation.value
            if key not in par_type:
                par_type[key] = []
            par_type[key].append(c)

        for type_cot, cots in par_type.items():
            montants = sorted([float(c.montant_patronal) for c in cots if c.montant_patronal > 0])
            if len(montants) < 10:
                continue

            q1_idx = len(montants) // 4
            q3_idx = 3 * len(montants) // 4
            q1 = montants[q1_idx]
            q3 = montants[q3_idx]
            iqr = q3 - q1

            if iqr == 0:
                continue

            lower = q1 - float(SEUIL_OUTLIER_IQR) * iqr
            upper = q3 + float(SEUIL_OUTLIER_IQR) * iqr

            outliers = [c for c in cots if float(c.montant_patronal) < lower or float(c.montant_patronal) > upper]

            for c in outliers[:5]:  # Limiter a 5 outliers par type
                findings.append(Finding(
                    categorie=FindingCategory.PATTERN_SUSPECT,
                    severite=Severity.FAIBLE,
                    titre=f"Valeur atypique - {type_cot}",
                    description=(
                        f"Le montant {c.montant_patronal} pour {type_cot} "
                        f"est statistiquement atypique (intervalle normal : "
                        f"{lower:.2f} - {upper:.2f}). "
                        f"Les ecarts de remuneration (dirigeant, cadre superieur) "
                        f"sont une cause frequente de faux positif. "
                        f"Indicateur statistique non probant a lui seul."
                    ),
                    montant_impact=c.montant_patronal,
                    score_risque=20,
                    recommandation="Verifier si ce montant est justifie par le niveau de remuneration (dirigeant, cadre).",
                    detecte_par=self.nom,
                    documents_concernes=[c.source_document_id],
                ))

        return findings
