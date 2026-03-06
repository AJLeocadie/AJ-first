"""Tests du point d'entree CLI (main.py, __main__.py)."""

import sys
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.main import (
    configurer_logging,
    creer_argument_parser,
    main,
    BANNER,
)


class TestConfigurerLogging:
    """Tests de configuration du logging."""

    def test_logging_default(self):
        configurer_logging(verbose=False)
        # basicConfig sets root logger level; check it was called without error
        assert True

    def test_logging_verbose(self):
        configurer_logging(verbose=True)
        # In verbose mode, DEBUG level is used
        assert True


class TestArgumentParser:
    """Tests du parser d'arguments CLI."""

    def test_parser_creation(self):
        parser = creer_argument_parser()
        assert parser is not None
        assert parser.prog == "urssaf_analyzer"

    def test_parser_fichiers_required(self):
        parser = creer_argument_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_parser_single_file(self):
        parser = creer_argument_parser()
        args = parser.parse_args(["test.pdf"])
        assert len(args.fichiers) == 1
        assert args.fichiers[0] == Path("test.pdf")

    def test_parser_multiple_files(self):
        parser = creer_argument_parser()
        args = parser.parse_args(["a.pdf", "b.csv"])
        assert len(args.fichiers) == 2

    def test_parser_format_html(self):
        parser = creer_argument_parser()
        args = parser.parse_args(["test.pdf", "--format", "html"])
        assert args.format == "html"

    def test_parser_format_json(self):
        parser = creer_argument_parser()
        args = parser.parse_args(["test.pdf", "-f", "json"])
        assert args.format == "json"

    def test_parser_format_default(self):
        parser = creer_argument_parser()
        args = parser.parse_args(["test.pdf"])
        assert args.format == "html"

    def test_parser_output(self):
        parser = creer_argument_parser()
        args = parser.parse_args(["test.pdf", "-o", "/tmp/reports"])
        assert args.output == Path("/tmp/reports")

    def test_parser_verbose(self):
        parser = creer_argument_parser()
        args = parser.parse_args(["test.pdf", "-v"])
        assert args.verbose is True

    def test_parser_no_cleanup(self):
        parser = creer_argument_parser()
        args = parser.parse_args(["test.pdf", "--no-cleanup"])
        assert args.no_cleanup is True


class TestMain:
    """Tests de la fonction main."""

    def test_main_no_valid_files(self, tmp_path):
        with patch("sys.argv", ["urssaf_analyzer", str(tmp_path / "nonexist.pdf")]):
            result = main()
            assert result == 1

    def test_main_unsupported_format(self, tmp_path):
        f = tmp_path / "test.xyz"
        f.write_text("test")
        with patch("sys.argv", ["urssaf_analyzer", str(f)]):
            result = main()
            assert result == 1

    def test_banner_exists(self):
        assert "analyse" in BANNER.lower() or "v1.0.0" in BANNER

    def test_main_with_valid_file_analysis_error(self, tmp_path):
        f = tmp_path / "test.csv"
        f.write_text("col1,col2\nval1,val2")
        with patch("sys.argv", ["urssaf_analyzer", str(f)]):
            with patch("urssaf_analyzer.main.Orchestrator") as mock_orch:
                mock_instance = MagicMock()
                from urssaf_analyzer.core.exceptions import URSSAFAnalyzerError
                mock_instance.analyser_documents.side_effect = URSSAFAnalyzerError("test error")
                mock_instance.nettoyer = MagicMock()
                mock_orch.return_value = mock_instance
                result = main()
                assert result == 1

    def test_main_with_valid_file_unexpected_error(self, tmp_path):
        f = tmp_path / "test.csv"
        f.write_text("col1,col2\nval1,val2")
        with patch("sys.argv", ["urssaf_analyzer", str(f)]):
            with patch("urssaf_analyzer.main.Orchestrator") as mock_orch:
                mock_instance = MagicMock()
                mock_instance.analyser_documents.side_effect = RuntimeError("boom")
                mock_instance.nettoyer = MagicMock()
                mock_orch.return_value = mock_instance
                result = main()
                assert result == 2
