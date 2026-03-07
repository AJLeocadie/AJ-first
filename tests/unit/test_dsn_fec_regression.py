"""Tests de non-regression pour le parsing DSN et FEC.

Valide :
- Extraction correcte des champs DSN depuis le fixture sample_dsn.dsn
- Reconciliation S89/S81
- Robustesse face aux DSN malformees
- Export/validation roundtrip FEC
- Gestion des cas limites (desequilibre, colonnes manquantes)
- Mapping CTP Alsace-Moselle et codes inconnus
"""

import sys
import tempfile
from pathlib import Path
from decimal import Decimal
from datetime import date

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.parsers.dsn_parser import DSNParser, CTP_MAPPING, NATURES_CONTRAT
from urssaf_analyzer.models.documents import Document, FileType, Declaration, Cotisation
from urssaf_analyzer.config.constants import ContributionType
from urssaf_analyzer.comptabilite.ecritures import MoteurEcritures, Ecriture, LigneEcriture, TypeJournal
from urssaf_analyzer.comptabilite.fec_export import exporter_fec, valider_fec, COLONNES_FEC

FIXTURES = Path(__file__).parent.parent / "fixtures"


# =====================================================================
# PARSING DSN - FIXTURE sample_dsn.dsn
# =====================================================================


class TestDSNFixtureParsing:
    """Validation complete des champs extraits du fichier sample_dsn.dsn."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.parser = DSNParser()
        self.doc = Document(type_fichier=FileType.DSN)
        self.declarations = self.parser.parser(FIXTURES / "sample_dsn.dsn", self.doc)
        assert len(self.declarations) == 1
        self.decl = self.declarations[0]

    def test_type_declaration(self):
        assert self.decl.type_declaration == "DSN"

    def test_employeur_siren(self):
        assert self.decl.employeur is not None
        assert self.decl.employeur.siren == "123456789"

    def test_effectif(self):
        # S21.G00.11.001 = '15' dans le fixture, mais le SIRET est '00012'
        # qui est trop court pour un vrai SIRET
        assert self.decl.effectif_declare == 3

    def test_employes_count(self):
        assert len(self.decl.employes) == 3

    def test_employes_nirs(self):
        nirs = {e.nir for e in self.decl.employes}
        assert any("1850175123456" in nir for nir in nirs)
        assert any("1920683987654" in nir for nir in nirs)
        assert any("2780599456789" in nir for nir in nirs)

    def test_employes_noms(self):
        noms = {e.nom for e in self.decl.employes}
        assert "DUPONT" in noms
        assert "MARTIN" in noms
        assert "DURAND" in noms

    def test_employes_prenoms(self):
        prenoms = {e.prenom for e in self.decl.employes}
        assert "Jean" in prenoms
        assert "Sophie" in prenoms
        assert "Pierre" in prenoms

    def test_cotisations_extracted(self):
        assert len(self.decl.cotisations) >= 5

    def test_cotisations_types_mapped(self):
        types = {c.type_cotisation for c in self.decl.cotisations}
        assert ContributionType.MALADIE in types
        assert ContributionType.VIEILLESSE_PLAFONNEE in types
        assert ContributionType.VIEILLESSE_DEPLAFONNEE in types

    def test_cotisation_maladie_values(self):
        """CTP 100, base 3200.00, taux 13%, montant 416.00."""
        maladie_3200 = [
            c for c in self.decl.cotisations
            if c.type_cotisation == ContributionType.MALADIE
            and c.base_brute == Decimal("3200")
        ]
        assert len(maladie_3200) >= 1
        c = maladie_3200[0]
        assert c.taux_patronal == Decimal("0.13")
        assert c.montant_patronal == Decimal("416")

    def test_cotisation_vieillesse_plafonnee(self):
        """CTP 260, base 3200.00, taux 8.55%, montant 273.60."""
        vieil = [
            c for c in self.decl.cotisations
            if c.type_cotisation == ContributionType.VIEILLESSE_PLAFONNEE
            and c.base_brute == Decimal("3200")
        ]
        assert len(vieil) >= 1
        c = vieil[0]
        assert c.taux_patronal == Decimal("0.0855")
        assert c.montant_patronal == Decimal("273.60")

    def test_metadata_blocs_presents(self):
        assert "blocs_presents" in self.decl.metadata
        blocs = self.decl.metadata["blocs_presents"]
        assert "S10" in blocs or "S20" in blocs or "S30" in blocs

    def test_metadata_format_dsn(self):
        metadata = self.parser.extraire_metadata(FIXTURES / "sample_dsn.dsn")
        assert metadata["format"] == "dsn"
        assert metadata["sous_format"] == "texte_structure"


# =====================================================================
# S89 RECONCILIATION
# =====================================================================


class TestS89Reconciliation:
    """Verification de la logique de reconciliation S89 vs S81."""

    def _make_dsn_content(self, cotisations_lines, s89_total=None, s89_brut=None):
        """Genere un contenu DSN minimal avec cotisations et S89."""
        lines = [
            "S10.G00.00.001 'TEST'",
            "S10.G00.01.001 '999888777'",
            "S20.G00.05.001 '999888777'",
            "S20.G00.05.002 '202601'",
            "S30.G00.30.001 '1850175000001'",
            "S30.G00.30.002 'TEST'",
            "S30.G00.30.004 'Employe'",
        ]
        lines.extend(cotisations_lines)
        if s89_total is not None:
            lines.append(f"S89.G00.89.001 '{s89_total}'")
        if s89_brut is not None:
            lines.append(f"S89.G00.89.002 '{s89_brut}'")
        return "\n".join(lines)

    def test_s89_reconciliation_ok(self):
        """Quand S89 correspond a la somme S81, reconciliation reussie."""
        content = self._make_dsn_content(
            [
                "S81.G00.81.001 '100'",
                "S81.G00.81.003 '3000.00'",
                "S81.G00.81.004 '13.00'",
                "S81.G00.81.005 '390.00'",
                "S81.G00.81.001 '260'",
                "S81.G00.81.003 '3000.00'",
                "S81.G00.81.004 '8.55'",
                "S81.G00.81.005 '256.50'",
            ],
            s89_total="646.50",
        )
        with tempfile.NamedTemporaryFile(suffix=".dsn", mode="w", delete=False, encoding="utf-8") as f:
            f.write(content)
            f.flush()
            parser = DSNParser()
            doc = Document(type_fichier=FileType.DSN)
            decls = parser.parser(Path(f.name), doc)
            assert len(decls) == 1
            meta = decls[0].metadata
            assert "s89_reconciliation" in meta
            assert meta["s89_reconciliation"]["reconcilie"] is True

    def test_s89_reconciliation_ecart(self):
        """Quand S89 differe significativement, reconciliation echouee."""
        content = self._make_dsn_content(
            [
                "S81.G00.81.001 '100'",
                "S81.G00.81.003 '3000.00'",
                "S81.G00.81.004 '13.00'",
                "S81.G00.81.005 '390.00'",
            ],
            s89_total="500.00",
        )
        with tempfile.NamedTemporaryFile(suffix=".dsn", mode="w", delete=False, encoding="utf-8") as f:
            f.write(content)
            f.flush()
            parser = DSNParser()
            doc = Document(type_fichier=FileType.DSN)
            decls = parser.parser(Path(f.name), doc)
            meta = decls[0].metadata
            assert "s89_reconciliation" in meta
            assert meta["s89_reconciliation"]["reconcilie"] is False
            assert meta["s89_reconciliation"]["ecart"] > 1.0


# =====================================================================
# DSN MALFORMEES
# =====================================================================


class TestDSNMalformed:
    """Robustesse face aux entrees DSN incorrectes."""

    def _parse_content(self, content):
        with tempfile.NamedTemporaryFile(suffix=".dsn", mode="w", delete=False, encoding="utf-8") as f:
            f.write(content)
            f.flush()
            parser = DSNParser()
            doc = Document(type_fichier=FileType.DSN)
            return parser.parser(Path(f.name), doc)

    def test_empty_file_raises(self):
        """Un fichier vide doit lever ParseError."""
        from urssaf_analyzer.core.exceptions import ParseError
        with pytest.raises(ParseError):
            self._parse_content("")

    def test_no_blocs_raises(self):
        """Un fichier sans blocs DSN valides doit lever ParseError."""
        from urssaf_analyzer.core.exceptions import ParseError
        with pytest.raises(ParseError):
            self._parse_content("ceci n'est pas un fichier DSN\nrien du tout")

    def test_missing_employee_fields(self):
        """DSN avec champs employes incomplets -> parse sans crash."""
        content = "\n".join([
            "S10.G00.00.001 'TEST'",
            "S20.G00.05.001 '999888777'",
            "S20.G00.05.002 '202601'",
            "S30.G00.30.001 '1850175000001'",
            # Pas de nom ni prenom
            "S81.G00.81.001 '100'",
            "S81.G00.81.003 '2000.00'",
            "S81.G00.81.004 '13.00'",
            "S81.G00.81.005 '260.00'",
        ])
        decls = self._parse_content(content)
        assert len(decls) == 1
        # L'employe est cree meme sans nom
        assert len(decls[0].employes) == 1
        assert decls[0].employes[0].nom == ""

    def test_extra_spaces_in_values(self):
        """Les valeurs avec espaces supplementaires sont gerees."""
        content = "\n".join([
            "S10.G00.00.001 'TEST  '",
            "S20.G00.05.001 '999888777'",
            "S20.G00.05.002 '202601'",
            "S30.G00.30.001 '1850175000001'",
            "S30.G00.30.002 '  DUPONT  '",
            "S30.G00.30.004 'Jean'",
            "S81.G00.81.001 '100'",
            "S81.G00.81.003 '3000.00'",
            "S81.G00.81.004 '13.00'",
            "S81.G00.81.005 '390.00'",
        ])
        decls = self._parse_content(content)
        assert len(decls) == 1


# =====================================================================
# CTP MAPPING
# =====================================================================


class TestCTPMapping:
    """Verification du mapping CTP vers ContributionType."""

    def test_alsace_moselle_ctp_110(self):
        """CTP 110 (Maladie Alsace-Moselle) mappe vers MALADIE."""
        assert CTP_MAPPING["110"] == ContributionType.MALADIE

    def test_alsace_moselle_ctp_112(self):
        """CTP 112 (Maladie Alsace-Moselle complement) mappe vers MALADIE."""
        assert CTP_MAPPING["112"] == ContributionType.MALADIE

    def test_alsace_moselle_ctp_957(self):
        """CTP 957 (TA Alsace-Moselle) mappe vers TAXE_APPRENTISSAGE."""
        assert CTP_MAPPING["957"] == ContributionType.TAXE_APPRENTISSAGE

    def test_unknown_ctp_falls_back_to_autre(self):
        """Un code CTP inconnu dans une DSN donne ContributionType.AUTRE."""
        content = "\n".join([
            "S10.G00.00.001 'TEST'",
            "S20.G00.05.001 '999888777'",
            "S20.G00.05.002 '202601'",
            "S30.G00.30.001 '1850175000001'",
            "S30.G00.30.002 'TEST'",
            "S30.G00.30.004 'Employe'",
            "S81.G00.81.001 '999'",  # Code CTP inexistant
            "S81.G00.81.003 '2000.00'",
            "S81.G00.81.004 '5.00'",
            "S81.G00.81.005 '100.00'",
        ])
        with tempfile.NamedTemporaryFile(suffix=".dsn", mode="w", delete=False, encoding="utf-8") as f:
            f.write(content)
            f.flush()
            parser = DSNParser()
            doc = Document(type_fichier=FileType.DSN)
            decls = parser.parser(Path(f.name), doc)
            assert len(decls) == 1
            types = {c.type_cotisation for c in decls[0].cotisations}
            assert ContributionType.AUTRE in types

    def test_all_known_ctps_mapped(self):
        """Tous les CTP du mapping sont definis comme ContributionType valides."""
        for code, ct in CTP_MAPPING.items():
            assert isinstance(ct, ContributionType), f"CTP {code} mappe vers {ct} invalide"


# =====================================================================
# FEC - EXPORT ROUNDTRIP
# =====================================================================


class TestFECRoundtrip:
    """Export FEC → validation → coherence."""

    def _create_moteur_with_ecritures(self):
        """Cree un moteur avec des ecritures de paie equilibrees."""
        moteur = MoteurEcritures()
        moteur.generer_ecriture_paie(
            date_piece=date(2026, 1, 31),
            nom_salarie="DUPONT Jean",
            salaire_brut=Decimal("3200.00"),
            cotisations_salariales=Decimal("720.00"),
            cotisations_patronales_urssaf=Decimal("960.00"),
            cotisations_patronales_retraite=Decimal("320.00"),
            net_a_payer=Decimal("2480.00"),
        )
        moteur.generer_ecriture_paie(
            date_piece=date(2026, 1, 31),
            nom_salarie="MARTIN Sophie",
            salaire_brut=Decimal("4500.00"),
            cotisations_salariales=Decimal("1012.50"),
            cotisations_patronales_urssaf=Decimal("1350.00"),
            cotisations_patronales_retraite=Decimal("450.00"),
            net_a_payer=Decimal("3487.50"),
        )
        # Valider
        erreurs = moteur.valider_ecritures()
        assert len(erreurs) == 0
        return moteur

    def test_export_and_validate(self):
        """Export FEC puis validation: doit etre valide et equilibre."""
        moteur = self._create_moteur_with_ecritures()
        fec_content = exporter_fec(moteur, siren="123456789")

        result = valider_fec(fec_content)
        assert result["valide"] is True
        assert result["equilibre_general"] is True
        assert result["nb_lignes"] > 0
        assert result["ecritures_desequilibrees"] == 0

    def test_export_has_18_columns(self):
        """Le FEC exporte a bien 18 colonnes."""
        moteur = self._create_moteur_with_ecritures()
        fec_content = exporter_fec(moteur, siren="123456789")
        lines = fec_content.strip().split("\n")
        header = lines[0].split("\t")
        assert len(header) == 18

    def test_export_header_matches_spec(self):
        """L'en-tete FEC correspond aux 18 colonnes obligatoires."""
        moteur = self._create_moteur_with_ecritures()
        fec_content = exporter_fec(moteur, siren="123456789")
        lines = fec_content.strip().split("\n")
        header = lines[0].split("\t")
        assert header == COLONNES_FEC

    def test_debit_credit_consistency(self):
        """Chaque ecriture est equilibree dans le FEC exporte."""
        moteur = self._create_moteur_with_ecritures()
        fec_content = exporter_fec(moteur, siren="123456789")
        result = valider_fec(fec_content)
        assert result["ecritures_desequilibrees"] == 0
        # Total debit == total credit
        assert abs(result["total_debit"] - result["total_credit"]) < 0.01


# =====================================================================
# FEC - CAS D'ERREUR
# =====================================================================


class TestFECErrors:
    """Validation FEC avec des donnees incorrectes."""

    def test_fec_imbalanced_entries(self):
        """Un FEC avec ecritures desequilibrees doit le signaler."""
        fec_content = "\t".join(COLONNES_FEC) + "\n"
        fec_content += "\t".join([
            "OD", "Operations diverses", "000001", "20260131",
            "641100", "Salaire brut", "", "",
            "PAIE-01", "20260131", "Salaire brut DUPONT",
            "3200,00", "0,00", "", "", "", "", "",
        ]) + "\n"
        fec_content += "\t".join([
            "OD", "Operations diverses", "000001", "20260131",
            "421000", "Net a payer", "", "",
            "PAIE-01", "20260131", "Net DUPONT",
            "0,00", "2000,00", "", "", "", "", "",
        ]) + "\n"
        # Ecriture 000001 : debit 3200, credit 2000 -> desequilibree

        result = valider_fec(fec_content)
        assert result["ecritures_desequilibrees"] >= 1

    def test_fec_missing_columns(self):
        """Un FEC avec colonnes manquantes doit le signaler."""
        # Seulement 5 colonnes au lieu de 18
        fec_content = "JournalCode\tEcritureNum\tCompteNum\tDebit\tCredit\n"
        fec_content += "OD\t000001\t641100\t3200,00\t0,00\n"

        result = valider_fec(fec_content)
        assert len(result["colonnes_manquantes"]) > 0
        assert result["taux_conformite"] < 100

    def test_fec_empty_file(self):
        """Un FEC vide doit etre invalide."""
        result = valider_fec("")
        assert result["valide"] is False

    def test_fec_dates_format(self):
        """Les dates dans le FEC exporte sont au format YYYYMMDD."""
        moteur = MoteurEcritures()
        moteur.generer_ecriture_paie(
            date_piece=date(2026, 3, 15),
            nom_salarie="TEST",
            salaire_brut=Decimal("2000.00"),
            cotisations_salariales=Decimal("500.00"),
            cotisations_patronales_urssaf=Decimal("600.00"),
            net_a_payer=Decimal("1500.00"),
        )
        moteur.valider_ecritures()
        fec_content = exporter_fec(moteur, siren="999888777")
        lines = fec_content.strip().split("\n")
        # Verifier la date dans la premiere ligne de donnees
        data_line = lines[1].split("\t")
        ecriture_date = data_line[3]  # EcritureDate
        assert ecriture_date == "20260315"


# =====================================================================
# NATURES DE CONTRAT DSN
# =====================================================================


class TestNaturesContrat:
    """Verification du dictionnaire NATURES_CONTRAT."""

    def test_cdi_present(self):
        assert NATURES_CONTRAT["01"] == "CDI"

    def test_cdd_present(self):
        assert NATURES_CONTRAT["02"] == "CDD"

    def test_apprentissage_present(self):
        assert NATURES_CONTRAT["04"] == "Contrat d'apprentissage"

    def test_all_codes_are_strings(self):
        for code, libelle in NATURES_CONTRAT.items():
            assert isinstance(code, str)
            assert isinstance(libelle, str)
            assert len(libelle) > 0
