"""Tests exhaustifs des modeles de donnees.

Couverture : Document, Employe, Employeur, Cotisation, Declaration,
Finding, AnalysisResult, proprietes calculees.
"""

import sys
from pathlib import Path
from decimal import Decimal
from datetime import datetime, date

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.models.documents import (
    FileType, DateRange, Document, Employe, Employeur,
    Cotisation, Declaration, Finding, AnalysisResult,
)
from urssaf_analyzer.config.constants import (
    ContributionType, Severity, FindingCategory,
)


class TestFileType:
    """Tests de l'enum FileType."""

    def test_all_types_exist(self):
        assert FileType.PDF == "pdf"
        assert FileType.CSV == "csv"
        assert FileType.EXCEL == "excel"
        assert FileType.XML == "xml"
        assert FileType.DSN == "dsn"
        assert FileType.IMAGE == "image"
        assert FileType.TEXTE == "texte"

    def test_from_string(self):
        assert FileType("pdf") == FileType.PDF
        assert FileType("csv") == FileType.CSV


class TestDocument:
    """Tests du modele Document."""

    def test_default_values(self):
        doc = Document()
        assert doc.nom_fichier == ""
        assert doc.chemin is None
        assert doc.hash_sha256 == ""
        assert doc.taille_octets == 0
        assert doc.id is not None
        assert doc.importe_le is not None

    def test_custom_values(self):
        doc = Document(
            nom_fichier="test.csv",
            type_fichier=FileType.CSV,
            hash_sha256="abc123",
            taille_octets=1024,
        )
        assert doc.nom_fichier == "test.csv"
        assert doc.type_fichier == FileType.CSV
        assert doc.taille_octets == 1024

    def test_unique_ids(self):
        d1 = Document()
        d2 = Document()
        assert d1.id != d2.id


class TestEmploye:
    """Tests du modele Employe."""

    def test_default_temps_plein(self):
        emp = Employe()
        assert emp.temps_travail == Decimal("1.0")

    def test_temps_partiel(self):
        emp = Employe(temps_travail=Decimal("0.5"))
        assert emp.temps_travail == Decimal("0.5")


class TestCotisation:
    """Tests du modele Cotisation."""

    def test_default_zero_values(self):
        cot = Cotisation()
        assert cot.base_brute == Decimal("0")
        assert cot.montant_patronal == Decimal("0")
        assert cot.montant_salarial == Decimal("0")

    def test_calcul_coherent(self):
        cot = Cotisation(
            base_brute=Decimal("3000"),
            assiette=Decimal("3000"),
            taux_patronal=Decimal("0.07"),
            montant_patronal=Decimal("210"),
        )
        expected = cot.assiette * cot.taux_patronal
        assert abs(cot.montant_patronal - expected) < Decimal("0.01")


class TestAnalysisResult:
    """Tests du modele AnalysisResult et ses proprietes calculees."""

    def test_empty_result(self):
        result = AnalysisResult()
        assert result.nb_anomalies == 0
        assert result.nb_incoherences == 0
        assert result.nb_critiques == 0
        assert result.impact_total == Decimal("0")
        assert result.score_risque_global == 0

    def test_nb_anomalies(self):
        result = AnalysisResult(findings=[
            Finding(categorie=FindingCategory.ANOMALIE),
            Finding(categorie=FindingCategory.ANOMALIE),
            Finding(categorie=FindingCategory.INCOHERENCE),
        ])
        assert result.nb_anomalies == 2
        assert result.nb_incoherences == 1

    def test_nb_critiques(self):
        result = AnalysisResult(findings=[
            Finding(severite=Severity.CRITIQUE),
            Finding(severite=Severity.HAUTE),
            Finding(severite=Severity.CRITIQUE),
        ])
        assert result.nb_critiques == 2

    def test_impact_total(self):
        result = AnalysisResult(findings=[
            Finding(montant_impact=Decimal("1000")),
            Finding(montant_impact=Decimal("500")),
            Finding(montant_impact=None),
        ])
        assert result.impact_total == Decimal("1500")

    def test_score_risque_global(self):
        result = AnalysisResult(findings=[
            Finding(severite=Severity.CRITIQUE, score_risque=90),
        ])
        score = result.score_risque_global
        assert 0 <= score <= 100

    def test_score_risque_sans_findings(self):
        result = AnalysisResult(findings=[])
        assert result.score_risque_global == 0

    def test_session_id_unique(self):
        r1 = AnalysisResult()
        r2 = AnalysisResult()
        assert r1.session_id != r2.session_id

    def test_date_analyse_set(self):
        result = AnalysisResult()
        assert isinstance(result.date_analyse, datetime)

    def test_multiple_severity_levels(self):
        result = AnalysisResult(findings=[
            Finding(severite=Severity.CRITIQUE, score_risque=100),
            Finding(severite=Severity.HAUTE, score_risque=80),
            Finding(severite=Severity.MOYENNE, score_risque=50),
            Finding(severite=Severity.FAIBLE, score_risque=20),
        ])
        score = result.score_risque_global
        assert 0 < score <= 100


class TestDateRange:
    """Tests du modele DateRange."""

    def test_creation(self):
        dr = DateRange(debut=date(2026, 1, 1), fin=date(2026, 12, 31))
        assert dr.debut == date(2026, 1, 1)
        assert dr.fin == date(2026, 12, 31)
