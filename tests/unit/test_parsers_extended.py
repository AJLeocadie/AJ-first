"""Tests etendus des parseurs (text, fixedwidth, xml, excel, docx, pdf, dsn)."""

import sys
from decimal import Decimal
from datetime import date
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.models.documents import Document, FileType


# =====================================================
# TEXT PARSER
# =====================================================

class TestTextParser:
    """Tests du parseur texte."""

    def test_peut_traiter_txt(self):
        from urssaf_analyzer.parsers.text_parser import TextParser
        parser = TextParser()
        assert parser.peut_traiter(Path("test.txt")) is True

    def test_peut_traiter_non_txt(self):
        from urssaf_analyzer.parsers.text_parser import TextParser
        parser = TextParser()
        assert parser.peut_traiter(Path("test.pdf")) is False

    def test_extraire_metadata(self, tmp_path):
        from urssaf_analyzer.parsers.text_parser import TextParser
        parser = TextParser()
        f = tmp_path / "test.txt"
        f.write_text("Ligne 1\nLigne 2\nLigne 3")
        meta = parser.extraire_metadata(f)
        assert meta["format"] == "texte"
        assert meta["nb_lignes"] == 3

    def test_extraire_metadata_erreur(self, tmp_path):
        from urssaf_analyzer.parsers.text_parser import TextParser
        parser = TextParser()
        meta = parser.extraire_metadata(tmp_path / "nonexistent.txt")
        assert "erreur" in meta

    def test_parser_fichier_vide(self, tmp_path):
        from urssaf_analyzer.parsers.text_parser import TextParser
        parser = TextParser()
        f = tmp_path / "empty.txt"
        f.write_text("")
        doc = Document(id="test", nom_fichier="empty.txt", chemin=f, type_fichier=FileType.TEXTE)
        result = parser.parser(f, doc)
        assert result == []

    def test_lire_texte_utf8(self, tmp_path):
        from urssaf_analyzer.parsers.text_parser import TextParser
        f = tmp_path / "utf8.txt"
        f.write_text("Texte français avec accents: é à ü", encoding="utf-8")
        texte = TextParser._lire_texte(f)
        assert "français" in texte

    def test_lire_texte_latin1(self, tmp_path):
        from urssaf_analyzer.parsers.text_parser import TextParser
        f = tmp_path / "latin1.txt"
        f.write_bytes("Texte en latin-1: \xe9\xe0\xfc".encode("latin-1"))
        texte = TextParser._lire_texte(f)
        assert len(texte) > 0


# =====================================================
# FIXEDWIDTH PARSER
# =====================================================

class TestFixedwidthParser:
    """Tests du parseur a largeur fixe."""

    def test_peut_traiter_pnm(self):
        from urssaf_analyzer.parsers.fixedwidth_parser import FixedWidthParser
        parser = FixedWidthParser()
        assert parser.peut_traiter(Path("test.pnm")) is True

    def test_parse_sage_date_valid(self):
        from urssaf_analyzer.parsers.fixedwidth_parser import _parse_sage_date
        d = _parse_sage_date("150326")
        assert d == date(2026, 3, 15)

    def test_parse_sage_date_invalid(self):
        from urssaf_analyzer.parsers.fixedwidth_parser import _parse_sage_date
        assert _parse_sage_date("abc") is None

    def test_parse_sage_date_empty(self):
        from urssaf_analyzer.parsers.fixedwidth_parser import _parse_sage_date
        assert _parse_sage_date("") is None

    def test_parse_sage_date_old_year(self):
        from urssaf_analyzer.parsers.fixedwidth_parser import _parse_sage_date
        d = _parse_sage_date("010199")
        assert d is not None
        assert d.year == 1999

    def test_parse_ciel_date_valid(self):
        from urssaf_analyzer.parsers.fixedwidth_parser import _parse_ciel_date
        d = _parse_ciel_date("20260315")
        assert d == date(2026, 3, 15)

    def test_parse_ciel_date_invalid(self):
        from urssaf_analyzer.parsers.fixedwidth_parser import _parse_ciel_date
        assert _parse_ciel_date("abc") is None

    def test_parse_ciel_date_empty(self):
        from urssaf_analyzer.parsers.fixedwidth_parser import _parse_ciel_date
        assert _parse_ciel_date("") is None

    def test_parse_fixed_montant_zero(self):
        from urssaf_analyzer.parsers.fixedwidth_parser import _parse_fixed_montant
        assert _parse_fixed_montant("") == Decimal("0")

    def test_parse_fixed_montant_normal(self):
        from urssaf_analyzer.parsers.fixedwidth_parser import _parse_fixed_montant
        result = _parse_fixed_montant("  1234.56  ")
        assert result == Decimal("1234.56")


# =====================================================
# XML PARSER
# =====================================================

class TestXMLParser:
    """Tests du parseur XML."""

    def test_peut_traiter_xml(self):
        from urssaf_analyzer.parsers.xml_parser import XMLParser
        parser = XMLParser()
        assert parser.peut_traiter(Path("test.xml")) is True

    def test_peut_traiter_non_xml(self):
        from urssaf_analyzer.parsers.xml_parser import XMLParser
        parser = XMLParser()
        assert parser.peut_traiter(Path("test.csv")) is False

    def test_extraire_metadata(self, tmp_path):
        from urssaf_analyzer.parsers.xml_parser import XMLParser
        parser = XMLParser()
        f = tmp_path / "test.xml"
        f.write_text('<?xml version="1.0"?><root><item>1</item><item>2</item></root>')
        meta = parser.extraire_metadata(f)
        assert meta["format"] == "xml"

    def test_parser_xml_simple(self, tmp_path):
        from urssaf_analyzer.parsers.xml_parser import XMLParser
        parser = XMLParser()
        f = tmp_path / "test.xml"
        f.write_text('<?xml version="1.0"?><declarations><declaration></declaration></declarations>')
        doc = Document(id="test", nom_fichier="test.xml", chemin=f, type_fichier=FileType.XML)
        result = parser.parser(f, doc)
        assert isinstance(result, list)


# =====================================================
# EXCEL PARSER
# =====================================================

class TestExcelParser:
    """Tests du parseur Excel."""

    def test_peut_traiter_xlsx(self):
        from urssaf_analyzer.parsers.excel_parser import ExcelParser
        parser = ExcelParser()
        assert parser.peut_traiter(Path("test.xlsx")) is True

    def test_peut_traiter_xls(self):
        from urssaf_analyzer.parsers.excel_parser import ExcelParser
        parser = ExcelParser()
        assert parser.peut_traiter(Path("test.xls")) is True

    def test_peut_traiter_non_excel(self):
        from urssaf_analyzer.parsers.excel_parser import ExcelParser
        parser = ExcelParser()
        assert parser.peut_traiter(Path("test.csv")) is False

    def test_normaliser_entete(self):
        from urssaf_analyzer.parsers.excel_parser import ExcelParser
        assert ExcelParser._normaliser_entete("  NOM  ") == "nom"
        assert ExcelParser._normaliser_entete(None) == ""

    def test_est_ligne_total(self):
        from urssaf_analyzer.parsers.excel_parser import ExcelParser
        assert ExcelParser._est_ligne_total(("TOTAL", 100, 200)) is True
        assert ExcelParser._est_ligne_total(("Dupont", 100, 200)) is False

    def test_to_decimal(self):
        from urssaf_analyzer.parsers.excel_parser import ExcelParser
        assert ExcelParser._to_decimal(100) == Decimal("100")
        assert ExcelParser._to_decimal("1234.56") == Decimal("1234.56")

    def test_to_decimal_zero(self):
        from urssaf_analyzer.parsers.excel_parser import ExcelParser
        assert ExcelParser._to_decimal(0) == Decimal("0")

    def test_to_decimal_comma(self):
        from urssaf_analyzer.parsers.excel_parser import ExcelParser
        result = ExcelParser._to_decimal("1 234,56")
        assert result == Decimal("1234.56")


# =====================================================
# DOCX PARSER
# =====================================================

class TestDocxParser:
    """Tests du parseur Word."""

    def test_peut_traiter_docx(self):
        from urssaf_analyzer.parsers.docx_parser import DocxParser
        parser = DocxParser()
        assert parser.peut_traiter(Path("test.docx")) is True

    def test_peut_traiter_doc(self):
        from urssaf_analyzer.parsers.docx_parser import DocxParser
        parser = DocxParser()
        assert parser.peut_traiter(Path("test.doc")) is True

    def test_peut_traiter_non_word(self):
        from urssaf_analyzer.parsers.docx_parser import DocxParser
        parser = DocxParser()
        assert parser.peut_traiter(Path("test.pdf")) is False


# =====================================================
# PDF PARSER
# =====================================================

class TestPDFParser:
    """Tests du parseur PDF."""

    def test_peut_traiter_pdf(self):
        from urssaf_analyzer.parsers.pdf_parser import PDFParser
        parser = PDFParser()
        assert parser.peut_traiter(Path("test.pdf")) is True

    def test_peut_traiter_non_pdf(self):
        from urssaf_analyzer.parsers.pdf_parser import PDFParser
        parser = PDFParser()
        assert parser.peut_traiter(Path("test.csv")) is False

    def test_detecter_type_bulletin(self):
        from urssaf_analyzer.parsers.pdf_parser import PDFParser
        parser = PDFParser()
        texte = "BULLETIN DE PAIE\nSalaire brut: 3000\nNet a payer: 2400\nCotisations sociales"
        doc_type = parser._detecter_type_document(texte)
        assert doc_type in ("bulletin", "livre_de_paie", "generique")

    def test_detecter_type_facture(self):
        from urssaf_analyzer.parsers.pdf_parser import PDFParser
        parser = PDFParser()
        texte = "FACTURE N° F-2026-001\nMontant HT: 1000\nTVA 20%: 200\nMontant TTC: 1200"
        doc_type = parser._detecter_type_document(texte)
        assert doc_type in ("facture", "generique")


# =====================================================
# DSN PARSER
# =====================================================

class TestDSNParser:
    """Tests du parseur DSN."""

    def test_peut_traiter_dsn(self):
        from urssaf_analyzer.parsers.dsn_parser import DSNParser
        parser = DSNParser()
        assert parser.peut_traiter(Path("test.dsn")) is True

    def test_peut_traiter_non_dsn(self):
        from urssaf_analyzer.parsers.dsn_parser import DSNParser
        parser = DSNParser()
        assert parser.peut_traiter(Path("test.pdf")) is False

    def test_ctp_mapping_not_empty(self):
        from urssaf_analyzer.parsers.dsn_parser import CTP_MAPPING
        assert len(CTP_MAPPING) > 0
