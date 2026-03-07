"""Tests unitaires exhaustifs de la validation des donnees entrantes.

Niveau bancaire : chaque validateur est teste avec cas normaux, limites, injection.
Ref: OWASP Input Validation Cheat Sheet, ISO 27001 A.14.
"""

import pytest
from decimal import Decimal

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from urssaf_analyzer.utils.input_validator import (
    validate_email, validate_password, validate_siret, validate_siren,
    validate_nir, validate_amount, validate_rate, validate_file_upload,
    validate_string, ValidationError, _check_luhn,
)


# ================================================================
# EMAIL
# ================================================================

class TestValidateEmail:

    def test_valid_email(self):
        assert validate_email("user@example.com") == "user@example.com"

    def test_email_normalized_lowercase(self):
        assert validate_email("User@Example.COM") == "user@example.com"

    def test_email_stripped(self):
        assert validate_email("  user@example.com  ") == "user@example.com"

    def test_email_with_plus(self):
        assert validate_email("user+tag@example.com") == "user+tag@example.com"

    def test_email_empty_raises(self):
        with pytest.raises(ValidationError):
            validate_email("")

    def test_email_none_raises(self):
        with pytest.raises(ValidationError):
            validate_email(None)

    def test_email_no_at_raises(self):
        with pytest.raises(ValidationError):
            validate_email("userexample.com")

    def test_email_no_domain_raises(self):
        with pytest.raises(ValidationError):
            validate_email("user@")

    def test_email_too_long_raises(self):
        with pytest.raises(ValidationError):
            validate_email("a" * 250 + "@b.fr")


# ================================================================
# PASSWORD
# ================================================================

class TestValidatePassword:

    def test_valid_password(self):
        assert validate_password("SecurePass123!") == "SecurePass123!"

    def test_password_too_short(self):
        with pytest.raises(ValidationError, match="trop court"):
            validate_password("Short1!")

    def test_password_too_long(self):
        with pytest.raises(ValidationError, match="trop long"):
            validate_password("A1!" + "a" * 130)

    def test_password_no_uppercase(self):
        with pytest.raises(ValidationError, match="majuscule"):
            validate_password("alllowercase1!")

    def test_password_no_lowercase(self):
        with pytest.raises(ValidationError, match="minuscule"):
            validate_password("ALLUPPERCASE1!")

    def test_password_no_digit(self):
        with pytest.raises(ValidationError, match="chiffre"):
            validate_password("NoDigitsHere!X")

    def test_password_empty(self):
        with pytest.raises(ValidationError):
            validate_password("")

    def test_password_none(self):
        with pytest.raises(ValidationError):
            validate_password(None)


# ================================================================
# SIRET / SIREN (Luhn)
# ================================================================

class TestValidateSIRET:

    def test_valid_siret(self):
        # SIRET valide Luhn: 73282932000074
        result = validate_siret("73282932000074")
        assert result == "73282932000074"

    def test_siret_with_spaces(self):
        result = validate_siret("732 829 320 00074")
        assert result == "73282932000074"

    def test_siret_wrong_length(self):
        with pytest.raises(ValidationError, match="14 chiffres"):
            validate_siret("1234")

    def test_siret_empty(self):
        with pytest.raises(ValidationError):
            validate_siret("")

    def test_siret_invalid_luhn(self):
        with pytest.raises(ValidationError, match="cle de controle"):
            validate_siret("12345678901235")  # Invalid Luhn


class TestValidateSIREN:

    def test_valid_siren(self):
        result = validate_siren("732829320")
        assert result == "732829320"

    def test_siren_wrong_length(self):
        with pytest.raises(ValidationError, match="9 chiffres"):
            validate_siren("12345")

    def test_siren_invalid_luhn(self):
        with pytest.raises(ValidationError, match="cle de controle"):
            validate_siren("123456780")


# ================================================================
# NIR
# ================================================================

class TestValidateNIR:

    def test_valid_nir(self):
        result = validate_nir("1850175123456")
        assert result == "1850175123456"

    def test_nir_with_spaces(self):
        result = validate_nir("1 85 01 75 123 456")
        assert result == "1850175123456"

    def test_nir_invalid_start(self):
        with pytest.raises(ValidationError):
            validate_nir("3850175123456")

    def test_nir_empty(self):
        with pytest.raises(ValidationError):
            validate_nir("")


# ================================================================
# AMOUNTS
# ================================================================

class TestValidateAmount:

    def test_valid_amount(self):
        assert validate_amount("1234.56") == Decimal("1234.56")

    def test_amount_int(self):
        assert validate_amount(1000) == Decimal("1000")

    def test_amount_negative(self):
        # Les montants negatifs sont autorises (credits)
        assert validate_amount("-100") == Decimal("-100")

    def test_amount_too_large(self):
        with pytest.raises(ValidationError, match="hors limites"):
            validate_amount("9999999999.99")

    def test_amount_invalid(self):
        with pytest.raises(ValidationError, match="invalide"):
            validate_amount("not-a-number")

    def test_amount_none(self):
        with pytest.raises(ValidationError, match="requis"):
            validate_amount(None)


# ================================================================
# RATES
# ================================================================

class TestValidateRate:

    def test_valid_rate_decimal(self):
        assert validate_rate("0.07") == Decimal("0.07")

    def test_valid_rate_percent(self):
        assert validate_rate("7.0") == Decimal("7.0")

    def test_rate_zero(self):
        assert validate_rate("0") == Decimal("0")

    def test_rate_negative(self):
        with pytest.raises(ValidationError, match="negatif"):
            validate_rate("-1")

    def test_rate_over_100(self):
        with pytest.raises(ValidationError, match="100"):
            validate_rate("101")


# ================================================================
# FILE UPLOAD
# ================================================================

class TestValidateFileUpload:

    def test_valid_csv(self):
        assert validate_file_upload("data.csv", 1024) == "data.csv"

    def test_valid_pdf(self):
        assert validate_file_upload("report.pdf", 5000) == "report.pdf"

    def test_valid_xlsx(self):
        assert validate_file_upload("paie.xlsx", 10000) == "paie.xlsx"

    def test_invalid_extension(self):
        with pytest.raises(ValidationError, match="non autorisee"):
            validate_file_upload("hack.exe", 1024)

    def test_empty_filename(self):
        with pytest.raises(ValidationError, match="requis"):
            validate_file_upload("", 1024)

    def test_file_too_large(self):
        with pytest.raises(ValidationError, match="volumineux"):
            validate_file_upload("data.csv", 200 * 1024 * 1024)

    def test_file_empty_size(self):
        with pytest.raises(ValidationError, match="vide"):
            validate_file_upload("data.csv", 0)

    def test_filename_too_long(self):
        with pytest.raises(ValidationError, match="trop long"):
            validate_file_upload("a" * 260 + ".csv", 1024)


# ================================================================
# STRING VALIDATION & INJECTION
# ================================================================

class TestValidateString:

    def test_valid_string(self):
        assert validate_string("Hello World", "test") == "Hello World"

    def test_empty_string_rejected(self):
        with pytest.raises(ValidationError, match="vide"):
            validate_string("", "test")

    def test_empty_string_allowed(self):
        validate_string("", "test", allow_empty=True)

    def test_string_too_long(self):
        with pytest.raises(ValidationError, match="(?i)trop long"):
            validate_string("a" * 20000, "test")

    def test_xss_injection_blocked(self):
        with pytest.raises(ValidationError, match="dangereux"):
            validate_string("<script>alert(1)</script>", "test")

    def test_sql_injection_blocked(self):
        with pytest.raises(ValidationError, match="dangereux"):
            validate_string("'; DROP TABLE users", "test")

    def test_js_protocol_blocked(self):
        with pytest.raises(ValidationError, match="dangereux"):
            validate_string("javascript:alert(1)", "test")

    def test_union_select_blocked(self):
        with pytest.raises(ValidationError, match="dangereux"):
            validate_string("1 UNION SELECT * FROM passwords", "test")


# ================================================================
# LUHN ALGORITHM
# ================================================================

class TestLuhn:

    def test_luhn_valid(self):
        assert _check_luhn("79927398713") is True

    def test_luhn_invalid(self):
        assert _check_luhn("79927398710") is False

    def test_luhn_single_digit(self):
        assert _check_luhn("0") is True
