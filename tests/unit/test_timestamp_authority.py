"""Tests de l'horodatage certifie RFC 3161 / eIDAS.

Couvre :
- Horodatage fallback (horloge systeme)
- Construction de requete RFC 3161
- Verification de jetons
- Integration avec la chaine de preuve
"""

import pytest

from urssaf_analyzer.security.timestamp_authority import (
    TimestampAuthority,
    TimestampToken,
    _sha256_hex,
    _build_rfc3161_request,
)


class TestTimestampToken:
    def test_fallback_token_creation(self):
        token = TimestampToken(
            timestamp_utc="2026-03-04T12:00:00+00:00",
            hash_algorithm="SHA-256",
            data_hash="abc123",
            certified=False,
            method="system_clock",
        )
        assert token.certified is False
        assert token.method == "system_clock"

    def test_fallback_token_dict(self):
        token = TimestampToken(
            timestamp_utc="2026-03-04T12:00:00+00:00",
            hash_algorithm="SHA-256",
            data_hash="abc123",
            certified=False,
            method="system_clock",
        )
        d = token.to_dict()
        assert d["certified"] is False
        assert "avertissement" in d
        assert "non certifie" in d["avertissement"]

    def test_certified_token_dict(self):
        token = TimestampToken(
            timestamp_utc="2026-03-04T12:00:00+00:00",
            hash_algorithm="SHA-256",
            data_hash="abc123",
            tsa_url="http://tsa.test.com",
            certified=True,
            method="rfc3161",
        )
        d = token.to_dict()
        assert d["certified"] is True
        assert "conformite" in d
        assert d["tsa_url"] == "http://tsa.test.com"
        assert "avertissement" not in d


class TestSha256Hex:
    def test_deterministic(self):
        h1 = _sha256_hex("hello")
        h2 = _sha256_hex("hello")
        assert h1 == h2

    def test_different_inputs(self):
        h1 = _sha256_hex("hello")
        h2 = _sha256_hex("world")
        assert h1 != h2

    def test_hex_format(self):
        h = _sha256_hex("test")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


class TestBuildRfc3161Request:
    def test_request_format(self):
        hash_bytes = bytes.fromhex(_sha256_hex("test"))
        request = _build_rfc3161_request(hash_bytes)
        # Doit commencer par un tag SEQUENCE ASN.1 (0x30)
        assert request[0] == 0x30
        # Doit contenir le hash
        assert hash_bytes in request

    def test_request_deterministic(self):
        hash_bytes = bytes.fromhex(_sha256_hex("test"))
        r1 = _build_rfc3161_request(hash_bytes)
        r2 = _build_rfc3161_request(hash_bytes)
        assert r1 == r2


class TestTimestampAuthority:
    def test_fallback_when_disabled(self):
        tsa = TimestampAuthority(enabled=False)
        token = tsa.timestamp("donnees de test")
        assert token.certified is False
        assert token.method == "system_clock"
        assert token.data_hash == _sha256_hex("donnees de test")

    def test_fallback_when_tsa_unreachable(self):
        tsa = TimestampAuthority(
            tsa_urls=["http://192.0.2.1:9999"],  # Adresse RFC 5737 (non routable)
            timeout_seconds=1,
        )
        token = tsa.timestamp("donnees de test")
        assert token.certified is False
        assert token.method == "system_clock"

    def test_timestamp_hash_fallback(self):
        tsa = TimestampAuthority(enabled=False)
        data_hash = _sha256_hex("test data")
        token = tsa.timestamp_hash(data_hash)
        assert token.data_hash == data_hash
        assert token.certified is False

    def test_verify_valid_token(self):
        tsa = TimestampAuthority(enabled=False)
        data = "donnees a horodater"
        token = tsa.timestamp(data)
        result = tsa.verify_token(token, data)
        assert result["hash_valid"] is True

    def test_verify_invalid_token(self):
        tsa = TimestampAuthority(enabled=False)
        token = tsa.timestamp("original")
        result = tsa.verify_token(token, "modifie")
        assert result["hash_valid"] is False
        assert "erreur" in result

    def test_verify_certified_note(self):
        token = TimestampToken(
            timestamp_utc="2026-03-04T12:00:00+00:00",
            hash_algorithm="SHA-256",
            data_hash=_sha256_hex("test"),
            certified=True,
            method="rfc3161",
        )
        tsa = TimestampAuthority(enabled=False)
        result = tsa.verify_token(token, "test")
        assert result["hash_valid"] is True
        assert "note" in result

    def test_timestamp_includes_utc(self):
        tsa = TimestampAuthority(enabled=False)
        token = tsa.timestamp("test")
        assert "+" in token.timestamp_utc or "Z" in token.timestamp_utc
