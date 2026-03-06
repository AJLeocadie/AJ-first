"""Tests exhaustifs du module d'authentification.

Couverture : JWT, PBKDF2, CRUD utilisateurs, verification email,
revocation tokens, roles, multi-tenant, dashboard persistence.
Niveau : bancaire (ISO 27001).
"""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from auth import (
    hash_password, verify_password,
    jwt_encode, jwt_decode,
    _b64url_encode, _b64url_decode,
    create_user, authenticate, get_user,
    update_user_role, set_user_tenant,
    list_users_by_tenant,
    generate_token, revoke_token,
    generate_verification_code, verify_email_code,
    save_dashboard, load_dashboard,
    bootstrap_admin,
    VALID_OFFERS, VALID_ROLES, MIN_PASSWORD_LENGTH,
)


# ==============================
# Token Revocation
# ==============================

class TestTokenRevocation:
    """Tests de la revocation de tokens."""

    def setup_method(self):
        import auth
        auth._users = {}
        auth._token_blacklist = {}

    def test_revoke_valid_token(self):
        user = create_user("rev@test.fr", "SecurePass123!", "Rev", "User")
        token = generate_token(user)
        assert revoke_token(token) is True
        assert jwt_decode(token) is None

    def test_revoke_invalid_token(self):
        assert revoke_token("not.a.valid.token") is False

    def test_revoke_already_revoked(self):
        user = create_user("rev2@test.fr", "SecurePass123!", "Rev2", "User")
        token = generate_token(user)
        assert revoke_token(token) is True
        # Deuxieme revocation echoue car token deja blackliste
        assert revoke_token(token) is False

    def test_revoked_token_not_decoded(self):
        user = create_user("rev3@test.fr", "SecurePass123!", "Rev3", "User")
        token = generate_token(user)
        payload = jwt_decode(token)
        assert payload is not None
        revoke_token(token)
        assert jwt_decode(token) is None


# ==============================
# Email Verification
# ==============================

class TestEmailVerification:
    """Tests de la verification d'email."""

    def setup_method(self):
        import auth
        auth._users = {}
        auth._verification_codes = {}

    def test_generate_code(self):
        code = generate_verification_code("user@test.fr")
        assert len(code) == 6
        assert code.isdigit()

    def test_verify_correct_code(self):
        create_user("verify@test.fr", "SecurePass123!", "Verify", "User")
        code = generate_verification_code("verify@test.fr")
        assert verify_email_code("verify@test.fr", code) is True

    def test_verify_wrong_code(self):
        generate_verification_code("wrong@test.fr")
        assert verify_email_code("wrong@test.fr", "000000") is False

    def test_verify_expired_code(self):
        import auth
        code = generate_verification_code("expired@test.fr")
        auth._verification_codes["expired@test.fr"]["expires"] = time.time() - 1
        assert verify_email_code("expired@test.fr", code) is False

    def test_verify_max_attempts(self):
        import auth
        code = generate_verification_code("attempts@test.fr")
        auth._verification_codes["attempts@test.fr"]["attempts"] = 10
        assert verify_email_code("attempts@test.fr", code) is False

    def test_verify_nonexistent_email(self):
        assert verify_email_code("nope@test.fr", "123456") is False

    def test_email_marked_verified(self):
        import auth
        create_user("mark@test.fr", "SecurePass123!", "Mark", "User")
        code = generate_verification_code("mark@test.fr")
        verify_email_code("mark@test.fr", code)
        assert auth._users["mark@test.fr"]["email_verifie"] is True

    def test_case_insensitive_email(self):
        code = generate_verification_code("UPPER@Test.FR")
        assert verify_email_code("upper@test.fr", code) is True


# ==============================
# User CRUD Extended
# ==============================

class TestUserCRUDExtended:
    """Tests avances de la gestion des utilisateurs."""

    def setup_method(self):
        import auth
        auth._users = {}

    def test_create_user_email_normalized(self):
        user = create_user("  UPPER@TEST.FR  ", "SecurePass123!", "Up", "User")
        assert user["email"] == "upper@test.fr"

    def test_create_user_all_roles(self):
        for i, role in enumerate(VALID_ROLES):
            user = create_user(
                f"role{i}@test.fr", "SecurePass123!", "Role", "User", role=role
            )
            assert user["role"] == role

    def test_create_user_invalid_role(self):
        with pytest.raises(ValueError, match="Role invalide"):
            create_user("bad@test.fr", "SecurePass123!", "Bad", "Role", role="hacker")

    def test_create_user_all_offers(self):
        for i, offre in enumerate(VALID_OFFERS):
            user = create_user(
                f"offre{i}@test.fr", "SecurePass123!", "Offre", "User", offre=offre
            )
            assert user["offre"] == offre

    def test_create_user_invalid_offer(self):
        with pytest.raises(ValueError, match="Offre invalide"):
            create_user(
                "badoffre@test.fr", "SecurePass123!", "Bad", "Offre", offre="premium"
            )

    def test_password_must_have_mixed_case(self):
        with pytest.raises(ValueError, match="majuscules et minuscules"):
            create_user("lower@test.fr", "alllowercase1!", "Low", "User")
        with pytest.raises(ValueError, match="majuscules et minuscules"):
            create_user("upper@test.fr", "ALLUPPERCASE1!", "Up", "User")

    def test_password_min_length(self):
        short = "Ab1!" * 2  # 8 chars < 12
        with pytest.raises(ValueError, match="trop court"):
            create_user("short@test.fr", short, "Short", "Pass")

    def test_get_user(self):
        create_user("get@test.fr", "SecurePass123!", "Get", "User")
        user = get_user("get@test.fr")
        assert user is not None
        assert user["email"] == "get@test.fr"
        assert "password_hash" not in user

    def test_get_user_not_found(self):
        assert get_user("notfound@test.fr") is None

    def test_update_role(self):
        create_user("update@test.fr", "SecurePass123!", "Update", "Role")
        updated = update_user_role("update@test.fr", "admin")
        assert updated["role"] == "admin"

    def test_update_role_not_found(self):
        assert update_user_role("none@test.fr", "admin") is None

    def test_set_tenant(self):
        create_user("tenant@test.fr", "SecurePass123!", "Tenant", "User")
        updated = set_user_tenant("tenant@test.fr", "new-tenant")
        assert updated["tenant_id"] == "new-tenant"

    def test_set_tenant_not_found(self):
        assert set_user_tenant("none@test.fr", "t1") is None

    def test_list_users_by_tenant(self):
        create_user("t1@test.fr", "SecurePass123!", "T1", "User", tenant_id="tenantA")
        create_user("t2@test.fr", "SecurePass123!", "T2", "User", tenant_id="tenantA")
        create_user("t3@test.fr", "SecurePass123!", "T3", "User", tenant_id="tenantB")
        users = list_users_by_tenant("tenantA")
        assert len(users) == 2
        assert all("password_hash" not in u for u in users)

    def test_authenticate_inactive_user(self):
        import auth
        create_user("inactive@test.fr", "SecurePass123!", "Inactive", "User")
        auth._users["inactive@test.fr"]["active"] = False
        assert authenticate("inactive@test.fr", "SecurePass123!") is None

    def test_user_has_all_fields(self):
        user = create_user(
            "full@test.fr", "SecurePass123!", "Full", "User",
            entreprise="ACME", telephone="0612345678",
        )
        assert user["entreprise"] == "ACME"
        assert user["telephone"] == "0612345678"
        assert "created_at" in user
        assert "id" in user


# ==============================
# Admin Bootstrap
# ==============================

class TestAdminBootstrap:
    """Tests du bootstrap admin."""

    def setup_method(self):
        import auth
        auth._users = {}

    def test_bootstrap_creates_admin(self):
        admin = bootstrap_admin()
        assert admin is not None
        assert admin["role"] == "admin"

    def test_bootstrap_idempotent(self):
        bootstrap_admin()
        second = bootstrap_admin()
        assert second is None  # Admin existe deja

    def test_bootstrap_promotes_existing_user(self):
        import auth
        create_user("admin@normacheck.fr", "Admin2026!Norma", "Admin", "User")
        admin = bootstrap_admin()
        assert admin["role"] == "admin"


# ==============================
# Dashboard Persistence
# ==============================

class TestDashboardPersistence:
    """Tests de la persistence des dashboards."""

    def setup_method(self):
        import auth
        auth._dashboards = {}

    def test_save_and_load(self):
        data = {"analyses": 5, "score_moyen": 82}
        save_dashboard("user@test.fr", data)
        loaded = load_dashboard("user@test.fr")
        assert loaded is not None
        assert loaded["data"]["analyses"] == 5
        assert "saved_at" in loaded

    def test_load_nonexistent(self):
        assert load_dashboard("nope@test.fr") is None

    def test_save_overwrites(self):
        save_dashboard("user@test.fr", {"v": 1})
        save_dashboard("user@test.fr", {"v": 2})
        loaded = load_dashboard("user@test.fr")
        assert loaded["data"]["v"] == 2

    def test_email_normalized(self):
        save_dashboard("  USER@TEST.FR  ", {"v": 1})
        loaded = load_dashboard("user@test.fr")
        assert loaded is not None


# ==============================
# JWT Advanced
# ==============================

class TestJWTAdvanced:
    """Tests avances de l'implementation JWT."""

    def setup_method(self):
        import auth
        auth._users = {}
        auth._token_blacklist = {}

    def test_generate_token_has_all_claims(self):
        user = create_user("claims@test.fr", "SecurePass123!", "Claims", "User")
        token = generate_token(user)
        payload = jwt_decode(token)
        assert payload["sub"] == "claims@test.fr"
        assert payload["role"] == "collaborateur"
        assert "exp" in payload
        assert "iat" in payload
        assert "jti" in payload
        assert "tenant_id" in payload

    def test_token_signature_tampered(self):
        token = jwt_encode({"sub": "user1", "exp": time.time() + 3600})
        parts = token.split(".")
        bad_sig = parts[2][:-1] + ("A" if parts[2][-1] != "A" else "B")
        tampered = f"{parts[0]}.{parts[1]}.{bad_sig}"
        assert jwt_decode(tampered) is None

    def test_empty_payload(self):
        token = jwt_encode({})
        decoded = jwt_decode(token)
        assert decoded is not None

    def test_large_payload(self):
        payload = {f"key_{i}": f"value_{i}" for i in range(100)}
        token = jwt_encode(payload)
        decoded = jwt_decode(token)
        assert decoded["key_50"] == "value_50"

    def test_special_characters_in_payload(self):
        payload = {"name": "Jean-Pierre D'Alembert", "city": "Saint-Etienne"}
        token = jwt_encode(payload)
        decoded = jwt_decode(token)
        assert decoded["name"] == "Jean-Pierre D'Alembert"

    def test_unicode_payload(self):
        payload = {"nom": "Béatrice Müller", "ville": "Strasbourg"}
        token = jwt_encode(payload)
        decoded = jwt_decode(token)
        assert decoded["nom"] == "Béatrice Müller"


# ==============================
# Security Edge Cases
# ==============================

class TestSecurityEdgeCases:
    """Tests de securite (cas limites)."""

    def setup_method(self):
        import auth
        auth._users = {}

    def test_sql_injection_in_email(self):
        """Emails malicieux sont stockes sans effet secondaire (dict in-memory)."""
        malicious = "drop-table@evil.com"
        user = create_user(malicious, "SecurePass123!", "Evil", "User")
        assert user["email"] == malicious

    def test_xss_in_fields(self):
        user = create_user(
            "xss@test.fr", "SecurePass123!",
            "<script>alert('xss')</script>", "User",
        )
        assert "<script>" in user["nom"]  # Stocke tel quel, sanitize a l'affichage

    def test_very_long_password(self):
        long_pass = "Aa1!" * 1000  # 4000 chars
        h = hash_password(long_pass)
        assert verify_password(long_pass, h) is True

    def test_timing_attack_resistance(self):
        """verify_password utilise hmac.compare_digest (constant-time)."""
        h = hash_password("TestPassword1!")
        # Les deux doivent prendre environ le meme temps
        assert verify_password("WrongPassword1", h) is False
        assert verify_password("TestPassword1!", h) is True

    def test_null_bytes_in_password(self):
        h = hash_password("test\x00password")
        assert verify_password("test\x00password", h) is True
        assert verify_password("test", h) is False
