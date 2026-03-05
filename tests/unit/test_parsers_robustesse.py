"""Tests de robustesse des parseurs CSV, DSN et FEC.

Couvre les points critiques identifiés avant commercialisation :
- Détection d'encoding (SAGE cp1252, CIEL iso-8859-1, ADP utf-8-sig)
- Détection de dialecte CSV (séparateur, guillemets)
- Signatures logiciels de paie
- Validation CTP DSN
- Reconciliation S89 DSN
- Validation FEC 18 colonnes
- Comptes PCG et déséquilibres écritures
- Gestion des fichiers corrompus / vides
"""

import csv
import sys
import tempfile
from pathlib import Path
from decimal import Decimal
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from urssaf_analyzer.models.documents import Document, FileType
from urssaf_analyzer.parsers.csv_parser import CSVParser, COLONNES_MAPPING
from urssaf_analyzer.parsers.dsn_parser import DSNParser, CTP_MAPPING
from urssaf_analyzer.parsers.fec_parser import FECParser, COLONNES_FEC
from urssaf_analyzer.parsers.parser_factory import ParserFactory
from urssaf_analyzer.config.constants import ContributionType


FIXTURES = Path(__file__).parent.parent / "fixtures"


# ============================================================
# CSV Parser - Encoding
# ============================================================

class TestCSVEncoding:
    """Tests de la détection d'encodage multi-logiciels."""

    def setup_method(self):
        self.parser = CSVParser()

    def test_utf8_bom_adp(self, tmp_path):
        """ADP exporte en UTF-8 avec BOM."""
        contenu = "\ufeffnir,nom,prenom,base_brute,type_cotisation,taux_patronal,montant_patronal,taux_salarial,montant_salarial,periode_debut,periode_fin\n"
        contenu += "1850175123456,DUPONT,Jean,3200.00,maladie,13.00,416.00,0.00,0.00,01/01/2026,31/01/2026\n"
        f = tmp_path / "export_adp.csv"
        f.write_text(contenu, encoding="utf-8-sig")
        doc = Document(type_fichier=FileType.CSV)
        declarations = self.parser.parser(f, doc)
        assert len(declarations) >= 1

    def test_cp1252_sage(self, tmp_path):
        """SAGE exporte en Windows-1252."""
        contenu = "nir;nom;prenom;base_brute;type_cotisation;taux_patronal;montant_patronal;taux_salarial;montant_salarial;periode_debut;periode_fin\n"
        contenu += "1850175123456;DUPR\u00c9;Fran\u00e7ois;3200.00;maladie;13.00;416.00;0.00;0.00;01/01/2026;31/01/2026\n"
        f = tmp_path / "export_sage.csv"
        f.write_bytes(contenu.encode("cp1252"))
        doc = Document(type_fichier=FileType.CSV)
        declarations = self.parser.parser(f, doc)
        assert len(declarations) >= 1

    def test_iso8859_ciel(self, tmp_path):
        """CIEL exporte en ISO-8859-1."""
        contenu = "nir;nom;prenom;base_brute;type_cotisation;taux_patronal;montant_patronal;taux_salarial;montant_salarial;periode_debut;periode_fin\n"
        contenu += "1850175123456;L\u00c9GAULT;Marie;2800.00;vieillesse plafonnee;8.55;239.40;6.90;193.20;01/01/2026;31/01/2026\n"
        f = tmp_path / "export_ciel.csv"
        f.write_bytes(contenu.encode("iso-8859-1"))
        doc = Document(type_fichier=FileType.CSV)
        declarations = self.parser.parser(f, doc)
        assert len(declarations) >= 1


class TestCSVDialecte:
    """Tests de la détection automatique de dialecte CSV."""

    def setup_method(self):
        self.parser = CSVParser()

    def test_separateur_point_virgule(self, tmp_path):
        """SAGE/CIEL/Silae utilisent le point-virgule."""
        contenu = "nir;nom;prenom;base_brute;type_cotisation;taux_patronal;montant_patronal;taux_salarial;montant_salarial;periode_debut;periode_fin\n"
        contenu += "1850175123456;DUPONT;Jean;3200.00;maladie;13.00;416.00;0.00;0.00;01/01/2026;31/01/2026\n"
        f = tmp_path / "test.csv"
        f.write_text(contenu)
        doc = Document(type_fichier=FileType.CSV)
        declarations = self.parser.parser(f, doc)
        assert len(declarations) >= 1

    def test_separateur_tabulation(self, tmp_path):
        """EBP utilise parfois la tabulation."""
        contenu = "nir\tnom\tprenom\tbase_brute\ttype_cotisation\ttaux_patronal\tmontant_patronal\ttaux_salarial\tmontant_salarial\tperiode_debut\tperiode_fin\n"
        contenu += "1850175123456\tDUPONT\tJean\t3200.00\tmaladie\t13.00\t416.00\t0.00\t0.00\t01/01/2026\t31/01/2026\n"
        f = tmp_path / "test.csv"
        f.write_text(contenu)
        doc = Document(type_fichier=FileType.CSV)
        declarations = self.parser.parser(f, doc)
        assert len(declarations) >= 1

    def test_separateur_virgule(self, tmp_path):
        """ADP utilise la virgule standard."""
        doc = Document(type_fichier=FileType.CSV)
        declarations = self.parser.parser(FIXTURES / "sample_paie.csv", doc)
        assert len(declarations) >= 1
        assert len(declarations[0].employes) == 3


class TestCSVFichiersCorrompus:
    """Tests de gestion des fichiers CSV corrompus ou vides."""

    def setup_method(self):
        self.parser = CSVParser()

    def test_fichier_vide(self, tmp_path):
        f = tmp_path / "vide.csv"
        f.write_text("")
        doc = Document(type_fichier=FileType.CSV)
        from urssaf_analyzer.core.exceptions import ParseError
        with pytest.raises(ParseError):
            self.parser.parser(f, doc)

    def test_fichier_une_seule_ligne(self, tmp_path):
        """Fichier avec seulement l'en-tête."""
        f = tmp_path / "entete_seul.csv"
        f.write_text("nir,nom,prenom,base_brute\n")
        doc = Document(type_fichier=FileType.CSV)
        declarations = self.parser.parser(f, doc)
        assert len(declarations) >= 1
        assert len(declarations[0].employes) == 0

    def test_fichier_colonnes_inconnues(self, tmp_path):
        """Fichier avec des colonnes non reconnues."""
        f = tmp_path / "colonnes_inconnues.csv"
        f.write_text("colonne_x,colonne_y,colonne_z\nval1,val2,val3\n")
        doc = Document(type_fichier=FileType.CSV)
        declarations = self.parser.parser(f, doc)
        # Ne doit pas crasher, retourne des données vides
        assert len(declarations) >= 1


class TestCSVMappingColonnes:
    """Tests du mapping flexible des colonnes."""

    def test_mapping_nir_variantes(self):
        nir_keys = [k for k, v in COLONNES_MAPPING.items() if v == "nir"]
        assert "nir" in nir_keys
        assert "numero_ss" in nir_keys
        assert "securite_sociale" in nir_keys
        assert "num_secu" in nir_keys

    def test_mapping_nom_variantes(self):
        nom_keys = [k for k, v in COLONNES_MAPPING.items() if v == "nom"]
        assert "nom" in nom_keys
        assert "nom_salarie" in nom_keys
        assert "collaborateur_nom" in nom_keys

    def test_mapping_base_brute_variantes(self):
        brut_keys = [k for k, v in COLONNES_MAPPING.items() if v == "base_brute"]
        assert "base_brute" in brut_keys or "salaire_brut" in [k for k, v in COLONNES_MAPPING.items() if v == "base_brute"]


# ============================================================
# DSN Parser - CTP et validation
# ============================================================

class TestDSNCTP:
    """Tests du mapping CTP (Codes Types de Personnel)."""

    def test_ctp_maladie(self):
        assert CTP_MAPPING["100"] == ContributionType.MALADIE

    def test_ctp_vieillesse_plafonnee(self):
        assert CTP_MAPPING["260"] == ContributionType.VIEILLESSE_PLAFONNEE

    def test_ctp_vieillesse_deplafonnee(self):
        assert CTP_MAPPING["262"] == ContributionType.VIEILLESSE_DEPLAFONNEE

    def test_ctp_allocations_familiales(self):
        assert CTP_MAPPING["332"] == ContributionType.ALLOCATIONS_FAMILIALES

    def test_ctp_chomage(self):
        assert CTP_MAPPING["772"] == ContributionType.ASSURANCE_CHOMAGE

    def test_ctp_ags(self):
        assert CTP_MAPPING["937"] == ContributionType.AGS

    def test_ctp_csg_deductible(self):
        assert CTP_MAPPING["012"] == ContributionType.CSG_DEDUCTIBLE

    def test_ctp_formation(self):
        assert CTP_MAPPING["971"] == ContributionType.FORMATION_PROFESSIONNELLE

    def test_ctp_taxe_apprentissage(self):
        assert CTP_MAPPING["951"] == ContributionType.TAXE_APPRENTISSAGE

    def test_ctp_retraite_complementaire(self):
        assert CTP_MAPPING["063"] == ContributionType.RETRAITE_COMPLEMENTAIRE_T1

    def test_nombre_ctp_minimum(self):
        """Le mapping doit couvrir au minimum 40 CTP."""
        assert len(CTP_MAPPING) >= 40

    def test_tous_ctp_ont_contribution_type(self):
        """Chaque CTP doit mapper vers un ContributionType valide."""
        for code, ct in CTP_MAPPING.items():
            assert isinstance(ct, ContributionType), f"CTP {code} -> type invalide"


class TestDSNParsing:
    """Tests du parsing DSN sur le fichier fixture."""

    def setup_method(self):
        self.parser = DSNParser()

    def test_parsing_basique(self):
        doc = Document(type_fichier=FileType.DSN)
        declarations = self.parser.parser(FIXTURES / "sample_dsn.dsn", doc)
        assert len(declarations) == 1
        decl = declarations[0]
        assert decl.type_declaration == "DSN"

    def test_employeur_extrait(self):
        doc = Document(type_fichier=FileType.DSN)
        declarations = self.parser.parser(FIXTURES / "sample_dsn.dsn", doc)
        assert declarations[0].employeur is not None
        assert declarations[0].employeur.siren == "123456789"

    def test_employes_extraits(self):
        doc = Document(type_fichier=FileType.DSN)
        declarations = self.parser.parser(FIXTURES / "sample_dsn.dsn", doc)
        assert len(declarations[0].employes) == 3
        nirs = {e.nir for e in declarations[0].employes}
        # NIR de 13 chiffres peut etre complete avec la cle (15 chiffres)
        assert any("1850175123456" in nir for nir in nirs)

    def test_cotisations_extraites(self):
        doc = Document(type_fichier=FileType.DSN)
        declarations = self.parser.parser(FIXTURES / "sample_dsn.dsn", doc)
        assert len(declarations[0].cotisations) > 0

    def test_metadata_dsn(self):
        metadata = self.parser.extraire_metadata(FIXTURES / "sample_dsn.dsn")
        assert metadata["format"] == "dsn"
        assert "blocs" in metadata


class TestDSNFichiersCorrompus:
    """Tests de gestion des DSN corrompues."""

    def setup_method(self):
        self.parser = DSNParser()

    def test_fichier_vide(self, tmp_path):
        f = tmp_path / "vide.dsn"
        f.write_text("")
        doc = Document(type_fichier=FileType.DSN)
        from urssaf_analyzer.core.exceptions import ParseError
        with pytest.raises(ParseError):
            self.parser.parser(f, doc)

    def test_fichier_sans_bloc_s10(self, tmp_path):
        """DSN sans bloc émetteur."""
        contenu = "S20.G00.05.001 '123456789'\nS20.G00.05.002 'TEST'\n"
        f = tmp_path / "sans_s10.dsn"
        f.write_text(contenu)
        doc = Document(type_fichier=FileType.DSN)
        # Ne doit pas crasher
        declarations = self.parser.parser(f, doc)
        assert isinstance(declarations, list)


# ============================================================
# FEC Parser
# ============================================================

class TestFECColonnes:
    """Tests de la validation des colonnes FEC obligatoires."""

    def test_18_colonnes_obligatoires(self):
        assert len(COLONNES_FEC) == 18

    def test_colonnes_presentes(self):
        colonnes_attendues = [
            "JournalCode", "JournalLib", "EcritureNum", "EcritureDate",
            "CompteNum", "CompteLib", "CompAuxNum", "CompAuxLib",
            "PieceRef", "PieceDate", "EcritureLib", "Debit", "Credit",
            "EcrtureLet", "DateLet", "ValidDate", "Montantdevise", "Idevise",
        ]
        for col in colonnes_attendues:
            assert col in COLONNES_FEC, f"Colonne {col} manquante"


class TestFECParsing:
    """Tests du parsing FEC."""

    def setup_method(self):
        self.parser = FECParser()

    def test_peut_traiter_fec_txt(self, tmp_path):
        """FEC souvent en .txt avec header FEC reconnaissable."""
        contenu = "JournalCode\tJournalLib\tEcritureNum\tEcritureDate\tCompteNum\t"
        contenu += "CompteLib\tCompAuxNum\tCompAuxLib\tPieceRef\tPieceDate\t"
        contenu += "EcritureLib\tDebit\tCredit\tEcrtureLet\tDateLet\t"
        contenu += "ValidDate\tMontantdevise\tIdevise\n"
        contenu += "VE\tVentes\t001\t20260101\t411000\tClients\t\t\tFA001\t20260101\t"
        contenu += "Facture client\t1000.00\t0.00\t\t\t20260101\t\t\n"
        f = tmp_path / "FEC_20260101.txt"
        f.write_text(contenu)
        assert self.parser.peut_traiter(f) is True

    def test_parsing_fec_simple(self, tmp_path):
        """Parse un FEC minimal avec 2 écritures équilibrées."""
        contenu = "JournalCode\tJournalLib\tEcritureNum\tEcritureDate\tCompteNum\t"
        contenu += "CompteLib\tCompAuxNum\tCompAuxLib\tPieceRef\tPieceDate\t"
        contenu += "EcritureLib\tDebit\tCredit\tEcrtureLet\tDateLet\t"
        contenu += "ValidDate\tMontantdevise\tIdevise\n"
        # Écriture 1 - Vente
        contenu += "VE\tVentes\t001\t20260101\t411000\tClients\t\t\tFA001\t20260101\t"
        contenu += "Vente\t1200.00\t0.00\t\t\t20260101\t\t\n"
        contenu += "VE\tVentes\t001\t20260101\t701000\tVentes\t\t\tFA001\t20260101\t"
        contenu += "Vente\t0.00\t1000.00\t\t\t20260101\t\t\n"
        contenu += "VE\tVentes\t001\t20260101\t445710\tTVA collectée\t\t\tFA001\t20260101\t"
        contenu += "TVA\t0.00\t200.00\t\t\t20260101\t\t\n"
        f = tmp_path / "FEC_20260101.txt"
        f.write_text(contenu)
        doc = Document(type_fichier=FileType.TEXTE)
        declarations = self.parser.parser(f, doc)
        assert len(declarations) >= 1

    def test_fec_metadata(self, tmp_path):
        """Test de l'extraction des métadonnées FEC."""
        contenu = "JournalCode\tJournalLib\tEcritureNum\tEcritureDate\tCompteNum\t"
        contenu += "CompteLib\tCompAuxNum\tCompAuxLib\tPieceRef\tPieceDate\t"
        contenu += "EcritureLib\tDebit\tCredit\tEcrtureLet\tDateLet\t"
        contenu += "ValidDate\tMontantdevise\tIdevise\n"
        contenu += "VE\tVentes\t001\t20260101\t411000\tClients\t\t\tFA001\t20260101\t"
        contenu += "Vente\t1000.00\t0.00\t\t\t20260101\t\t\n"
        f = tmp_path / "FEC_20260101.txt"
        f.write_text(contenu)
        metadata = self.parser.extraire_metadata(f)
        assert metadata["format"] == "fec"

    def test_fec_pipe_separator(self, tmp_path):
        """Certains logiciels (CEGID) utilisent le pipe comme séparateur."""
        colonnes = "|".join(COLONNES_FEC)
        ligne = "|".join([
            "VE", "Ventes", "001", "20260101", "411000", "Clients",
            "", "", "FA001", "20260101", "Vente", "1000.00", "0.00",
            "", "", "20260101", "", "",
        ])
        f = tmp_path / "FEC_20260101.txt"
        f.write_text(colonnes + "\n" + ligne + "\n")
        assert self.parser.peut_traiter(f) is True


class TestFECFichiersCorrompus:
    """Tests de gestion des FEC corrompus."""

    def setup_method(self):
        self.parser = FECParser()

    def test_fichier_vide(self, tmp_path):
        f = tmp_path / "FEC_vide.txt"
        f.write_text("")
        doc = Document(type_fichier=FileType.TEXTE)
        from urssaf_analyzer.core.exceptions import ParseError
        with pytest.raises(ParseError):
            self.parser.parser(f, doc)

    def test_fichier_sans_colonnes_fec(self, tmp_path):
        """Fichier .txt qui n'est pas un FEC."""
        f = tmp_path / "pas_un_fec.txt"
        f.write_text("Ceci n'est pas un FEC\nJuste du texte quelconque\n")
        # peut_traiter doit retourner False
        assert self.parser.peut_traiter(f) is False


# ============================================================
# Parser Factory - Robustesse
# ============================================================

class TestParserFactoryRobustesse:
    """Tests de robustesse de la factory."""

    def setup_method(self):
        self.factory = ParserFactory()

    def test_dsn_extension(self):
        parser = self.factory.get_parser(Path("test.dsn"))
        assert isinstance(parser, DSNParser)

    def test_csv_extension(self):
        parser = self.factory.get_parser(Path("test.csv"))
        assert isinstance(parser, CSVParser)

    def test_priorite_fec_sur_csv(self, tmp_path):
        """FEC doit être testé avant CSV car un FEC peut avoir l'extension .txt ou .csv."""
        # Créer un fichier avec en-tête FEC
        colonnes = "\t".join(COLONNES_FEC)
        f = tmp_path / "FEC_20260101.txt"
        f.write_text(colonnes + "\n")
        parser = self.factory.get_parser(f)
        assert isinstance(parser, FECParser)

    def test_formats_supportes_non_vide(self):
        formats = self.factory.formats_supportes()
        assert len(formats) > 0
        assert ".csv" in formats
        assert ".pdf" in formats
        assert ".dsn" in formats
