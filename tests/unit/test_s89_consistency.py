"""Tests de la verification S89 dans le ConsistencyChecker.

Verifie que les ecarts entre totaux declares (bloc S89) et
totaux calcules (somme des cotisations individuelles S81) sont
correctement detectes.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from decimal import Decimal

from urssaf_analyzer.analyzers.consistency_checker import ConsistencyChecker
from urssaf_analyzer.models.documents import Declaration, Cotisation


def _make_declaration(
    s89_total_cotisations=None,
    s89_total_brut=None,
    masse_salariale_brute=Decimal("0"),
    cotisations=None,
):
    """Helper pour creer une Declaration avec metadata S89."""
    meta = {}
    if s89_total_cotisations is not None:
        meta["s89_total_cotisations"] = s89_total_cotisations
    if s89_total_brut is not None:
        meta["s89_total_brut"] = s89_total_brut
    return Declaration(
        type_declaration="DSN",
        reference="DSN-TEST",
        masse_salariale_brute=masse_salariale_brute,
        cotisations=cotisations or [],
        metadata=meta,
    )


class TestS89Consistency:
    """Tests de la detection des ecarts S89."""

    def test_s89_cotisations_coherent(self):
        """Pas de finding si S89 et somme individuelle sont coherents."""
        checker = ConsistencyChecker()
        cots = [
            Cotisation(montant_patronal=Decimal("500.00")),
            Cotisation(montant_patronal=Decimal("300.00")),
        ]
        decl = _make_declaration(
            s89_total_cotisations=800.00,
            cotisations=cots,
        )
        findings = checker.analyser([decl])
        s89_findings = [f for f in findings if "S89" in f.titre]
        assert len(s89_findings) == 0

    def test_s89_cotisations_ecart_detecte(self):
        """Un ecart significatif entre S89 et somme individuelle genere un finding."""
        checker = ConsistencyChecker()
        cots = [
            Cotisation(montant_patronal=Decimal("500.00")),
            Cotisation(montant_patronal=Decimal("300.00")),
        ]
        decl = _make_declaration(
            s89_total_cotisations=900.00,  # 100 EUR d'ecart
            cotisations=cots,
        )
        findings = checker.analyser([decl])
        s89_findings = [f for f in findings if "S89" in f.titre and "cotisations" in f.titre]
        assert len(s89_findings) == 1
        assert s89_findings[0].montant_impact == Decimal("100.00")

    def test_s89_brut_coherent(self):
        """Pas de finding si S89 brut et masse salariale sont coherents."""
        checker = ConsistencyChecker()
        cots = [Cotisation(montant_patronal=Decimal("100.00"))]
        decl = _make_declaration(
            s89_total_brut=5000.00,
            masse_salariale_brute=Decimal("5000.00"),
            cotisations=cots,
        )
        findings = checker.analyser([decl])
        s89_brut_findings = [f for f in findings if "S89" in f.titre and "brut" in f.titre]
        assert len(s89_brut_findings) == 0

    def test_s89_brut_ecart_detecte(self):
        """Un ecart significatif entre S89 brut et masse salariale genere un finding."""
        checker = ConsistencyChecker()
        cots = [Cotisation(montant_patronal=Decimal("100.00"))]
        decl = _make_declaration(
            s89_total_brut=5500.00,
            masse_salariale_brute=Decimal("5000.00"),
            cotisations=cots,
        )
        findings = checker.analyser([decl])
        s89_brut_findings = [f for f in findings if "S89" in f.titre and "brut" in f.titre]
        assert len(s89_brut_findings) == 1

    def test_s89_absent_pas_de_finding(self):
        """Pas de finding si les metadata S89 ne sont pas presentes."""
        checker = ConsistencyChecker()
        cots = [Cotisation(montant_patronal=Decimal("500.00"))]
        decl = _make_declaration(cotisations=cots, masse_salariale_brute=Decimal("3000.00"))
        findings = checker.analyser([decl])
        s89_findings = [f for f in findings if "S89" in f.titre]
        assert len(s89_findings) == 0

    def test_s89_ecart_faible_ignore(self):
        """Un ecart inferieur a 1 EUR pour les cotisations est tolere."""
        checker = ConsistencyChecker()
        cots = [Cotisation(montant_patronal=Decimal("800.50"))]
        decl = _make_declaration(
            s89_total_cotisations=800.90,  # 0.40 EUR ecart < 1 EUR
            cotisations=cots,
        )
        findings = checker.analyser([decl])
        s89_cot_findings = [f for f in findings if "S89" in f.titre and "cotisations" in f.titre]
        assert len(s89_cot_findings) == 0
