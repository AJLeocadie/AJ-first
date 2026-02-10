"""Tests des analyseurs d'anomalies."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from decimal import Decimal
from datetime import date

from urssaf_analyzer.config.constants import (
    ContributionType, Severity, FindingCategory, PASS_MENSUEL,
)
from urssaf_analyzer.models.documents import (
    Declaration, Cotisation, Employe, DateRange,
)
from urssaf_analyzer.analyzers.anomaly_detector import AnomalyDetector
from urssaf_analyzer.analyzers.consistency_checker import ConsistencyChecker
from urssaf_analyzer.analyzers.pattern_analyzer import PatternAnalyzer
from urssaf_analyzer.analyzers.analyzer_engine import AnalyzerEngine


class TestAnomalyDetector:
    """Tests du detecteur d'anomalies."""

    def setup_method(self):
        self.detector = AnomalyDetector(effectif=25)

    def test_base_negative(self):
        decl = Declaration(
            cotisations=[Cotisation(
                type_cotisation=ContributionType.MALADIE,
                base_brute=Decimal("-1000"),
            )]
        )
        findings = self.detector.analyser([decl])
        assert len(findings) > 0
        assert any(f.titre == "Base brute negative" for f in findings)

    def test_taux_incorrect(self):
        decl = Declaration(
            cotisations=[Cotisation(
                type_cotisation=ContributionType.VIEILLESSE_PLAFONNEE,
                base_brute=Decimal("3000"),
                assiette=Decimal("3000"),
                taux_patronal=Decimal("0.10"),  # 10% au lieu de 8.55%
                montant_patronal=Decimal("300"),
            )]
        )
        findings = self.detector.analyser([decl])
        assert any("Taux patronal incorrect" in f.titre for f in findings)

    def test_depassement_pass(self):
        decl = Declaration(
            cotisations=[Cotisation(
                type_cotisation=ContributionType.VIEILLESSE_PLAFONNEE,
                base_brute=Decimal("5000"),
                assiette=Decimal("5000"),  # > PASS mensuel 4005
                taux_patronal=Decimal("0.0855"),
                montant_patronal=Decimal("427.50"),
            )]
        )
        findings = self.detector.analyser([decl])
        assert any(f.categorie == FindingCategory.DEPASSEMENT_SEUIL for f in findings)

    def test_erreur_calcul(self):
        decl = Declaration(
            cotisations=[Cotisation(
                type_cotisation=ContributionType.MALADIE,
                base_brute=Decimal("3000"),
                assiette=Decimal("3000"),
                taux_patronal=Decimal("0.13"),
                montant_patronal=Decimal("500"),  # Devrait etre 390
            )]
        )
        findings = self.detector.analyser([decl])
        assert any("Erreur de calcul" in f.titre for f in findings)

    def test_cotisation_conforme(self):
        decl = Declaration(
            cotisations=[Cotisation(
                type_cotisation=ContributionType.VIEILLESSE_PLAFONNEE,
                base_brute=Decimal("3000"),
                assiette=Decimal("3000"),
                taux_patronal=Decimal("0.0855"),
                montant_patronal=Decimal("256.50"),
            )]
        )
        findings = self.detector.analyser([decl])
        # Pas d'anomalie de taux ni de calcul
        assert not any("Taux patronal incorrect" in f.titre for f in findings)
        assert not any("Erreur de calcul" in f.titre for f in findings)


class TestConsistencyChecker:
    """Tests du verificateur de coherence."""

    def setup_method(self):
        self.checker = ConsistencyChecker()

    def test_ecart_effectif(self):
        decl = Declaration(
            effectif_declare=10,
            employes=[Employe(nir=str(i)) for i in range(5)],
            cotisations=[],
        )
        findings = self.checker.analyser([decl])
        assert any("effectif" in f.titre.lower() for f in findings)

    def test_masse_salariale_inter_documents(self):
        d1 = Declaration(
            masse_salariale_brute=Decimal("50000"),
            periode=DateRange(debut=date(2026, 1, 1), fin=date(2026, 1, 31)),
            cotisations=[],
            source_document_id="doc1",
        )
        d2 = Declaration(
            masse_salariale_brute=Decimal("80000"),  # Ecart > 5%
            periode=DateRange(debut=date(2026, 1, 1), fin=date(2026, 1, 31)),
            cotisations=[],
            source_document_id="doc2",
        )
        findings = self.checker.analyser([d1, d2])
        assert any("masse salariale" in f.titre.lower() for f in findings)


class TestPatternAnalyzer:
    """Tests de l'analyseur de patterns."""

    def setup_method(self):
        self.analyzer = PatternAnalyzer()

    def test_doublons(self):
        c1 = Cotisation(
            type_cotisation=ContributionType.MALADIE,
            employe_id="emp1",
            base_brute=Decimal("3000"),
            montant_patronal=Decimal("390"),
            source_document_id="doc1",
        )
        c2 = Cotisation(
            type_cotisation=ContributionType.MALADIE,
            employe_id="emp1",
            base_brute=Decimal("3000"),
            montant_patronal=Decimal("390"),
            source_document_id="doc2",
        )
        d1 = Declaration(cotisations=[c1])
        d2 = Declaration(cotisations=[c2])
        findings = self.analyzer.analyser([d1, d2])
        assert any("Doublon" in f.titre for f in findings)

    def test_mois_manquants(self):
        declarations = []
        for m in [1, 2, 4, 5]:  # Mars manquant
            declarations.append(Declaration(
                periode=DateRange(
                    debut=date(2026, m, 1),
                    fin=date(2026, m, 28),
                ),
                cotisations=[Cotisation(
                    base_brute=Decimal("3000"),
                    montant_patronal=Decimal("390"),
                )],
            ))
        findings = self.analyzer.analyser(declarations)
        assert any("manquant" in f.titre.lower() for f in findings)


class TestAnalyzerEngine:
    """Tests du moteur d'analyse complet."""

    def test_execution_complete(self):
        engine = AnalyzerEngine(effectif=25)
        decl = Declaration(
            cotisations=[
                Cotisation(
                    type_cotisation=ContributionType.MALADIE,
                    base_brute=Decimal("-500"),  # Anomalie
                ),
            ],
            effectif_declare=5,
            employes=[Employe(nir="1")],  # Incoherence effectif
        )
        findings = engine.analyser([decl])
        assert len(findings) > 0

    def test_synthese(self):
        engine = AnalyzerEngine()
        from urssaf_analyzer.models.documents import Finding
        findings = [
            Finding(severite=Severity.HAUTE, score_risque=80),
            Finding(severite=Severity.MOYENNE, score_risque=50),
        ]
        synthese = engine.generer_synthese(findings)
        assert synthese["total_findings"] == 2
        assert synthese["score_risque_moyen"] == 65.0
