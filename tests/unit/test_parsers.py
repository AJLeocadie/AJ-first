"""Tests des parseurs de documents."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from decimal import Decimal

from urssaf_analyzer.config.constants import ContributionType
from urssaf_analyzer.models.documents import Document, FileType
from urssaf_analyzer.parsers.csv_parser import CSVParser
from urssaf_analyzer.parsers.xml_parser import XMLParser
from urssaf_analyzer.parsers.dsn_parser import DSNParser
from urssaf_analyzer.parsers.parser_factory import ParserFactory
from urssaf_analyzer.utils.number_utils import parser_montant, est_nombre_rond, formater_montant
from urssaf_analyzer.utils.date_utils import parser_date, mois_entre

FIXTURES = Path(__file__).parent.parent / "fixtures"


class TestParserFactory:
    """Tests de la factory de parseurs."""

    def setup_method(self):
        self.factory = ParserFactory()

    def test_csv_selection(self):
        parser = self.factory.get_parser(FIXTURES / "sample_paie.csv")
        assert isinstance(parser, CSVParser)

    def test_xml_selection(self):
        parser = self.factory.get_parser(FIXTURES / "sample_bordereau.xml")
        # Peut etre XMLParser ou DSNParser selon le contenu
        assert parser is not None

    def test_dsn_selection(self):
        parser = self.factory.get_parser(FIXTURES / "sample_dsn.dsn")
        assert isinstance(parser, DSNParser)

    def test_format_non_supporte(self):
        import pytest
        from urssaf_analyzer.core.exceptions import UnsupportedFormatError
        with pytest.raises(UnsupportedFormatError):
            self.factory.get_parser(Path("test.doc"))


class TestCSVParser:
    """Tests du parseur CSV."""

    def setup_method(self):
        self.parser = CSVParser()

    def test_peut_traiter(self):
        assert self.parser.peut_traiter(Path("test.csv")) is True
        assert self.parser.peut_traiter(Path("test.pdf")) is False

    def test_parsing_sample(self):
        doc = Document(type_fichier=FileType.CSV)
        declarations = self.parser.parser(FIXTURES / "sample_paie.csv", doc)
        assert len(declarations) == 1

        decl = declarations[0]
        assert len(decl.cotisations) > 0
        assert len(decl.employes) == 3  # DUPONT, MARTIN, DURAND

    def test_extraction_montants(self):
        doc = Document(type_fichier=FileType.CSV)
        declarations = self.parser.parser(FIXTURES / "sample_paie.csv", doc)
        decl = declarations[0]

        # Verifier que les montants sont correctement extraits
        maladie_dupont = [
            c for c in decl.cotisations
            if c.base_brute == Decimal("3200") and c.type_cotisation == ContributionType.MALADIE
        ]
        assert len(maladie_dupont) >= 1
        c = maladie_dupont[0]
        assert c.taux_patronal == Decimal("0.13")
        assert c.montant_patronal == Decimal("416")

    def test_metadata(self):
        metadata = self.parser.extraire_metadata(FIXTURES / "sample_paie.csv")
        assert metadata["format"] == "csv"
        assert metadata["nb_lignes"] > 0


class TestXMLParser:
    """Tests du parseur XML."""

    def setup_method(self):
        self.parser = XMLParser()

    def test_peut_traiter(self):
        assert self.parser.peut_traiter(Path("test.xml")) is True
        assert self.parser.peut_traiter(Path("test.csv")) is False

    def test_parsing_bordereau(self):
        doc = Document(type_fichier=FileType.XML)
        declarations = self.parser.parser(FIXTURES / "sample_bordereau.xml", doc)
        assert len(declarations) >= 1

        # Verifier qu'on a extrait des cotisations
        total_cotisations = sum(len(d.cotisations) for d in declarations)
        assert total_cotisations > 0

    def test_metadata(self):
        metadata = self.parser.extraire_metadata(FIXTURES / "sample_bordereau.xml")
        assert metadata["format"] == "xml"
        assert "racine" in metadata


class TestDSNParser:
    """Tests du parseur DSN."""

    def setup_method(self):
        self.parser = DSNParser()

    def test_peut_traiter(self):
        assert self.parser.peut_traiter(Path("test.dsn")) is True
        assert self.parser.peut_traiter(Path("test.csv")) is False

    def test_parsing_dsn(self):
        doc = Document(type_fichier=FileType.DSN)
        declarations = self.parser.parser(FIXTURES / "sample_dsn.dsn", doc)
        assert len(declarations) == 1

        decl = declarations[0]
        assert decl.type_declaration == "DSN"
        assert len(decl.employes) == 3
        assert len(decl.cotisations) > 0

    def test_extraction_employeur(self):
        doc = Document(type_fichier=FileType.DSN)
        declarations = self.parser.parser(FIXTURES / "sample_dsn.dsn", doc)
        decl = declarations[0]

        assert decl.employeur is not None
        assert decl.employeur.siren == "123456789"

    def test_extraction_employes(self):
        doc = Document(type_fichier=FileType.DSN)
        declarations = self.parser.parser(FIXTURES / "sample_dsn.dsn", doc)
        decl = declarations[0]

        nirs = {e.nir for e in decl.employes}
        assert "1850175123456" in nirs
        assert "1920683987654" in nirs

    def test_metadata(self):
        metadata = self.parser.extraire_metadata(FIXTURES / "sample_dsn.dsn")
        assert metadata["format"] == "dsn"
        assert "blocs" in metadata


class TestNumberUtils:
    """Tests des utilitaires numeriques."""

    def test_parser_montant_francais(self):
        assert parser_montant("1 234,56") == Decimal("1234.56")

    def test_parser_montant_anglais(self):
        assert parser_montant("1234.56") == Decimal("1234.56")

    def test_parser_montant_euro(self):
        assert parser_montant("1234.56 EUR") == Decimal("1234.56")
        assert parser_montant("1234.56€") == Decimal("1234.56")

    def test_parser_montant_europeen(self):
        assert parser_montant("1.234,56") == Decimal("1234.56")

    def test_parser_montant_vide(self):
        assert parser_montant("") == Decimal("0")
        assert parser_montant("   ") == Decimal("0")

    def test_nombre_rond(self):
        assert est_nombre_rond(Decimal("100")) is True
        assert est_nombre_rond(Decimal("100.50")) is False

    def test_formater_montant(self):
        result = formater_montant(Decimal("1234.56"))
        assert "1 234" in result
        assert ".56" in result


class TestDateUtils:
    """Tests des utilitaires de date."""

    def test_parser_date_fr(self):
        d = parser_date("15/01/2026")
        assert d is not None
        assert d.year == 2026
        assert d.month == 1
        assert d.day == 15

    def test_parser_date_iso(self):
        d = parser_date("2026-01-15")
        assert d is not None
        assert d.year == 2026

    def test_parser_date_invalide(self):
        assert parser_date("pas une date") is None
        assert parser_date("") is None

    def test_mois_entre(self):
        from datetime import date
        assert mois_entre(date(2026, 1, 1), date(2026, 3, 31)) == 3
        assert mois_entre(date(2026, 1, 1), date(2026, 1, 31)) == 1
