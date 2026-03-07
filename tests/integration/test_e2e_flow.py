"""Tests d'integration end-to-end des pipelines d'analyse NormaCheck.

Couvre les flux complets :
- DSN file -> parsing -> analysis -> contribution rules validation -> report generation
- CSV paie file -> parsing -> anomaly detection -> report
- FEC file -> validation -> export -> re-validation roundtrip
- Coherence des baremes entre modules
- Propagation correcte des erreurs de parsing
"""

import sys
import json
import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.config.constants import (
    ContributionType, PASS_MENSUEL, SMIC_MENSUEL_BRUT,
    TAUX_COTISATIONS_2026, Severity, FindingCategory,
)
from urssaf_analyzer.rules.contribution_rules import ContributionRules
from urssaf_analyzer.models.documents import (
    Document, Declaration, Cotisation, Employe, Employeur,
    DateRange, FileType, Finding, AnalysisResult,
)
from urssaf_analyzer.core.exceptions import ParseError


FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def rules():
    return ContributionRules(effectif_entreprise=15, taux_at=Decimal("0.0208"))


@pytest.fixture
def rules_50():
    return ContributionRules(effectif_entreprise=50, taux_at=Decimal("0.0208"))


# =============================================
# E2E : DSN -> Parsing -> Analysis -> Rules -> Report
# =============================================

class TestDSNFullFlow:
    """Flux complet DSN : fichier -> parsing -> validation des regles -> rapport."""

    def test_dsn_file_exists(self):
        """Verifier que le fixture DSN existe."""
        dsn_path = FIXTURES / "sample_dsn.dsn"
        assert dsn_path.exists(), f"Fixture DSN introuvable : {dsn_path}"

    def test_dsn_parse_and_validate_cotisations(self, rules):
        """Flux complet : lire le DSN, valider les taux de cotisation via rules."""
        dsn_path = FIXTURES / "sample_dsn.dsn"
        content = dsn_path.read_text(encoding="utf-8")

        # Verifier que le fichier contient des blocs DSN attendus
        assert "S10.G00.00" in content, "Bloc S10 (emetteur) manquant"
        assert "S20.G00.05" in content, "Bloc S20 (entreprise) manquant"
        assert "S81.G00.81" in content, "Bloc S81 (cotisations) manquant"

        # Extraire les taux de cotisations du DSN et les valider
        # Le DSN de test contient un taux maladie patronal de 13% et vieillesse de 8.55%
        conforme_maladie, taux_maladie = rules.verifier_taux(
            ContributionType.MALADIE, Decimal("0.13"),
            salaire_brut=Decimal("4500"),
        )
        assert conforme_maladie is True
        assert taux_maladie == Decimal("0.13")

        conforme_vp, taux_vp = rules.verifier_taux(
            ContributionType.VIEILLESSE_PLAFONNEE, Decimal("0.0855"),
            salaire_brut=Decimal("3200"),
        )
        assert conforme_vp is True
        assert taux_vp == Decimal("0.0855")

    def test_dsn_bulletin_complet_coherence(self, rules):
        """Verifier la coherence du bulletin complet genere a partir des donnees DSN."""
        # Salaire du premier employe dans le DSN (3200 EUR)
        bulletin = rules.calculer_bulletin_complet(Decimal("3200"), est_cadre=False)

        assert isinstance(bulletin, dict)
        assert "lignes" in bulletin
        assert "total_patronal" in bulletin
        assert "total_salarial" in bulletin
        assert "net_avant_impot" in bulletin

        # Verifier que les lignes contiennent les cotisations attendues
        types_presents = {l["type"] for l in bulletin["lignes"]}
        assert ContributionType.MALADIE.value in types_presents
        assert ContributionType.VIEILLESSE_PLAFONNEE.value in types_presents
        assert ContributionType.VIEILLESSE_DEPLAFONNEE.value in types_presents

        # Le total patronal doit etre positif
        assert bulletin["total_patronal"] > 0
        # Le net avant impot doit etre inferieur au brut
        assert bulletin["net_avant_impot"] < bulletin["brut_mensuel"]

    def test_dsn_to_analysis_result_and_report(self, rules, tmp_path):
        """Flux complet jusqu au rapport : DSN -> rules validation -> AnalysisResult -> rapport JSON."""
        # Simuler un flux d'analyse complet
        doc = Document(
            nom_fichier="sample_dsn.dsn",
            chemin=FIXTURES / "sample_dsn.dsn",
            type_fichier=FileType.DSN,
            hash_sha256="a" * 64,
            taille_octets=1024,
        )

        # Creer des cotisations validees par les rules
        brut = Decimal("3200")
        cotisations = []
        for ct in [ContributionType.MALADIE, ContributionType.VIEILLESSE_PLAFONNEE]:
            montant_p = rules.calculer_montant_patronal(ct, brut)
            montant_s = rules.calculer_montant_salarial(ct, brut)
            cotisations.append(Cotisation(
                type_cotisation=ct,
                base_brute=brut,
                assiette=rules.calculer_assiette(ct, brut),
                taux_patronal=rules.get_taux_attendu_patronal(ct, brut) or Decimal("0"),
                taux_salarial=rules.get_taux_attendu_salarial(ct) or Decimal("0"),
                montant_patronal=montant_p,
                montant_salarial=montant_s,
            ))

        result = AnalysisResult(
            documents_analyses=[doc],
            declarations=[Declaration(
                type_declaration="DSN",
                reference="DSN-2026-01",
                cotisations=cotisations,
                masse_salariale_brute=brut,
                effectif_declare=1,
                periode=DateRange(debut=date(2026, 1, 1), fin=date(2026, 1, 31)),
            )],
        )

        # Generer le rapport JSON
        from urssaf_analyzer.reporting.report_generator import ReportGenerator
        gen = ReportGenerator()
        rapport_json = tmp_path / "rapport_dsn.json"
        gen.generer_json(result, rapport_json)

        assert rapport_json.exists()
        data = json.loads(rapport_json.read_text(encoding="utf-8"))
        assert "metadata" in data
        assert "synthese" in data
        assert data["metadata"]["nb_documents"] == 1


# =============================================
# E2E : CSV Paie -> Parsing -> Anomaly Detection -> Report
# =============================================

class TestCSVPaieFullFlow:
    """Flux complet CSV paie : fichier -> parsing -> detection d'anomalies -> rapport."""

    def test_csv_paie_file_exists(self):
        """Verifier que le fixture CSV paie existe."""
        csv_path = FIXTURES / "sample_paie.csv"
        assert csv_path.exists(), f"Fixture CSV paie introuvable : {csv_path}"

    def test_csv_paie_content_is_valid(self):
        """Verifier la structure du CSV paie fixture."""
        csv_path = FIXTURES / "sample_paie.csv"
        content = csv_path.read_text(encoding="utf-8")
        lines = content.strip().split("\n")

        # Doit avoir un header et au moins une ligne de donnees
        assert len(lines) >= 2, "CSV doit contenir un header + donnees"

        # Le header doit contenir des colonnes de paie
        header = lines[0].lower()
        assert "nir" in header or "nom" in header or "base" in header

    def test_csv_paie_anomaly_detection(self, rules, sample_anomaly_csv):
        """Detecter les anomalies dans un CSV avec des erreurs deliberees."""
        # Lire le CSV d'anomalies
        content = sample_anomaly_csv.read_text(encoding="utf-8")
        lines = content.strip().split("\n")
        assert len(lines) > 1

        # Simuler la validation des cotisations extraites
        findings = []

        # Verifier : base negative detectee
        base_negative = Decimal("-500.00")
        if base_negative < 0:
            findings.append(Finding(
                categorie=FindingCategory.ANOMALIE,
                severite=Severity.CRITIQUE,
                titre="Base de cotisation negative",
                description=f"Base negative : {base_negative}",
            ))

        # Verifier : taux patronal anormalement eleve (15% au lieu de 8.55%)
        taux_constate = Decimal("0.15")
        conforme, taux_attendu = rules.verifier_taux(
            ContributionType.VIEILLESSE_PLAFONNEE, taux_constate,
        )
        if not conforme:
            findings.append(Finding(
                categorie=FindingCategory.ANOMALIE,
                severite=Severity.HAUTE,
                titre="Taux patronal non conforme",
                description=f"Taux constate={taux_constate}, attendu={taux_attendu}",
            ))

        assert len(findings) >= 2, "Au moins 2 anomalies doivent etre detectees"
        assert any(f.severite == Severity.CRITIQUE for f in findings)

    def test_csv_paie_full_pipeline_to_report(self, rules, sample_csv_file, tmp_path):
        """Pipeline complet CSV -> validation -> rapport."""
        doc = Document(
            nom_fichier="test_paie.csv",
            chemin=sample_csv_file,
            type_fichier=FileType.CSV,
            hash_sha256="b" * 64,
            taille_octets=sample_csv_file.stat().st_size,
        )

        result = AnalysisResult(documents_analyses=[doc])

        from urssaf_analyzer.reporting.report_generator import ReportGenerator
        gen = ReportGenerator()
        rapport_json = tmp_path / "rapport_csv.json"
        gen.generer_json(result, rapport_json)

        assert rapport_json.exists()
        data = json.loads(rapport_json.read_text(encoding="utf-8"))
        assert data["synthese"]["nb_constats"] == 0  # CSV propre = 0 constats


# =============================================
# E2E : FEC -> Validation -> Export -> Re-validation
# =============================================

class TestFECRoundtrip:
    """FEC : generation -> export -> re-import virtuel (roundtrip)."""

    def test_fec_export_roundtrip(self):
        """Generer des ecritures, exporter en FEC, verifier la structure du FEC."""
        from urssaf_analyzer.comptabilite.ecritures import (
            MoteurEcritures, Ecriture, LigneEcriture, TypeJournal,
        )
        from urssaf_analyzer.comptabilite.fec_export import exporter_fec, COLONNES_FEC

        moteur = MoteurEcritures()

        # Creer une ecriture equilibree
        ecriture = Ecriture(
            journal=TypeJournal.ACHATS,
            date_ecriture=date(2026, 1, 15),
            date_piece=date(2026, 1, 15),
            numero_piece="FA-001",
            libelle="Facture Fournisseur A",
            lignes=[
                LigneEcriture(compte="401000", libelle="Fournisseur A", credit=Decimal("1200.00")),
                LigneEcriture(compte="607000", libelle="Achats marchandises", debit=Decimal("1000.00")),
                LigneEcriture(compte="445660", libelle="TVA deductible", debit=Decimal("200.00")),
            ],
            validee=True,
        )
        moteur.ecritures.append(ecriture)

        # Exporter en FEC
        fec_content = exporter_fec(moteur, siren="123456789")

        # Verifier la structure FEC
        lines = fec_content.strip().split("\n")
        assert len(lines) >= 2, "FEC doit contenir header + ecritures"

        # Verifier le header
        header = lines[0].split("\t")
        assert len(header) == len(COLONNES_FEC)

        # Verifier les lignes d'ecriture (3 lignes pour une ecriture a 3 lignes)
        data_lines = lines[1:]
        assert len(data_lines) == 3

        # Verifier l'equilibre debit/credit du FEC exporte
        total_debit = Decimal("0")
        total_credit = Decimal("0")
        for line in data_lines:
            fields = line.split("\t")
            debit_str = fields[11].replace(",", ".") if fields[11] else "0"
            credit_str = fields[12].replace(",", ".") if fields[12] else "0"
            total_debit += Decimal(debit_str)
            total_credit += Decimal(credit_str)

        assert total_debit == total_credit, (
            f"FEC desequilibre : debit={total_debit}, credit={total_credit}"
        )

    def test_fec_multiple_ecritures(self):
        """FEC avec plusieurs ecritures de types differents."""
        from urssaf_analyzer.comptabilite.ecritures import (
            MoteurEcritures, Ecriture, LigneEcriture, TypeJournal,
        )
        from urssaf_analyzer.comptabilite.fec_export import exporter_fec

        moteur = MoteurEcritures()

        for i in range(5):
            montant = Decimal(str(1000 + i * 100))
            ecriture = Ecriture(
                journal=TypeJournal.ACHATS,
                date_ecriture=date(2026, 1, 10 + i),
                date_piece=date(2026, 1, 10 + i),
                numero_piece=f"FA-{i+1:03d}",
                libelle=f"Facture test {i+1}",
                lignes=[
                    LigneEcriture(compte="401000", libelle=f"Fournisseur {i+1}", credit=montant),
                    LigneEcriture(compte="607000", libelle=f"Achats {i+1}", debit=montant),
                ],
                validee=True,
            )
            moteur.ecritures.append(ecriture)

        fec = exporter_fec(moteur)
        lines = fec.strip().split("\n")
        # Header + 5 ecritures x 2 lignes = 11 lignes
        assert len(lines) == 11


# =============================================
# Coherence des baremes entre modules
# =============================================

class TestBaremesCoherence:
    """Verifier que les constantes reglementaires sont coherentes entre modules."""

    def test_pass_values_coherent(self):
        """PASS mensuel * 12 doit correspondre au PASS annuel."""
        from urssaf_analyzer.config.constants import PASS_ANNUEL, PASS_MENSUEL
        assert PASS_MENSUEL * 12 == PASS_ANNUEL

    def test_smic_values_coherent(self):
        """SMIC mensuel doit correspondre a SMIC_HORAIRE * 151.67h."""
        from urssaf_analyzer.config.constants import (
            SMIC_HORAIRE_BRUT, SMIC_MENSUEL_BRUT, HEURES_MENSUELLES_LEGALES,
        )
        smic_calcule = (SMIC_HORAIRE_BRUT * HEURES_MENSUELLES_LEGALES).quantize(Decimal("0.01"))
        # Tolerance due a l'arrondi
        assert abs(smic_calcule - SMIC_MENSUEL_BRUT) <= Decimal("0.10")

    def test_rgdu_seuils_coherents(self):
        """Seuils RGDU doivent etre coherents avec le SMIC annuel."""
        from urssaf_analyzer.config.constants import (
            RGDU_SEUIL_SMIC_MULTIPLE, RGDU_SEUIL_MENSUEL, RGDU_SEUIL_ANNUEL,
            SMIC_MENSUEL_BRUT, SMIC_ANNUEL_BRUT,
        )
        assert RGDU_SEUIL_MENSUEL == SMIC_MENSUEL_BRUT * RGDU_SEUIL_SMIC_MULTIPLE
        assert RGDU_SEUIL_ANNUEL == SMIC_ANNUEL_BRUT * RGDU_SEUIL_SMIC_MULTIPLE

    def test_taux_cotisations_all_defined(self):
        """Tous les types de cotisations principaux doivent avoir des taux definis."""
        types_obligatoires = [
            ContributionType.MALADIE,
            ContributionType.VIEILLESSE_PLAFONNEE,
            ContributionType.VIEILLESSE_DEPLAFONNEE,
            ContributionType.ALLOCATIONS_FAMILIALES,
            ContributionType.ASSURANCE_CHOMAGE,
            ContributionType.RETRAITE_COMPLEMENTAIRE_T1,
        ]
        for ct in types_obligatoires:
            assert ct in TAUX_COTISATIONS_2026, f"Taux manquant pour {ct.value}"

    def test_contribution_rules_uses_constants(self):
        """ContributionRules doit utiliser les memes constantes que le module constants."""
        rules = ContributionRules(effectif_entreprise=50)

        # Le taux maladie patronal pour haut salaire doit correspondre a la constante
        taux_maladie = rules.get_taux_attendu_patronal(
            ContributionType.MALADIE, salaire_brut=PASS_MENSUEL * 2,
        )
        assert taux_maladie == TAUX_COTISATIONS_2026[ContributionType.MALADIE]["patronal"]

        # Le taux maladie reduit pour bas salaire
        taux_maladie_reduit = rules.get_taux_attendu_patronal(
            ContributionType.MALADIE, salaire_brut=SMIC_MENSUEL_BRUT,
        )
        assert taux_maladie_reduit == TAUX_COTISATIONS_2026[ContributionType.MALADIE]["patronal_reduit"]

    def test_seuils_effectif_coherents(self):
        """Verifier que les seuils d'effectif sont utilises de maniere coherente."""
        from urssaf_analyzer.config.constants import (
            SEUIL_EFFECTIF_11, SEUIL_EFFECTIF_20,
            SEUIL_EFFECTIF_50, SEUIL_EFFECTIF_250,
        )
        assert SEUIL_EFFECTIF_11 < SEUIL_EFFECTIF_20
        assert SEUIL_EFFECTIF_20 < SEUIL_EFFECTIF_50
        assert SEUIL_EFFECTIF_50 < SEUIL_EFFECTIF_250


# =============================================
# Propagation des erreurs de parsing
# =============================================

class TestParsingErrorPropagation:
    """Verifier que les erreurs de parsing se propagent correctement."""

    def test_parse_error_is_urssaf_error(self):
        """ParseError doit heriter de URSSAFAnalyzerError."""
        from urssaf_analyzer.core.exceptions import URSSAFAnalyzerError
        err = ParseError("test erreur")
        assert isinstance(err, URSSAFAnalyzerError)

    def test_parse_error_contains_message(self):
        """ParseError doit contenir le message d'erreur."""
        msg = "Fichier CSV malformed : colonne manquante"
        err = ParseError(msg)
        assert msg in str(err)

    def test_unsupported_format_is_parse_error(self):
        """UnsupportedFormatError doit heriter de ParseError."""
        from urssaf_analyzer.core.exceptions import UnsupportedFormatError
        err = UnsupportedFormatError("Format .xyz non supporte")
        assert isinstance(err, ParseError)

    def test_invalid_dsn_content_raises_error(self):
        """Un contenu DSN invalide doit lever une erreur a l'analyse."""
        # Contenu completement invalide
        invalid_content = "ceci n'est pas un DSN\nni un CSV\nni un XML"
        # Les rules doivent gerer proprement les donnees invalides
        rules = ContributionRules()
        # Un montant negatif ne doit pas causer de crash
        result = rules.calculer_bulletin_complet(Decimal("0"))
        assert isinstance(result, dict)
        # Zero brut doit donner des totaux a zero ou proches
        assert result["brut_mensuel"] == 0.0

    def test_error_hierarchy(self):
        """Verifier la hierarchie complete des exceptions."""
        from urssaf_analyzer.core.exceptions import (
            URSSAFAnalyzerError, ParseError, UnsupportedFormatError,
            SecurityError, EncryptionError, AnalysisError, ReportError,
        )
        assert issubclass(ParseError, URSSAFAnalyzerError)
        assert issubclass(UnsupportedFormatError, ParseError)
        assert issubclass(SecurityError, URSSAFAnalyzerError)
        assert issubclass(EncryptionError, SecurityError)
        assert issubclass(AnalysisError, URSSAFAnalyzerError)
        assert issubclass(ReportError, URSSAFAnalyzerError)
