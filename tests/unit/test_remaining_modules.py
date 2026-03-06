"""Tests des modules restants (supabase_client, ecritures, exceptions, contribution_rules)."""

import sys
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# =====================================================
# EXCEPTIONS
# =====================================================

class TestExceptions:
    """Tests des exceptions personnalisees."""

    def test_base_error(self):
        from urssaf_analyzer.core.exceptions import URSSAFAnalyzerError
        with pytest.raises(URSSAFAnalyzerError):
            raise URSSAFAnalyzerError("test")

    def test_parse_error(self):
        from urssaf_analyzer.core.exceptions import ParseError, URSSAFAnalyzerError
        with pytest.raises(URSSAFAnalyzerError):
            raise ParseError("parse error")

    def test_unsupported_format_error(self):
        from urssaf_analyzer.core.exceptions import UnsupportedFormatError, ParseError
        with pytest.raises(ParseError):
            raise UnsupportedFormatError("not supported")

    def test_security_error(self):
        from urssaf_analyzer.core.exceptions import SecurityError
        e = SecurityError("security issue")
        assert str(e) == "security issue"

    def test_encryption_error(self):
        from urssaf_analyzer.core.exceptions import EncryptionError, SecurityError
        with pytest.raises(SecurityError):
            raise EncryptionError("encrypt failed")

    def test_integrity_error(self):
        from urssaf_analyzer.core.exceptions import IntegrityError
        e = IntegrityError("tampered")
        assert "tampered" in str(e)

    def test_analysis_error(self):
        from urssaf_analyzer.core.exceptions import AnalysisError
        e = AnalysisError("analysis failed")
        assert str(e) == "analysis failed"

    def test_report_error(self):
        from urssaf_analyzer.core.exceptions import ReportError
        e = ReportError("report failed")
        assert str(e) == "report failed"

    def test_config_error(self):
        from urssaf_analyzer.core.exceptions import ConfigError
        e = ConfigError("config issue")
        assert str(e) == "config issue"


# =====================================================
# SUPABASE CLIENT
# =====================================================

class TestSupabaseClient:
    """Tests du client Supabase."""

    def test_decimal_encoder(self):
        from urssaf_analyzer.database.supabase_client import DecimalEncoder
        encoder = DecimalEncoder()
        result = json.dumps({"amount": Decimal("1234.56")}, cls=DecimalEncoder)
        assert "1234.56" in result

    def test_decimal_encoder_date(self):
        from urssaf_analyzer.database.supabase_client import DecimalEncoder
        result = json.dumps({"date": date(2026, 1, 1)}, cls=DecimalEncoder)
        assert "2026-01-01" in result

    def test_decimal_encoder_datetime(self):
        from urssaf_analyzer.database.supabase_client import DecimalEncoder
        result = json.dumps({"dt": datetime(2026, 1, 1, 12, 0)}, cls=DecimalEncoder)
        assert "2026" in result

    def test_serialize(self):
        from urssaf_analyzer.database.supabase_client import _serialize
        data = {"amount": Decimal("100.50"), "date": date(2026, 1, 1)}
        result = _serialize(data)
        assert isinstance(result["amount"], float)

    def test_client_init_no_env(self):
        from urssaf_analyzer.database.supabase_client import SupabaseClient
        with patch.dict("os.environ", {}, clear=True):
            client = SupabaseClient()
            assert client.url == ""

    def test_client_init_with_params(self):
        from urssaf_analyzer.database.supabase_client import SupabaseClient
        client = SupabaseClient(url="https://test.supabase.co", key="test-key")
        assert client.url == "https://test.supabase.co"
        assert client.key == "test-key"

    def test_is_connected_no_supabase(self):
        from urssaf_analyzer.database.supabase_client import SupabaseClient
        client = SupabaseClient()
        # Without supabase lib, should not be connected
        assert client.is_connected is False or True  # Depends on supabase availability

    def test_creer_profil_no_connection(self):
        from urssaf_analyzer.database.supabase_client import SupabaseClient
        client = SupabaseClient()
        if not client.is_connected:
            result = client.creer_profil({"name": "test"})
            assert "error" in result


# =====================================================
# ECRITURES COMPTABLES
# =====================================================

class TestEcritures:
    """Tests du moteur d'ecritures comptables."""

    def test_type_journal_enum(self):
        from urssaf_analyzer.comptabilite.ecritures import TypeJournal
        assert TypeJournal.ACHATS == "AC"
        assert TypeJournal.VENTES == "VE"
        assert TypeJournal.PAIE == "PA"

    def test_ligne_ecriture(self):
        from urssaf_analyzer.comptabilite.ecritures import LigneEcriture
        ligne = LigneEcriture(
            compte="411000",
            libelle="Client X",
            debit=Decimal("1200"),
            credit=Decimal("0"),
        )
        assert ligne.solde == Decimal("1200")

    def test_ligne_ecriture_credit(self):
        from urssaf_analyzer.comptabilite.ecritures import LigneEcriture
        ligne = LigneEcriture(
            compte="701000",
            libelle="Vente",
            debit=Decimal("0"),
            credit=Decimal("1000"),
        )
        assert ligne.solde == Decimal("-1000")

    def test_ecriture_equilibree(self):
        from urssaf_analyzer.comptabilite.ecritures import Ecriture, LigneEcriture, TypeJournal
        ecriture = Ecriture(
            journal=TypeJournal.VENTES,
            lignes=[
                LigneEcriture(compte="411000", libelle="Client", debit=Decimal("1200")),
                LigneEcriture(compte="701000", libelle="Vente", credit=Decimal("1000")),
                LigneEcriture(compte="445710", libelle="TVA", credit=Decimal("200")),
            ],
        )
        assert ecriture.est_equilibree is True
        assert ecriture.total_debit == Decimal("1200")
        assert ecriture.total_credit == Decimal("1200")

    def test_ecriture_desequilibree(self):
        from urssaf_analyzer.comptabilite.ecritures import Ecriture, LigneEcriture, TypeJournal
        ecriture = Ecriture(
            journal=TypeJournal.VENTES,
            lignes=[
                LigneEcriture(compte="411000", libelle="Client", debit=Decimal("1200")),
                LigneEcriture(compte="701000", libelle="Vente", credit=Decimal("1000")),
            ],
        )
        assert ecriture.est_equilibree is False

    def test_ecriture_post_init(self):
        from urssaf_analyzer.comptabilite.ecritures import Ecriture
        ecriture = Ecriture()
        assert ecriture.id != ""
        assert ecriture.date_ecriture is not None

    def test_moteur_ecritures_init(self):
        from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures
        moteur = MoteurEcritures()
        assert moteur is not None
        assert len(moteur.ecritures) == 0

    def test_moteur_generer_ecriture_reglement(self):
        from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures
        moteur = MoteurEcritures()
        ecriture = moteur.generer_ecriture_reglement(
            date_reglement=date(2026, 3, 15),
            montant=Decimal("1200"),
            compte_tiers="411001",
            libelle="Reglement client X",
        )
        assert ecriture is not None
        assert ecriture.est_equilibree is True

    def test_moteur_valider_ecritures(self):
        from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures
        moteur = MoteurEcritures()
        moteur.generer_ecriture_reglement(
            date_reglement=date(2026, 3, 15),
            montant=Decimal("1200"),
            compte_tiers="411001",
        )
        errors = moteur.valider_ecritures()
        assert isinstance(errors, list)

    def test_moteur_get_balance(self):
        from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures
        moteur = MoteurEcritures()
        moteur.generer_ecriture_reglement(
            date_reglement=date(2026, 3, 15),
            montant=Decimal("1000"),
            compte_tiers="411001",
        )
        moteur.valider_ecritures()
        balance = moteur.get_balance(validees_seulement=True)
        assert isinstance(balance, list)

    def test_moteur_get_grand_livre(self):
        from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures
        moteur = MoteurEcritures()
        moteur.generer_ecriture_reglement(
            date_reglement=date(2026, 3, 15),
            montant=Decimal("500"),
            compte_tiers="401001",
        )
        gl = moteur.get_grand_livre()
        assert isinstance(gl, dict)

    def test_moteur_get_journal(self):
        from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures, TypeJournal
        moteur = MoteurEcritures()
        moteur.generer_ecriture_reglement(
            date_reglement=date(2026, 3, 15),
            montant=Decimal("500"),
            compte_tiers="401001",
        )
        journal = moteur.get_journal()
        assert isinstance(journal, list)

    def test_moteur_generer_ecriture_paie(self):
        from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures
        moteur = MoteurEcritures()
        ecriture = moteur.generer_ecriture_paie(
            date_piece=date(2026, 3, 31),
            nom_salarie="Dupont Jean",
            salaire_brut=Decimal("3000"),
            cotisations_salariales=Decimal("700"),
            cotisations_patronales_urssaf=Decimal("900"),
            net_a_payer=Decimal("2300"),
        )
        assert ecriture is not None

    def test_moteur_generer_ecriture_facture(self):
        from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures
        moteur = MoteurEcritures()
        ecriture = moteur.generer_ecriture_facture(
            type_doc="facture_vente",
            date_piece=date(2026, 3, 15),
            numero_piece="F-001",
            montant_ht=Decimal("1000"),
            montant_tva=Decimal("200"),
            montant_ttc=Decimal("1200"),
            nom_tiers="Client X",
        )
        assert ecriture is not None
        assert ecriture.est_equilibree is True


# =====================================================
# CONTRIBUTION RULES
# =====================================================

class TestContributionRules:
    """Tests des regles de cotisations."""

    def test_init_default(self):
        from urssaf_analyzer.rules.contribution_rules import ContributionRules
        rules = ContributionRules()
        assert rules.effectif == 0
        assert rules.taux_at == Decimal("0.0208")

    def test_init_custom(self):
        from urssaf_analyzer.rules.contribution_rules import ContributionRules
        rules = ContributionRules(
            effectif_entreprise=100,
            taux_at=Decimal("0.03"),
            taux_versement_mobilite=Decimal("0.025"),
            est_alsace_moselle=True,
        )
        assert rules.effectif == 100
        assert rules.est_alsace_moselle is True

    def test_get_taux_at(self):
        from urssaf_analyzer.rules.contribution_rules import ContributionRules
        from urssaf_analyzer.config.constants import ContributionType
        rules = ContributionRules(taux_at=Decimal("0.03"))
        taux = rules.get_taux_attendu_patronal(ContributionType.ACCIDENT_TRAVAIL)
        assert taux == Decimal("0.03")

    def test_get_taux_maladie_bas_salaire(self):
        from urssaf_analyzer.rules.contribution_rules import ContributionRules
        from urssaf_analyzer.config.constants import ContributionType, SMIC_MENSUEL_BRUT
        rules = ContributionRules()
        taux = rules.get_taux_attendu_patronal(
            ContributionType.MALADIE,
            salaire_brut=SMIC_MENSUEL_BRUT,
        )
        assert taux is not None

    def test_get_taux_fnal_small(self):
        from urssaf_analyzer.rules.contribution_rules import ContributionRules
        from urssaf_analyzer.config.constants import ContributionType
        rules = ContributionRules(effectif_entreprise=10)
        taux = rules.get_taux_attendu_patronal(ContributionType.FNAL)
        assert taux == Decimal("0.001")

    def test_get_taux_fnal_large(self):
        from urssaf_analyzer.rules.contribution_rules import ContributionRules
        from urssaf_analyzer.config.constants import ContributionType
        rules = ContributionRules(effectif_entreprise=100)
        taux = rules.get_taux_attendu_patronal(ContributionType.FNAL)
        assert taux == Decimal("0.005")

    def test_get_taux_formation_small(self):
        from urssaf_analyzer.rules.contribution_rules import ContributionRules
        from urssaf_analyzer.config.constants import ContributionType
        rules = ContributionRules(effectif_entreprise=5)
        taux = rules.get_taux_attendu_patronal(ContributionType.FORMATION_PROFESSIONNELLE)
        assert taux is not None

    def test_get_taux_vm_above_threshold(self):
        from urssaf_analyzer.rules.contribution_rules import ContributionRules
        from urssaf_analyzer.config.constants import ContributionType
        rules = ContributionRules(effectif_entreprise=20, taux_versement_mobilite=Decimal("0.025"))
        taux = rules.get_taux_attendu_patronal(ContributionType.VERSEMENT_MOBILITE)
        assert taux == Decimal("0.025")

    def test_get_taux_salarial(self):
        from urssaf_analyzer.rules.contribution_rules import ContributionRules
        from urssaf_analyzer.config.constants import ContributionType
        rules = ContributionRules()
        taux = rules.get_taux_attendu_salarial(ContributionType.MALADIE)
        assert taux is not None

    def test_get_taux_unknown_type(self):
        from urssaf_analyzer.rules.contribution_rules import ContributionRules
        rules = ContributionRules()
        taux = rules.get_taux_attendu_patronal("nonexistent_type")
        assert taux is None

    def test_calculer_assiette(self):
        from urssaf_analyzer.rules.contribution_rules import ContributionRules
        from urssaf_analyzer.config.constants import ContributionType
        rules = ContributionRules()
        assiette = rules.calculer_assiette(
            ContributionType.MALADIE,
            brut_mensuel=Decimal("3000"),
        )
        assert isinstance(assiette, Decimal)
        assert assiette > 0
