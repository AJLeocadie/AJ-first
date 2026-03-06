"""Tests exhaustifs du module de validation stricte des entrees.

Couverture : email, password, SIRET, SIREN, NIR, montants,
taux, fichiers, injections.
"""

import sys
from pathlib import Path
from decimal import Decimal

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.utils.input_validator import (
    validate_email, validate_password, validate_siret, validate_siren,
    validate_nir, validate_amount, validate_rate, validate_file_upload,
    validate_string, ValidationError, _check_luhn,
)


class TestValidateEmail:
    """Tests de validation d'email."""

    def test_valid_email(self):
        assert validate_email("user@example.com") == "user@example.com"

    def test_normalized(self):
        assert validate_email("  USER@EXAMPLE.COM  ") == "user@example.com"

    def test_invalid_format(self):
        with pytest.raises(ValidationError, match="email"):
            validate_email("not-an-email")

    def test_empty(self):
        with pytest.raises(ValidationError):
            validate_email("")

    def test_none(self):
        with pytest.raises(ValidationError):
            validate_email(None)

    def test_too_long(self):
        with pytest.raises(ValidationError, match="trop long"):
            validate_email("a" * 250 + "@test.com")


class TestValidatePassword:
    """Tests de validation de mot de passe."""

    def test_valid(self):
        assert validate_password("SecurePass123!") == "SecurePass123!"

    def test_too_short(self):
        with pytest.raises(ValidationError, match="court"):
            validate_password("Short1A")

    def test_no_uppercase(self):
        with pytest.raises(ValidationError, match="majuscule"):
            validate_password("alllowercase1!")

    def test_no_lowercase(self):
        with pytest.raises(ValidationError, match="minuscule"):
            validate_password("ALLUPPERCASE1!")

    def test_no_digit(self):
        with pytest.raises(ValidationError, match="chiffre"):
            validate_password("NoDigitsHere!")

    def test_too_long(self):
        with pytest.raises(ValidationError, match="long"):
            validate_password("Aa1" * 50)

    def test_empty(self):
        with pytest.raises(ValidationError):
            validate_password("")


class TestValidateSIRET:
    """Tests de validation SIRET."""

    def test_valid_siret(self):
        # SIRET de La Poste (cas special Luhn)
        result = validate_siret("35600000000048")
        assert result == "35600000000048"

    def test_invalid_length(self):
        with pytest.raises(ValidationError, match="14 chiffres"):
            validate_siret("1234")

    def test_invalid_luhn(self):
        with pytest.raises(ValidationError, match="cle de controle"):
            validate_siret("12345678901234")

    def test_with_spaces(self):
        result = validate_siret("356 000 000 00048")
        assert result == "35600000000048"


class TestValidateSIREN:
    """Tests de validation SIREN."""

    def test_valid_siren(self):
        result = validate_siren("356000000")
        assert result == "356000000"

    def test_invalid_length(self):
        with pytest.raises(ValidationError, match="9 chiffres"):
            validate_siren("1234")


class TestValidateNIR:
    """Tests de validation NIR."""

    def test_valid_nir(self):
        result = validate_nir("1850175123456")
        assert result == "1850175123456"

    def test_invalid_format(self):
        with pytest.raises(ValidationError, match="NIR"):
            validate_nir("ABC")


class TestValidateAmount:
    """Tests de validation des montants."""

    def test_valid_amount(self):
        assert validate_amount("1234.56") == Decimal("1234.56")

    def test_negative_amount(self):
        assert validate_amount("-500") == Decimal("-500")

    def test_invalid_amount(self):
        with pytest.raises(ValidationError):
            validate_amount("not_a_number")

    def test_none_amount(self):
        with pytest.raises(ValidationError):
            validate_amount(None)

    def test_out_of_range(self):
        with pytest.raises(ValidationError, match="limites"):
            validate_amount("9999999999.99")

    def test_zero(self):
        assert validate_amount("0") == Decimal("0")


class TestValidateRate:
    """Tests de validation des taux."""

    def test_valid_rate(self):
        assert validate_rate("0.07") == Decimal("0.07")

    def test_percentage(self):
        assert validate_rate("7.0") == Decimal("7.0")

    def test_negative(self):
        with pytest.raises(ValidationError, match="negatif"):
            validate_rate("-1")

    def test_over_100(self):
        with pytest.raises(ValidationError, match="100"):
            validate_rate("150")


class TestValidateFileUpload:
    """Tests de validation des uploads de fichiers."""

    def test_valid_csv(self):
        assert validate_file_upload("test.csv", 1024) == "test.csv"

    def test_valid_pdf(self):
        assert validate_file_upload("report.pdf", 5000) == "report.pdf"

    def test_invalid_extension(self):
        with pytest.raises(ValidationError, match="non autorisee"):
            validate_file_upload("virus.exe", 1024)

    def test_empty_filename(self):
        with pytest.raises(ValidationError):
            validate_file_upload("", 1024)

    def test_empty_file(self):
        with pytest.raises(ValidationError, match="vide"):
            validate_file_upload("test.csv", 0)

    def test_too_large(self):
        with pytest.raises(ValidationError, match="volumineux"):
            validate_file_upload("huge.csv", 200 * 1024 * 1024)


class TestValidateString:
    """Tests de validation des chaines."""

    def test_valid_string(self):
        assert validate_string("Hello World", "test") == "Hello World"

    def test_empty_not_allowed(self):
        with pytest.raises(ValidationError, match="requis"):
            validate_string("", "test")

    def test_empty_allowed(self):
        assert validate_string("", "test", allow_empty=True) == ""

    def test_too_long(self):
        with pytest.raises(ValidationError, match="long"):
            validate_string("a" * 20000, "test")

    def test_injection_script(self):
        with pytest.raises(ValidationError, match="dangereux"):
            validate_string("<script>alert('xss')</script>", "input")

    def test_injection_sql(self):
        with pytest.raises(ValidationError, match="dangereux"):
            validate_string("'; DROP TABLE users; --", "input")


class TestLuhnAlgorithm:
    """Tests de l'algorithme de Luhn."""

    def test_valid_number(self):
        assert _check_luhn("79927398713") is True

    def test_invalid_number(self):
        assert _check_luhn("79927398710") is False

    def test_la_poste_siret(self):
        # La Poste a un SIRET special
        assert _check_luhn("35600000000048") is True
