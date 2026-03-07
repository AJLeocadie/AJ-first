"""Tests de detection d'erreurs silencieuses.

Niveau bancaire : verifie que les erreurs ne sont pas avalees silencieusement.
Ref: ISO 42001 - Fiabilite et tracabilite.
"""

import logging
import pytest
from decimal import Decimal
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ================================================================
# DETECTION D'ERREURS SILENCIEUSES DANS LE SCORING
# ================================================================

class TestScoringDeterminism:
    """Verifie le determinisme du scoring (ISO 42001)."""

    @pytest.mark.determinisme
    def test_score_deterministe(self):
        """Deux executions identiques doivent donner le meme score."""
        from urssaf_analyzer.rules.contribution_rules import ContributionRules
        rules = ContributionRules(effectif_entreprise=25, taux_at=Decimal("0.0208"))

        b1 = rules.calculer_bulletin_complet(Decimal("3000"))
        b2 = rules.calculer_bulletin_complet(Decimal("3000"))

        assert b1["total_patronal"] == b2["total_patronal"]
        assert b1["total_salarial"] == b2["total_salarial"]
        assert b1["net_avant_impot"] == b2["net_avant_impot"]
        assert len(b1["lignes"]) == len(b2["lignes"])

    @pytest.mark.determinisme
    def test_rgdu_deterministe(self):
        from urssaf_analyzer.rules.contribution_rules import ContributionRules
        from urssaf_analyzer.config.constants import SMIC_ANNUEL_BRUT
        rules = ContributionRules(effectif_entreprise=25)

        r1 = rules.calculer_rgdu(SMIC_ANNUEL_BRUT * Decimal("1.5"))
        r2 = rules.calculer_rgdu(SMIC_ANNUEL_BRUT * Decimal("1.5"))
        assert r1 == r2

    @pytest.mark.reproductibilite
    def test_analyse_reproductible(self, app_config, sample_csv_file):
        """L'analyse d'un meme fichier doit donner les memes types de constats."""
        import re
        from urssaf_analyzer.core.orchestrator import Orchestrator

        def _strip_uuids(titre):
            return re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', 'UUID', titre)

        orch1 = Orchestrator(config=app_config)
        orch1.analyser_documents([sample_csv_file])
        findings1 = sorted([(_strip_uuids(f.titre), f.severite.value) for f in orch1.result.findings])

        orch2 = Orchestrator(config=app_config)
        orch2.analyser_documents([sample_csv_file])
        findings2 = sorted([(_strip_uuids(f.titre), f.severite.value) for f in orch2.result.findings])

        assert len(findings1) == len(findings2)
        assert findings1 == findings2


# ================================================================
# VALIDATION DES DONNEES ENTRANTES
# ================================================================

class TestDataValidation:
    """Tests de validation stricte des donnees."""

    def test_decimal_overflow_handled(self):
        """Les montants extremes ne doivent pas causer d'erreur silencieuse."""
        from urssaf_analyzer.rules.contribution_rules import ContributionRules
        rules = ContributionRules(effectif_entreprise=25)

        # Montant tres eleve
        bulletin = rules.calculer_bulletin_complet(Decimal("999999"))
        assert bulletin["net_avant_impot"] > 0

        # Montant tres faible
        bulletin = rules.calculer_bulletin_complet(Decimal("0.01"))
        assert bulletin["net_avant_impot"] >= 0

    def test_taux_at_zero_gere(self):
        """Un taux AT/MP a zero ne doit pas casser le calcul."""
        from urssaf_analyzer.rules.contribution_rules import ContributionRules
        rules = ContributionRules(effectif_entreprise=25, taux_at=Decimal("0"))
        bulletin = rules.calculer_bulletin_complet(Decimal("3000"))
        assert bulletin is not None

    def test_effectif_zero_gere(self):
        """Effectif zero ne doit pas casser le calcul."""
        from urssaf_analyzer.rules.contribution_rules import ContributionRules
        rules = ContributionRules(effectif_entreprise=0)
        bulletin = rules.calculer_bulletin_complet(Decimal("3000"))
        assert bulletin is not None


# ================================================================
# DETECTION D'EXCEPTIONS SILENCIEUSES
# ================================================================

class TestSilentExceptionDetection:
    """Verifie que les except: pass n'avalent pas d'erreurs importantes."""

    def test_jwt_decode_returns_none_not_crash(self):
        """jwt_decode doit retourner None, jamais crasher."""
        from auth import jwt_decode
        assert jwt_decode("") is None
        assert jwt_decode("a") is None
        assert jwt_decode("a.b.c") is None
        assert jwt_decode(None) is None if True else True  # Graceful

    def test_parser_factory_error_not_silent(self):
        """Un format non supporte doit lever une exception, pas etre ignore."""
        from urssaf_analyzer.parsers.parser_factory import ParserFactory
        from urssaf_analyzer.core.exceptions import UnsupportedFormatError
        factory = ParserFactory()
        with pytest.raises(UnsupportedFormatError):
            factory.get_parser(Path("test.unknown_format"))


# ================================================================
# LOGGING - VERIFICATION QUE LES EVENTS CRITIQUES SONT LOGUES
# ================================================================

class TestCriticalLogging:
    """Verifie que les evenements critiques sont logues."""

    def test_orchestrator_logs_analysis_start(self, app_config, sample_csv_file, caplog):
        from urssaf_analyzer.core.orchestrator import Orchestrator
        with caplog.at_level(logging.INFO, logger="urssaf_analyzer"):
            orch = Orchestrator(config=app_config)
            orch.analyser_documents([sample_csv_file])
        assert any("Demarrage" in r.message or "demarrage" in r.message.lower() for r in caplog.records)

    def test_orchestrator_logs_report_generation(self, app_config, sample_csv_file, caplog):
        from urssaf_analyzer.core.orchestrator import Orchestrator
        with caplog.at_level(logging.INFO, logger="urssaf_analyzer"):
            orch = Orchestrator(config=app_config)
            orch.analyser_documents([sample_csv_file])
        assert any("Rapport" in r.message or "rapport" in r.message.lower() for r in caplog.records)
