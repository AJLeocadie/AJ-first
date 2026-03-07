"""Tests unitaires exhaustifs des modeles de donnees.

Couverture niveau bancaire : dataclasses, proprietes calculees, cas limites.
"""

import pytest
from datetime import datetime, date
from decimal import Decimal

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.models.documents import (
    Document, FileType, DateRange, Employe, Employeur,
    Cotisation, Declaration, Finding, AnalysisResult,
)
from urssaf_analyzer.config.constants import (
    ContributionType, Severity, FindingCategory,
)


# ================================================================
# DOCUMENT
# ================================================================

class TestDocument:

    def test_document_creation(self):
        doc = Document(nom_fichier="test.csv", type_fichier=FileType.CSV)
        assert doc.nom_fichier == "test.csv"
        assert doc.type_fichier == FileType.CSV
        assert doc.id  # UUID genere

    def test_document_unique_ids(self):
        d1 = Document()
        d2 = Document()
        assert d1.id != d2.id

    def test_document_default_values(self):
        doc = Document()
        assert doc.taille_octets == 0
        assert doc.hash_sha256 == ""
        assert doc.metadata == {}

    def test_file_type_enum(self):
        assert FileType.PDF.value == "pdf"
        assert FileType.CSV.value == "csv"
        assert FileType.EXCEL.value == "excel"

    def test_date_range(self):
        dr = DateRange(debut=date(2026, 1, 1), fin=date(2026, 1, 31))
        assert dr.debut < dr.fin


# ================================================================
# EMPLOYE / EMPLOYEUR
# ================================================================

class TestEmployeEmployeur:

    def test_employe_creation(self):
        emp = Employe(nir="1850175123456", nom="Martin", prenom="Pierre")
        assert emp.nir == "1850175123456"
        assert emp.temps_travail == Decimal("1.0")

    def test_employeur_creation(self):
        eur = Employeur(siret="12345678901234", raison_sociale="ACME")
        assert eur.siret == "12345678901234"
        assert eur.effectif == 0

    def test_employe_unique_ids(self):
        e1 = Employe()
        e2 = Employe()
        assert e1.id != e2.id


# ================================================================
# COTISATION
# ================================================================

class TestCotisation:

    def test_cotisation_creation(self):
        cot = Cotisation(
            type_cotisation=ContributionType.MALADIE,
            base_brute=Decimal("3000"),
            assiette=Decimal("3000"),
            taux_patronal=Decimal("0.07"),
            montant_patronal=Decimal("210"),
        )
        assert cot.type_cotisation == ContributionType.MALADIE
        assert cot.montant_patronal == Decimal("210")

    def test_cotisation_defaults(self):
        cot = Cotisation()
        assert cot.base_brute == Decimal("0")
        assert cot.montant_salarial == Decimal("0")


# ================================================================
# DECLARATION
# ================================================================

class TestDeclaration:

    def test_declaration_creation(self):
        decl = Declaration(
            type_declaration="DSN",
            reference="DSN-2026-01",
            masse_salariale_brute=Decimal("50000"),
        )
        assert decl.type_declaration == "DSN"
        assert decl.masse_salariale_brute == Decimal("50000")

    def test_declaration_empty_lists(self):
        decl = Declaration()
        assert decl.employes == []
        assert decl.cotisations == []


# ================================================================
# FINDING
# ================================================================

class TestFinding:

    def test_finding_creation(self):
        f = Finding(
            categorie=FindingCategory.ANOMALIE,
            severite=Severity.CRITIQUE,
            titre="Taux maladie incorrect",
            score_risque=85,
        )
        assert f.severite == Severity.CRITIQUE
        assert f.score_risque == 85

    def test_finding_defaults(self):
        f = Finding()
        assert f.severite == Severity.MOYENNE
        assert f.montant_impact is None


# ================================================================
# ANALYSIS RESULT - Proprietes calculees
# ================================================================

class TestAnalysisResult:

    def _make_finding(self, cat=FindingCategory.ANOMALIE, sev=Severity.MOYENNE,
                      impact=None, score=50):
        return Finding(
            categorie=cat,
            severite=sev,
            titre="Test",
            montant_impact=impact,
            score_risque=score,
        )

    def test_empty_result(self):
        r = AnalysisResult()
        assert r.nb_anomalies == 0
        assert r.nb_incoherences == 0
        assert r.nb_critiques == 0
        assert r.impact_total == Decimal("0")
        assert r.score_risque_global == 0

    def test_nb_anomalies(self):
        r = AnalysisResult(findings=[
            self._make_finding(FindingCategory.ANOMALIE),
            self._make_finding(FindingCategory.ANOMALIE),
            self._make_finding(FindingCategory.INCOHERENCE),
        ])
        assert r.nb_anomalies == 2

    def test_nb_incoherences(self):
        r = AnalysisResult(findings=[
            self._make_finding(FindingCategory.INCOHERENCE),
        ])
        assert r.nb_incoherences == 1

    def test_nb_critiques(self):
        r = AnalysisResult(findings=[
            self._make_finding(sev=Severity.CRITIQUE),
            self._make_finding(sev=Severity.HAUTE),
            self._make_finding(sev=Severity.CRITIQUE),
        ])
        assert r.nb_critiques == 2

    def test_impact_total(self):
        r = AnalysisResult(findings=[
            self._make_finding(impact=Decimal("100.50")),
            self._make_finding(impact=Decimal("200.00")),
            self._make_finding(impact=None),
        ])
        assert r.impact_total == Decimal("300.50")

    def test_score_risque_global_range(self):
        r = AnalysisResult(findings=[
            self._make_finding(sev=Severity.CRITIQUE, score=100),
            self._make_finding(sev=Severity.HAUTE, score=80),
        ])
        score = r.score_risque_global
        assert 0 <= score <= 100

    def test_score_risque_zero_findings(self):
        r = AnalysisResult(findings=[])
        assert r.score_risque_global == 0

    def test_score_risque_all_critique_high(self):
        r = AnalysisResult(findings=[
            self._make_finding(sev=Severity.CRITIQUE, score=100),
        ])
        assert r.score_risque_global == 100

    def test_session_id_unique(self):
        r1 = AnalysisResult()
        r2 = AnalysisResult()
        assert r1.session_id != r2.session_id
