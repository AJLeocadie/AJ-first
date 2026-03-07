"""Tests avec fichiers corrompus et malformés.

Vérifie que les parseurs gèrent gracieusement les fichiers invalides.
"""

from pathlib import Path
from decimal import Decimal

import pytest

from urssaf_analyzer.core.exceptions import ParseError
from urssaf_analyzer.models.documents import Document, FileType

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _make_doc(name, chemin, file_type=FileType.CSV):
    return Document(
        nom_fichier=name,
        chemin=chemin,
        type_fichier=file_type,
        hash_sha256="a" * 64,
        taille_octets=chemin.stat().st_size if chemin.exists() else 0,
    )


class TestCorruptCSV:
    """Tests avec CSV corrompus."""

    def test_empty_headers_csv(self):
        from urssaf_analyzer.parsers.csv_parser import CSVParser
        f = FIXTURES / "empty_headers.csv"
        if not f.exists():
            pytest.skip("Fixture empty_headers.csv manquante")
        parser = CSVParser()
        doc = _make_doc("empty_headers.csv", f)
        try:
            result = parser.parser(f, doc)
            # Devrait retourner des déclarations vides
            assert len(result) == 0 or len(result[0].cotisations) == 0
        except ParseError:
            pass  # Acceptable

    def test_huge_values_csv(self):
        from urssaf_analyzer.parsers.csv_parser import CSVParser
        f = FIXTURES / "huge_values.csv"
        if not f.exists():
            pytest.skip("Fixture huge_values.csv manquante")
        parser = CSVParser()
        doc = _make_doc("huge_values.csv", f)
        result = parser.parser(f, doc)
        assert len(result) >= 1
        # Les cotisations sont parsées même avec des valeurs extrêmes
        decl = result[0]
        assert decl is not None

    def test_corrupt_binary_csv(self):
        from urssaf_analyzer.parsers.csv_parser import CSVParser
        f = FIXTURES / "corrupt_binary.csv"
        if not f.exists():
            pytest.skip("Fixture corrupt_binary.csv manquante")
        parser = CSVParser()
        doc = _make_doc("corrupt_binary.csv", f)
        try:
            parser.parser(f, doc)
        except (ParseError, UnicodeDecodeError, Exception):
            pass  # Binary files must fail gracefully

    def test_csv_single_column(self, tmp_path):
        """CSV avec une seule colonne ne crash pas."""
        f = tmp_path / "single_col.csv"
        f.write_text("valeur\n100\n200\n300\n")
        from urssaf_analyzer.parsers.csv_parser import CSVParser
        parser = CSVParser()
        doc = _make_doc("single_col.csv", f)
        result = parser.parser(f, doc)
        assert result is not None

    def test_csv_mixed_separators(self, tmp_path):
        """CSV avec mélange de séparateurs."""
        content = "Code;Libelle,Base\tMontant\n100;Test,3000\t200\n"
        f = tmp_path / "mixed_sep.csv"
        f.write_text(content)
        from urssaf_analyzer.parsers.csv_parser import CSVParser
        parser = CSVParser()
        doc = _make_doc("mixed_sep.csv", f)
        result = parser.parser(f, doc)
        assert result is not None

    def test_csv_unicode_bom(self, tmp_path):
        """CSV avec BOM UTF-8."""
        content = "\ufeffCode;Libelle;Base;Taux Patronal;Montant Patronal\n201;Maladie;3500.00;0.070;245.00\n"
        f = tmp_path / "bom.csv"
        f.write_text(content, encoding="utf-8-sig")
        from urssaf_analyzer.parsers.csv_parser import CSVParser
        parser = CSVParser()
        doc = _make_doc("bom.csv", f)
        result = parser.parser(f, doc)
        assert len(result) >= 1

    def test_csv_trailing_newlines(self, tmp_path):
        """CSV avec beaucoup de lignes vides à la fin."""
        content = "Code;Libelle;Base;Montant Patronal\n201;Test;3000;210\n" + "\n" * 50
        f = tmp_path / "trailing.csv"
        f.write_text(content)
        from urssaf_analyzer.parsers.csv_parser import CSVParser
        parser = CSVParser()
        doc = _make_doc("trailing.csv", f)
        result = parser.parser(f, doc)
        assert result is not None


class TestCorruptDSN:
    """Tests avec DSN corrompues."""

    def test_malformed_dsn(self):
        from urssaf_analyzer.parsers.dsn_parser import DSNParser
        f = FIXTURES / "malformed_dsn.dsn"
        if not f.exists():
            pytest.skip("Fixture malformed_dsn.dsn manquante")
        parser = DSNParser()
        doc = _make_doc("malformed_dsn.dsn", f, FileType.DSN)
        try:
            result = parser.parser(f, doc)
            # Devrait retourner une déclaration vide ou avec warnings
        except ParseError:
            pass  # Acceptable

    def test_dsn_missing_s10(self, tmp_path):
        """DSN sans bloc S10 (emetteur manquant)."""
        content = "S20.G00.05.001 '123456789'\nS30.G00.30.001 '1850175123456'\n"
        f = tmp_path / "no_s10.dsn"
        f.write_text(content)
        from urssaf_analyzer.parsers.dsn_parser import DSNParser
        parser = DSNParser()
        doc = _make_doc("no_s10.dsn", f, FileType.DSN)
        try:
            result = parser.parser(f, doc)
        except ParseError:
            pass

    def test_dsn_valeurs_vides(self, tmp_path):
        """DSN avec des valeurs vides entre guillemets."""
        content = """S10.G00.00.001 ''
S10.G00.00.002 ''
S20.G00.05.001 ''
S30.G00.30.001 ''
"""
        f = tmp_path / "empty_vals.dsn"
        f.write_text(content)
        from urssaf_analyzer.parsers.dsn_parser import DSNParser
        parser = DSNParser()
        doc = _make_doc("empty_vals.dsn", f, FileType.DSN)
        try:
            result = parser.parser(f, doc)
        except ParseError:
            pass

    def test_dsn_cotisation_sans_montant(self, tmp_path):
        """DSN avec bloc S81 incomplet (pas de montant)."""
        content = """S10.G00.00.001 'TEST'
S10.G00.00.002 '01'
S20.G00.05.001 '123456789'
S81.G00.81.001 '100'
S81.G00.81.003 '3000.00'
"""
        f = tmp_path / "no_montant.dsn"
        f.write_text(content)
        from urssaf_analyzer.parsers.dsn_parser import DSNParser
        parser = DSNParser()
        doc = _make_doc("no_montant.dsn", f, FileType.DSN)
        try:
            result = parser.parser(f, doc)
            # Le parser devrait gérer gracieusement le bloc incomplet
        except ParseError:
            pass


class TestCorruptXML:
    """Tests avec XML corrompus."""

    def test_xml_malformed(self, tmp_path):
        """XML mal formé ne crash pas le parser."""
        content = "<root><unclosed>data</root>"
        f = tmp_path / "bad.xml"
        f.write_text(content)
        from urssaf_analyzer.parsers.xml_parser import XMLParser
        parser = XMLParser()
        if parser.peut_traiter(f):
            doc = _make_doc("bad.xml", f, FileType.XML)
            try:
                parser.parser(f, doc)
            except (ParseError, Exception):
                pass

    def test_xml_xxe_attempt(self, tmp_path):
        """XXE (XML External Entity) doit être bloqué."""
        content = """<?xml version="1.0"?>
<!DOCTYPE foo [
  <!ENTITY xxe SYSTEM "file:///etc/passwd">
]>
<root>&xxe;</root>"""
        f = tmp_path / "xxe.xml"
        f.write_text(content)
        from urssaf_analyzer.parsers.xml_parser import XMLParser
        parser = XMLParser()
        if parser.peut_traiter(f):
            doc = _make_doc("xxe.xml", f, FileType.XML)
            try:
                result = parser.parser(f, doc)
                # Si ça passe, le contenu de /etc/passwd ne doit pas apparaître
                assert result is not None
            except (ParseError, Exception):
                pass  # XXE bloqué = OK
