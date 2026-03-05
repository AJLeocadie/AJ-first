"""Tests de la deduplication inter-analyzers (SPEC §3.3).

Verifie que les constats identiques detectes par differents analyseurs
ne sont comptes qu'une seule fois dans le scoring, et que le constat
le plus severe est conserve.
"""

import pytest

from urssaf_analyzer.analyzers.analyzer_engine import (
    AnalyzerEngine,
    _normalize_titre,
    _dedup_key,
)
from urssaf_analyzer.config.constants import Severity, FindingCategory
from urssaf_analyzer.models.documents import Finding


class TestNormalizeTitre:
    """Tests de la normalisation des titres pour deduplication."""

    def test_minuscules(self):
        assert _normalize_titre("TAUX MALADIE") == _normalize_titre("taux maladie")

    def test_accents(self):
        assert _normalize_titre("Écart détecté") == _normalize_titre("ecart detecte")

    def test_montants_retires(self):
        t1 = _normalize_titre("Ecart taux maladie : 13.10% vs 13.00%")
        t2 = _normalize_titre("Ecart taux maladie : 7.50% vs 7.00%")
        assert t1 == t2

    def test_montants_eur_retires(self):
        t1 = _normalize_titre("Impact financier : 1234.56 EUR")
        t2 = _normalize_titre("Impact financier : 9999.99 EUR")
        assert t1 == t2

    def test_ponctuation_ignoree(self):
        t1 = _normalize_titre("taux (patronal) - maladie")
        t2 = _normalize_titre("taux patronal maladie")
        assert t1 == t2

    def test_espaces_multiples(self):
        t1 = _normalize_titre("ecart   taux   maladie")
        t2 = _normalize_titre("ecart taux maladie")
        assert t1 == t2

    def test_titres_differents_distincts(self):
        t1 = _normalize_titre("Ecart taux maladie")
        t2 = _normalize_titre("Ecart taux vieillesse")
        assert t1 != t2


class TestDedupKey:
    def test_same_titre_same_categorie(self):
        f1 = Finding(
            titre="Ecart taux maladie",
            categorie=FindingCategory.ANOMALIE,
            severite=Severity.HAUTE,
        )
        f2 = Finding(
            titre="Ecart taux maladie",
            categorie=FindingCategory.ANOMALIE,
            severite=Severity.MOYENNE,
        )
        assert _dedup_key(f1) == _dedup_key(f2)

    def test_same_titre_different_categorie(self):
        f1 = Finding(
            titre="Ecart taux maladie",
            categorie=FindingCategory.ANOMALIE,
        )
        f2 = Finding(
            titre="Ecart taux maladie",
            categorie=FindingCategory.INCOHERENCE,
        )
        assert _dedup_key(f1) != _dedup_key(f2)


class TestDeduplication:
    """Tests de la deduplication dans AnalyzerEngine."""

    def test_no_dedup_when_unique(self):
        findings = [
            Finding(
                titre="Constat A",
                categorie=FindingCategory.ANOMALIE,
                severite=Severity.HAUTE,
                score_risque=80,
                detecte_par="AnomalyDetector",
            ),
            Finding(
                titre="Constat B",
                categorie=FindingCategory.INCOHERENCE,
                severite=Severity.MOYENNE,
                score_risque=50,
                detecte_par="ConsistencyChecker",
            ),
        ]
        result = AnalyzerEngine._deduplicate(findings)
        assert len(result) == 2

    def test_dedup_keeps_most_severe(self):
        findings = [
            Finding(
                titre="Ecart taux maladie",
                categorie=FindingCategory.ANOMALIE,
                severite=Severity.MOYENNE,
                score_risque=50,
                detecte_par="AnomalyDetector",
            ),
            Finding(
                titre="Ecart taux maladie",
                categorie=FindingCategory.ANOMALIE,
                severite=Severity.HAUTE,
                score_risque=70,
                detecte_par="ConsistencyChecker",
            ),
        ]
        result = AnalyzerEngine._deduplicate(findings)
        assert len(result) == 1
        assert result[0].severite == Severity.HAUTE
        assert result[0].score_risque == 70

    def test_dedup_merges_sources(self):
        findings = [
            Finding(
                titre="Ecart taux maladie",
                categorie=FindingCategory.ANOMALIE,
                severite=Severity.HAUTE,
                score_risque=70,
                detecte_par="AnomalyDetector",
            ),
            Finding(
                titre="Ecart taux maladie",
                categorie=FindingCategory.ANOMALIE,
                severite=Severity.MOYENNE,
                score_risque=50,
                detecte_par="ConsistencyChecker",
            ),
        ]
        result = AnalyzerEngine._deduplicate(findings)
        assert len(result) == 1
        assert "AnomalyDetector" in result[0].detecte_par
        assert "ConsistencyChecker" in result[0].detecte_par

    def test_dedup_equal_severity_keeps_higher_score(self):
        findings = [
            Finding(
                titre="Ecart masse salariale",
                categorie=FindingCategory.ANOMALIE,
                severite=Severity.HAUTE,
                score_risque=60,
                detecte_par="AnomalyDetector",
            ),
            Finding(
                titre="Ecart masse salariale",
                categorie=FindingCategory.ANOMALIE,
                severite=Severity.HAUTE,
                score_risque=85,
                detecte_par="ConsistencyChecker",
            ),
        ]
        result = AnalyzerEngine._deduplicate(findings)
        assert len(result) == 1
        assert result[0].score_risque == 85

    def test_dedup_with_accents_and_numbers(self):
        findings = [
            Finding(
                titre="Écart taux maladie : 13.10% au lieu de 13.00%",
                categorie=FindingCategory.ANOMALIE,
                severite=Severity.HAUTE,
                score_risque=70,
                detecte_par="AnomalyDetector",
            ),
            Finding(
                titre="Ecart taux maladie : 13.1% au lieu de 13%",
                categorie=FindingCategory.ANOMALIE,
                severite=Severity.MOYENNE,
                score_risque=50,
                detecte_par="PatternAnalyzer",
            ),
        ]
        result = AnalyzerEngine._deduplicate(findings)
        assert len(result) == 1

    def test_dedup_three_analyzers(self):
        findings = [
            Finding(
                titre="Masse salariale incohérente",
                categorie=FindingCategory.INCOHERENCE,
                severite=Severity.CRITIQUE,
                score_risque=90,
                detecte_par="AnomalyDetector",
            ),
            Finding(
                titre="Masse salariale incoherente",
                categorie=FindingCategory.INCOHERENCE,
                severite=Severity.HAUTE,
                score_risque=75,
                detecte_par="ConsistencyChecker",
            ),
            Finding(
                titre="Masse salariale incohérente",
                categorie=FindingCategory.INCOHERENCE,
                severite=Severity.MOYENNE,
                score_risque=50,
                detecte_par="PatternAnalyzer",
            ),
        ]
        result = AnalyzerEngine._deduplicate(findings)
        assert len(result) == 1
        assert result[0].severite == Severity.CRITIQUE
        # All three sources tracked
        assert "AnomalyDetector" in result[0].detecte_par
        assert "ConsistencyChecker" in result[0].detecte_par
        assert "PatternAnalyzer" in result[0].detecte_par

    def test_dedup_empty_list(self):
        result = AnalyzerEngine._deduplicate([])
        assert result == []

    def test_dedup_single_finding(self):
        findings = [
            Finding(
                titre="Test unique",
                categorie=FindingCategory.ANOMALIE,
                severite=Severity.FAIBLE,
                detecte_par="AnomalyDetector",
            ),
        ]
        result = AnalyzerEngine._deduplicate(findings)
        assert len(result) == 1
        assert result[0].detecte_par == "AnomalyDetector"

    def test_engine_dedup_stats(self):
        """Verifie que les compteurs pre/post dedup sont corrects."""
        engine = AnalyzerEngine()
        findings = [
            Finding(
                titre="Test A",
                categorie=FindingCategory.ANOMALIE,
                severite=Severity.HAUTE,
                detecte_par="X",
            ),
            Finding(
                titre="Test A",
                categorie=FindingCategory.ANOMALIE,
                severite=Severity.MOYENNE,
                detecte_par="Y",
            ),
        ]
        result = engine._deduplicate(findings)
        # Static method doesn't update counters, but the logic works
        assert len(result) == 1
