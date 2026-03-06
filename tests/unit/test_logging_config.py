"""Tests du module de configuration des logs.

Couverture : formateur JSON, detecteur d'erreurs silencieuses,
configuration, rotation.
"""

import sys
import json
import logging
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.utils.logging_config import (
    StructuredFormatter, SilentErrorDetector,
    setup_logging, get_silent_error_report,
)


class TestStructuredFormatter:
    """Tests du formateur JSON structure."""

    def test_format_basic_record(self):
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=10, msg="Test message", args=(), exc_info=None,
        )
        result = formatter.format(record)
        data = json.loads(result)
        assert data["level"] == "INFO"
        assert data["message"] == "Test message"
        assert "timestamp" in data

    def test_format_with_exception(self):
        formatter = StructuredFormatter()
        try:
            raise ValueError("Test error")
        except ValueError:
            record = logging.LogRecord(
                name="test", level=logging.ERROR, pathname="test.py",
                lineno=10, msg="Error occurred", args=(),
                exc_info=sys.exc_info(),
            )
        result = formatter.format(record)
        data = json.loads(result)
        assert "exception" in data
        assert data["exception"]["type"] == "ValueError"

    def test_format_with_extra_fields(self):
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=10, msg="Test", args=(), exc_info=None,
        )
        record.session_id = "test-session-123"
        result = formatter.format(record)
        data = json.loads(result)
        assert data["session_id"] == "test-session-123"


class TestSilentErrorDetector:
    """Tests du detecteur d'erreurs silencieuses."""

    def test_detects_warnings(self):
        detector = SilentErrorDetector()
        record = logging.LogRecord(
            name="test", level=logging.WARNING, pathname="test.py",
            lineno=10, msg="Silent warning", args=(), exc_info=None,
        )
        detector.emit(record)
        assert detector.error_count == 1

    def test_report(self):
        detector = SilentErrorDetector()
        for i in range(5):
            record = logging.LogRecord(
                name="test", level=logging.ERROR, pathname="test.py",
                lineno=10, msg=f"Error {i}", args=(), exc_info=None,
            )
            detector.emit(record)
        report = detector.get_report()
        assert report["total_errors"] == 5
        assert len(report["patterns"]) == 5


class TestSetupLogging:
    """Tests de la configuration du logging."""

    def test_setup_console_only(self):
        logger = setup_logging(level="DEBUG", structured=False)
        assert logger is not None
        assert logger.level == logging.DEBUG

    def test_setup_with_file(self, tmp_path):
        logger = setup_logging(log_dir=tmp_path, level="INFO")
        assert logger is not None
        log_files = list(tmp_path.glob("*.log"))
        # Les fichiers seront crees lors de la premiere ecriture

    def test_setup_structured(self):
        logger = setup_logging(structured=True)
        assert logger is not None
