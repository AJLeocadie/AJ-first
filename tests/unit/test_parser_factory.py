"""Tests exhaustifs de la factory de parseurs.

Couverture : selection automatique, formats supportes,
erreurs de format, detection de type.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.parsers.parser_factory import ParserFactory
from urssaf_analyzer.core.exceptions import UnsupportedFormatError


class TestParserFactorySelection:
    """Tests de la selection automatique de parseur."""

    def setup_method(self):
        self.factory = ParserFactory()

    def test_csv_parser(self, tmp_path):
        f = tmp_path / "test.csv"
        f.write_text("a;b;c\n1;2;3")
        parser = self.factory.get_parser(f)
        assert parser is not None

    def test_xml_parser(self, tmp_path):
        f = tmp_path / "test.xml"
        f.write_text("<root><item/></root>")
        parser = self.factory.get_parser(f)
        assert parser is not None

    def test_txt_parser(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("contenu texte")
        parser = self.factory.get_parser(f)
        assert parser is not None

    def test_unsupported_format(self, tmp_path):
        f = tmp_path / "test.xyz"
        f.write_text("data")
        with pytest.raises(UnsupportedFormatError):
            self.factory.get_parser(f)

    def test_unsupported_format_message(self, tmp_path):
        f = tmp_path / "test.abc"
        f.write_text("data")
        with pytest.raises(UnsupportedFormatError, match="non supporte"):
            self.factory.get_parser(f)


class TestParserFactoryFormats:
    """Tests des formats supportes."""

    def test_formats_supportes_not_empty(self):
        factory = ParserFactory()
        formats = factory.formats_supportes()
        assert len(formats) > 0

    def test_csv_in_formats(self):
        factory = ParserFactory()
        formats = factory.formats_supportes()
        assert ".csv" in formats

    def test_pdf_in_formats(self):
        factory = ParserFactory()
        formats = factory.formats_supportes()
        assert ".pdf" in formats

    def test_xml_in_formats(self):
        factory = ParserFactory()
        formats = factory.formats_supportes()
        assert ".xml" in formats

    def test_xlsx_in_formats(self):
        factory = ParserFactory()
        formats = factory.formats_supportes()
        assert ".xlsx" in formats or ".xls" in formats


class TestParserFactoryDSN:
    """Tests specifiques au parseur DSN."""

    def test_dsn_file_recognized(self, tmp_path):
        f = tmp_path / "test.dsn"
        f.write_text("S10.G00.00.003,'11'\nS10.G00.00.004,'test'\n")
        factory = ParserFactory()
        parser = factory.get_parser(f)
        assert parser is not None
