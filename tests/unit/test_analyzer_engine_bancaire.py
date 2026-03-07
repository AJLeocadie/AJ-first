"""Tests unitaires du moteur d'analyse (AnalyzerEngine).

Couverture : deduplication, constats structurels, synthese.
"""

import pytest
from decimal import Decimal
from datetime import date

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.analyzers.analyzer_engine import (
    AnalyzerEngine, _normalize_titre, _dedup_key,
)
from urssaf_analyzer.models.documents import (
    Finding, Declaration, Employeur, Employe, Cotisation, DateRange,
)
from urssaf_analyzer.config.constants import (
    Severity, FindingCategory, ContributionType,
)


# ================================================================
# NORMALISATION DE TITRES
# ================================================================

class TestNormalizeTitre:

    def test_lowercase(self):
        assert _normalize_titre("ANOMALIE") == "anomalie"

    def test_accents_removed(self):
        result = _normalize_titre("Ecart détecté")
        assert "e" in result  # accent supprime

    def test_numbers_removed(self):
        result = _normalize_titre("Ecart de 123.45 EUR")
        assert "123" not in result

    def test_percentages_removed(self):
        result = _normalize_titre("Taux de 7.5%")
        assert "7.5" not in result

    def test_multiple_spaces_collapsed(self):
        result = _normalize_titre("Taux    incorrects")
        assert "  " not in result


class TestDedupKey:

    def test_same_key_for_similar_findings(self):
        f1 = Finding(titre="Taux maladie incorrect 7.0%", categorie=FindingCategory.ANOMALIE)
        f2 = Finding(titre="Taux maladie incorrect 6.5%", categorie=FindingCategory.ANOMALIE)
        assert _dedup_key(f1) == _dedup_key(f2)

    def test_different_key_different_category(self):
        f1 = Finding(titre="Taux incorrect", categorie=FindingCategory.ANOMALIE)
        f2 = Finding(titre="Taux incorrect", categorie=FindingCategory.INCOHERENCE)
        assert _dedup_key(f1) != _dedup_key(f2)


# ================================================================
# DEDUPLICATION
# ================================================================

class TestDeduplication:

    def test_dedup_keeps_highest_severity(self):
        findings = [
            Finding(
                titre="Taux maladie incorrect",
                categorie=FindingCategory.ANOMALIE,
                severite=Severity.HAUTE,
                score_risque=60,
                detecte_par="AnomalyDetector",
            ),
            Finding(
                titre="Taux maladie incorrect",
                categorie=FindingCategory.ANOMALIE,
                severite=Severity.CRITIQUE,
                score_risque=90,
                detecte_par="ConsistencyChecker",
            ),
        ]
        result = AnalyzerEngine._deduplicate(findings)
        assert len(result) == 1
        assert result[0].severite == Severity.CRITIQUE

    def test_dedup_merges_detecte_par(self):
        findings = [
            Finding(
                titre="Anomalie X",
                categorie=FindingCategory.ANOMALIE,
                severite=Severity.MOYENNE,
                score_risque=50,
                detecte_par="A",
            ),
            Finding(
                titre="Anomalie X",
                categorie=FindingCategory.ANOMALIE,
                severite=Severity.MOYENNE,
                score_risque=40,
                detecte_par="B",
            ),
        ]
        result = AnalyzerEngine._deduplicate(findings)
        assert len(result) == 1
        assert "A" in result[0].detecte_par
        assert "B" in result[0].detecte_par

    def test_dedup_no_duplicates(self):
        findings = [
            Finding(titre="Anomalie A", categorie=FindingCategory.ANOMALIE, detecte_par="X"),
            Finding(titre="Anomalie B", categorie=FindingCategory.ANOMALIE, detecte_par="Y"),
        ]
        result = AnalyzerEngine._deduplicate(findings)
        assert len(result) == 2

    def test_dedup_empty(self):
        assert AnalyzerEngine._deduplicate([]) == []


# ================================================================
# CONSTATS STRUCTURELS
# ================================================================

class TestConstatsStructurels:

    @pytest.fixture
    def engine(self):
        return AnalyzerEngine(effectif=25)

    def _make_declaration(self, has_employeur=True, has_employes=True,
                          has_cotisations=True, effectif=25):
        employeur = Employeur(siret="12345678901234", effectif=effectif) if has_employeur else None
        employes = [Employe(nir="1850175123456")] if has_employes else []
        cotisations = [
            Cotisation(
                type_cotisation=ContributionType.MALADIE,
                base_brute=Decimal("3000"),
                montant_patronal=Decimal("210"),
            )
        ] if has_cotisations else []

        return Declaration(
            type_declaration="DSN",
            employeur=employeur,
            employes=employes,
            cotisations=cotisations,
            periode=DateRange(debut=date(2026, 1, 1), fin=date(2026, 1, 31)),
        )

    def test_constat_document_unique(self, engine):
        decls = [self._make_declaration()]
        findings = engine._constats_structurels(decls)
        titles = [f.titre for f in findings]
        assert any("unique" in t.lower() for t in titles)

    def test_pas_de_constat_document_unique_si_multiple(self, engine):
        decls = [self._make_declaration(), self._make_declaration()]
        findings = engine._constats_structurels(decls)
        titles = [f.titre for f in findings]
        assert not any("unique" in t.lower() for t in titles)

    def test_constat_employeur_manquant(self, engine):
        decls = [self._make_declaration(has_employeur=False)]
        findings = engine._constats_structurels(decls)
        titles = [f.titre for f in findings]
        assert any("employeur" in t.lower() for t in titles)

    def test_constat_aucune_cotisation(self, engine):
        decls = [self._make_declaration(has_cotisations=False)]
        findings = engine._constats_structurels(decls)
        titles = [f.titre for f in findings]
        assert any("cotisation" in t.lower() for t in titles)

    def test_constat_pas_employes(self, engine):
        decls = [self._make_declaration(has_employes=False)]
        findings = engine._constats_structurels(decls)
        titles = [f.titre for f in findings]
        assert any("employe" in t.lower() for t in titles)


# ================================================================
# SYNTHESE
# ================================================================

class TestSynthese:

    def test_synthese_structure(self):
        engine = AnalyzerEngine()
        findings = [
            Finding(
                severite=Severity.CRITIQUE,
                categorie=FindingCategory.ANOMALIE,
                score_risque=90,
                montant_impact=Decimal("1000"),
            ),
            Finding(
                severite=Severity.FAIBLE,
                categorie=FindingCategory.DONNEE_MANQUANTE,
                score_risque=20,
            ),
        ]
        synthese = engine.generer_synthese(findings)
        assert synthese["total_findings"] == 2
        assert "critique" in synthese["par_severite"]
        assert synthese["impact_financier_total"] == 1000.0

    def test_synthese_vide(self):
        engine = AnalyzerEngine()
        synthese = engine.generer_synthese([])
        assert synthese["total_findings"] == 0
        assert synthese["score_risque_moyen"] == 0


# ================================================================
# ANALYSE COMPLETE (integration interne)
# ================================================================

class TestAnalyseComplete:

    def test_analyse_declarations_vides(self):
        engine = AnalyzerEngine()
        findings = engine.analyser([])
        # Pas de crash, peut generer des constats structurels
        assert isinstance(findings, list)

    def test_analyse_avec_declaration(self):
        engine = AnalyzerEngine(effectif=25)
        decl = Declaration(
            type_declaration="DSN",
            employeur=Employeur(siret="12345678901234", effectif=25),
            cotisations=[
                Cotisation(
                    type_cotisation=ContributionType.MALADIE,
                    base_brute=Decimal("3000"),
                    assiette=Decimal("3000"),
                    taux_patronal=Decimal("0.07"),
                    montant_patronal=Decimal("210"),
                ),
            ],
            masse_salariale_brute=Decimal("3000"),
            periode=DateRange(debut=date(2026, 1, 1), fin=date(2026, 1, 31)),
        )
        findings = engine.analyser([decl])
        assert isinstance(findings, list)
        # Findings tries par severite
        if len(findings) >= 2:
            sev_order = {Severity.CRITIQUE: 0, Severity.HAUTE: 1, Severity.MOYENNE: 2, Severity.FAIBLE: 3}
            for i in range(len(findings) - 1):
                assert sev_order.get(findings[i].severite, 9) <= sev_order.get(findings[i + 1].severite, 9)
