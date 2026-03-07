"""Tests unitaires de la factory de parseurs.

Couverture niveau bancaire : selection de parseur, formats supportes.
"""

import pytest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.parsers.parser_factory import ParserFactory
from urssaf_analyzer.core.exceptions import UnsupportedFormatError


@pytest.fixture
def factory():
    return ParserFactory()


class TestParserFactory:

    def test_csv_parser_selected(self, factory, tmp_path):
        f = tmp_path / "test.csv"
        f.write_text("a;b;c\n1;2;3")
        parser = factory.get_parser(f)
        assert parser is not None

    def test_xml_parser_selected(self, factory, tmp_path):
        f = tmp_path / "test.xml"
        f.write_text("<root></root>")
        parser = factory.get_parser(f)
        assert parser is not None

    def test_txt_parser_selected(self, factory, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("some text content")
        parser = factory.get_parser(f)
        assert parser is not None

    def test_unsupported_format_raises(self, factory, tmp_path):
        f = tmp_path / "test.xyz"
        f.write_text("content")
        with pytest.raises(UnsupportedFormatError):
            factory.get_parser(f)

    def test_formats_supportes(self, factory):
        formats = factory.formats_supportes()
        assert ".csv" in formats
        assert ".pdf" in formats
        assert ".xml" in formats
        assert ".xlsx" in formats

    def test_case_insensitive_extension(self, factory, tmp_path):
        f = tmp_path / "test.CSV"
        f.write_text("a;b;c")
        parser = factory.get_parser(f)
        assert parser is not None
