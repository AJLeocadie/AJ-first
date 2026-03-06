"""Tests exhaustifs du moteur d'analyse et de la deduplication.

Couverture : AnalyzerEngine, deduplication inter-analyzers,
constats structurels, synthese.
"""

import sys
from pathlib import Path
from decimal import Decimal

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.analyzers.analyzer_engine import (
    AnalyzerEngine, _normalize_titre, _dedup_key,
)
from urssaf_analyzer.models.documents import (
    Declaration, Finding, Employeur, Employe, Cotisation,
)
from urssaf_analyzer.config.constants import (
    Severity, FindingCategory, ContributionType,
)


# ==============================
# Normalisation des titres
# ==============================

class TestNormalizeTitre:
    """Tests de la normalisation pour deduplication."""

    def test_accents_removed(self):
        assert "e" in _normalize_titre("éàü")

    def test_lowercase(self):
        result = _normalize_titre("ANOMALIE DETECTEE")
        assert result == result.lower()

    def test_amounts_removed(self):
        result = _normalize_titre("Ecart de 1234.56 EUR")
        assert "1234" not in result
        assert "eur" not in result.lower() or "eur" in _normalize_titre("test")

    def test_percentages_removed(self):
        result = _normalize_titre("Taux incorrect 12.5%")
        assert "12.5" not in result

    def test_multiple_spaces(self):
        result = _normalize_titre("  test   multiple   espaces  ")
        assert "  " not in result


class TestDedupKey:
    """Tests de la generation de cles de deduplication."""

    def test_same_finding_same_key(self):
        f1 = Finding(titre="Anomalie test", categorie=FindingCategory.ANOMALIE)
        f2 = Finding(titre="Anomalie test", categorie=FindingCategory.ANOMALIE)
        assert _dedup_key(f1) == _dedup_key(f2)

    def test_different_category_different_key(self):
        f1 = Finding(titre="Test", categorie=FindingCategory.ANOMALIE)
        f2 = Finding(titre="Test", categorie=FindingCategory.INCOHERENCE)
        assert _dedup_key(f1) != _dedup_key(f2)

    def test_similar_titles_same_key(self):
        f1 = Finding(titre="Ecart de 100 EUR", categorie=FindingCategory.ANOMALIE)
        f2 = Finding(titre="Ecart de 200 EUR", categorie=FindingCategory.ANOMALIE)
        assert _dedup_key(f1) == _dedup_key(f2)


# ==============================
# AnalyzerEngine
# ==============================

class TestAnalyzerEngine:
    """Tests du moteur d'analyse."""

    def _make_declaration(self, **kwargs):
        defaults = {
            "type_declaration": "DSN",
            "employeur": Employeur(
                siret="12345678901234",
                effectif=25,
            ),
            "employes": [Employe(nir="1850175123456", nom="Martin")],
            "cotisations": [
                Cotisation(
                    type_cotisation=ContributionType.MALADIE,
                    base_brute=Decimal("3000"),
                    assiette=Decimal("3000"),
                    taux_patronal=Decimal("0.07"),
                    montant_patronal=Decimal("210"),
                ),
            ],
            "masse_salariale_brute": Decimal("3000"),
            "effectif_declare": 1,
        }
        defaults.update(kwargs)
        return Declaration(**defaults)

    def test_analyse_returns_findings(self):
        engine = AnalyzerEngine(effectif=25)
        decls = [self._make_declaration()]
        findings = engine.analyser(decls)
        assert isinstance(findings, list)

    def test_analyse_sorted_by_severity(self):
        engine = AnalyzerEngine(effectif=25)
        decls = [self._make_declaration()]
        findings = engine.analyser(decls)
        if len(findings) >= 2:
            severity_order = {
                Severity.CRITIQUE: 0,
                Severity.HAUTE: 1,
                Severity.MOYENNE: 2,
                Severity.FAIBLE: 3,
            }
            for i in range(len(findings) - 1):
                assert severity_order.get(findings[i].severite, 9) <= \
                    severity_order.get(findings[i + 1].severite, 9)

    def test_deduplication(self):
        engine = AnalyzerEngine()
        findings = [
            Finding(
                titre="Anomalie test",
                categorie=FindingCategory.ANOMALIE,
                severite=Severity.MOYENNE,
                score_risque=50,
                detecte_par="AnalyzerA",
            ),
            Finding(
                titre="Anomalie test",
                categorie=FindingCategory.ANOMALIE,
                severite=Severity.HAUTE,
                score_risque=80,
                detecte_par="AnalyzerB",
            ),
        ]
        deduped = AnalyzerEngine._deduplicate(findings)
        assert len(deduped) == 1
        assert deduped[0].severite == Severity.HAUTE  # Plus severe conserve
        assert "AnalyzerA" in deduped[0].detecte_par
        assert "AnalyzerB" in deduped[0].detecte_par

    def test_deduplication_keeps_highest_score(self):
        findings = [
            Finding(
                titre="Test",
                categorie=FindingCategory.ANOMALIE,
                severite=Severity.MOYENNE,
                score_risque=30,
                detecte_par="A",
            ),
            Finding(
                titre="Test",
                categorie=FindingCategory.ANOMALIE,
                severite=Severity.MOYENNE,
                score_risque=70,
                detecte_par="B",
            ),
        ]
        deduped = AnalyzerEngine._deduplicate(findings)
        assert len(deduped) == 1
        assert deduped[0].score_risque == 70

    def test_no_dedup_different_findings(self):
        findings = [
            Finding(titre="Anomalie A", categorie=FindingCategory.ANOMALIE, detecte_par="A"),
            Finding(titre="Anomalie B", categorie=FindingCategory.ANOMALIE, detecte_par="B"),
        ]
        deduped = AnalyzerEngine._deduplicate(findings)
        assert len(deduped) == 2


# ==============================
# Constats Structurels
# ==============================

class TestConstatsStructurels:
    """Tests des constats structurels."""

    def test_document_unique_constat(self):
        engine = AnalyzerEngine()
        decls = [Declaration(type_declaration="DSN")]
        findings = engine._constats_structurels(decls)
        titres = [f.titre for f in findings]
        assert any("unique" in t.lower() for t in titres)

    def test_pas_de_constat_unique_multi_docs(self):
        engine = AnalyzerEngine()
        decls = [Declaration(type_declaration="DSN"), Declaration(type_declaration="DSN")]
        findings = engine._constats_structurels(decls)
        titres = [f.titre for f in findings]
        assert not any("unique" in t.lower() for t in titres)

    def test_employeur_manquant_constat(self):
        engine = AnalyzerEngine()
        decls = [Declaration(type_declaration="DSN")]
        findings = engine._constats_structurels(decls)
        titres = [f.titre for f in findings]
        assert any("employeur" in t.lower() for t in titres)

    def test_aucune_cotisation_constat(self):
        engine = AnalyzerEngine()
        decls = [Declaration(type_declaration="DSN")]
        findings = engine._constats_structurels(decls)
        titres = [f.titre for f in findings]
        assert any("cotisation" in t.lower() for t in titres)


# ==============================
# Synthese
# ==============================

class TestSynthese:
    """Tests de la generation de synthese."""

    def test_synthese_vide(self):
        engine = AnalyzerEngine()
        synthese = engine.generer_synthese([])
        assert synthese["total_findings"] == 0
        assert synthese["impact_financier_total"] == 0
        assert synthese["score_risque_moyen"] == 0

    def test_synthese_avec_findings(self):
        engine = AnalyzerEngine()
        findings = [
            Finding(
                severite=Severity.HAUTE,
                categorie=FindingCategory.ANOMALIE,
                montant_impact=Decimal("1000"),
                score_risque=80,
            ),
            Finding(
                severite=Severity.MOYENNE,
                categorie=FindingCategory.INCOHERENCE,
                montant_impact=Decimal("500"),
                score_risque=40,
            ),
        ]
        synthese = engine.generer_synthese(findings)
        assert synthese["total_findings"] == 2
        assert synthese["impact_financier_total"] == 1500.0
        assert synthese["score_risque_moyen"] == 60.0
        assert "haute" in synthese["par_severite"]
        assert "anomalie" in synthese["par_categorie"]
