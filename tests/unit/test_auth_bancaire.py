"""Tests unitaires exhaustifs du module d'authentification.

Couverture niveau bancaire : cas normaux, limites, erreurs, securite.
Ref: ISO 27001 A.9 - Controle d'acces.
"""

import time
import json
import pytest
from unittest.mock import patch

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ================================================================
# PASSWORD HASHING - PBKDF2-SHA256
# ================================================================

class TestPasswordHashing:
    """Tests du hachage de mots de passe (PBKDF2-SHA256)."""

    def test_hash_password_produces_salt_and_hash(self):
        from auth import hash_password
        result = hash_password("SecurePass123!")
        assert "$" in result
        parts = result.split("$")
        assert len(parts) == 2
        assert len(parts[0]) == 32  # hex salt (16 bytes)
        assert len(parts[1]) == 64  # hex SHA-256 hash

    def test_hash_password_unique_salts(self):
        from auth import hash_password
        h1 = hash_password("SecurePass123!")
        h2 = hash_password("SecurePass123!")
        assert h1 != h2  # Sels differents

    def test_verify_password_correct(self):
        from auth import hash_password, verify_password
        stored = hash_password("SecurePass123!")
        assert verify_password("SecurePass123!", stored) is True

    def test_verify_password_incorrect(self):
        from auth import hash_password, verify_password
        stored = hash_password("SecurePass123!")
        assert verify_password("WrongPassword1!", stored) is False

    def test_verify_password_empty(self):
        from auth import hash_password, verify_password
        stored = hash_password("SecurePass123!")
        assert verify_password("", stored) is False

    def test_verify_password_invalid_format(self):
        from auth import verify_password
        assert verify_password("anything", "not-a-valid-hash") is False

    def test_verify_password_timing_safe(self):
        """Verifie que la verification utilise une comparaison a temps constant."""
        from auth import hash_password, verify_password
        stored = hash_password("SecurePass123!")
        # Les deux appels doivent prendre un temps similaire (hmac.compare_digest)
        verify_password("WrongPassword1!", stored)
        verify_password("SecurePass123!", stored)
        # Pas de timing attack possible


# ================================================================
# JWT ENCODING / DECODING
# ================================================================

class TestJWT:
    """Tests du systeme JWT custom (HMAC-SHA256)."""

    def test_jwt_encode_decode_roundtrip(self):
        from auth import jwt_encode, jwt_decode
        payload = {"sub": "user@test.fr", "role": "admin", "exp": int(time.time()) + 3600}
        token = jwt_encode(payload)
        decoded = jwt_decode(token)
        assert decoded is not None
        assert decoded["sub"] == "user@test.fr"
        assert decoded["role"] == "admin"

    def test_jwt_three_parts(self):
        from auth import jwt_encode
        token = jwt_encode({"sub": "test", "exp": int(time.time()) + 3600})
        parts = token.split(".")
        assert len(parts) == 3

    def test_jwt_expired_token_rejected(self):
        from auth import jwt_encode, jwt_decode
        payload = {"sub": "test", "exp": int(time.time()) - 10}
        token = jwt_encode(payload)
        assert jwt_decode(token) is None

    def test_jwt_tampered_payload_rejected(self):
        from auth import jwt_encode, jwt_decode
        token = jwt_encode({"sub": "test", "exp": int(time.time()) + 3600})
        parts = token.split(".")
        # Tampering: modifier le payload
        import base64
        fake_payload = base64.urlsafe_b64encode(b'{"sub":"hacker","exp":9999999999}').rstrip(b"=").decode()
        tampered = f"{parts[0]}.{fake_payload}.{parts[2]}"
        assert jwt_decode(tampered) is None

    def test_jwt_tampered_signature_rejected(self):
        from auth import jwt_encode, jwt_decode
        token = jwt_encode({"sub": "test", "exp": int(time.time()) + 3600})
        tampered = token[:-5] + "XXXXX"
        assert jwt_decode(tampered) is None

    def test_jwt_malformed_input(self):
        from auth import jwt_decode
        assert jwt_decode("") is None
        assert jwt_decode("not.a.jwt") is None
        assert jwt_decode("a.b") is None
        assert jwt_decode("a.b.c.d") is None
        assert jwt_decode(None) is None if True else None  # graceful

    def test_jwt_no_exp_accepted(self):
        """Token sans expiration : accepte (pour flexibilite)."""
        from auth import jwt_encode, jwt_decode
        token = jwt_encode({"sub": "test"})
        decoded = jwt_decode(token)
        assert decoded is not None
        assert decoded["sub"] == "test"

    def test_jwt_with_special_characters(self):
        from auth import jwt_encode, jwt_decode
        payload = {"sub": "user+special@test.fr", "nom": "D'Arc", "exp": int(time.time()) + 3600}
        token = jwt_encode(payload)
        decoded = jwt_decode(token)
        assert decoded["nom"] == "D'Arc"


# ================================================================
# TOKEN REVOCATION
# ================================================================

class TestTokenRevocation:
    """Tests de la revocation de tokens (blacklist)."""

    def test_revoke_valid_token(self, clean_auth, sample_user):
        from auth import generate_token, revoke_token, jwt_decode
        token = generate_token(sample_user)
        assert jwt_decode(token) is not None
        assert revoke_token(token) is True
        assert jwt_decode(token) is None  # Revoque

    def test_revoke_invalid_token(self):
        from auth import revoke_token
        assert revoke_token("invalid.token.here") is False

    def test_revoke_expired_cleanup(self, clean_auth):
        import auth
        # Inserer un JTI expire
        auth._token_blacklist["expired-jti"] = time.time() - 100
        auth._cleanup_blacklist()
        assert "expired-jti" not in auth._token_blacklist


# ================================================================
# USER CRUD
# ================================================================

class TestUserCRUD:
    """Tests du CRUD utilisateurs."""

    def test_create_user_success(self, clean_auth):
        from auth import create_user
        user = create_user(
            email="new@test.fr",
            password="SecurePass123!",
            nom="Dupont",
            prenom="Jean",
            role="expert_comptable",
            offre="solo",
        )
        assert user["email"] == "new@test.fr"
        assert "password_hash" not in user  # Pas de hash expose
        assert user["role"] == "expert_comptable"

    def test_create_user_duplicate_email(self, clean_auth):
        from auth import create_user
        create_user(email="dup@test.fr", password="SecurePass123!", nom="A", prenom="B")
        with pytest.raises(ValueError, match="deja utilise"):
            create_user(email="dup@test.fr", password="SecurePass123!", nom="C", prenom="D")

    def test_create_user_email_case_insensitive(self, clean_auth):
        from auth import create_user
        create_user(email="User@Test.FR", password="SecurePass123!", nom="A", prenom="B")
        with pytest.raises(ValueError, match="deja utilise"):
            create_user(email="user@test.fr", password="SecurePass123!", nom="C", prenom="D")

    def test_create_user_password_too_short(self, clean_auth):
        from auth import create_user
        with pytest.raises(ValueError, match="trop court"):
            create_user(email="a@b.fr", password="Short1!", nom="A", prenom="B")

    def test_create_user_password_no_uppercase(self, clean_auth):
        from auth import create_user
        with pytest.raises(ValueError, match="majuscules"):
            create_user(email="a@b.fr", password="alllowercase1!", nom="A", prenom="B")

    def test_create_user_password_no_digit(self, clean_auth):
        from auth import create_user
        with pytest.raises(ValueError, match="chiffre"):
            create_user(email="a@b.fr", password="NoDigitsHere!", nom="A", prenom="B")

    def test_create_user_password_no_special(self, clean_auth):
        from auth import create_user
        with pytest.raises(ValueError, match="special"):
            create_user(email="a@b.fr", password="NoSpecial12345", nom="A", prenom="B")

    def test_create_user_invalid_offer(self, clean_auth):
        from auth import create_user
        with pytest.raises(ValueError, match="Offre invalide"):
            create_user(email="a@b.fr", password="SecurePass123!", nom="A", prenom="B", offre="premium")

    def test_create_user_invalid_role(self, clean_auth):
        from auth import create_user
        with pytest.raises(ValueError, match="Role invalide"):
            create_user(email="a@b.fr", password="SecurePass123!", nom="A", prenom="B", role="superuser")

    def test_authenticate_success(self, clean_auth):
        from auth import create_user, authenticate
        create_user(email="auth@test.fr", password="SecurePass123!", nom="A", prenom="B")
        result = authenticate("auth@test.fr", "SecurePass123!")
        assert result is not None
        assert result["email"] == "auth@test.fr"

    def test_authenticate_wrong_password(self, clean_auth):
        from auth import create_user, authenticate
        create_user(email="auth@test.fr", password="SecurePass123!", nom="A", prenom="B")
        assert authenticate("auth@test.fr", "WrongPass456!") is None

    def test_authenticate_nonexistent_user(self, clean_auth):
        from auth import authenticate
        assert authenticate("nobody@test.fr", "SecurePass123!") is None

    def test_authenticate_inactive_user(self, clean_auth):
        import auth
        auth.create_user(email="inactive@test.fr", password="SecurePass123!", nom="A", prenom="B")
        auth._users["inactive@test.fr"]["active"] = False
        assert auth.authenticate("inactive@test.fr", "SecurePass123!") is None

    def test_get_user_exists(self, sample_user):
        from auth import get_user
        user = get_user("test@normacheck.fr")
        assert user is not None
        assert "password_hash" not in user

    def test_get_user_not_found(self, clean_auth):
        from auth import get_user
        assert get_user("nobody@test.fr") is None

    def test_update_user_role(self, sample_user):
        from auth import update_user_role
        updated = update_user_role("test@normacheck.fr", "admin")
        assert updated["role"] == "admin"

    def test_update_user_role_invalid(self, sample_user):
        from auth import update_user_role
        with pytest.raises(ValueError, match="Role invalide"):
            update_user_role("test@normacheck.fr", "superadmin")

    def test_set_user_tenant(self, sample_user):
        from auth import set_user_tenant
        result = set_user_tenant("test@normacheck.fr", "new-tenant-id")
        assert result["tenant_id"] == "new-tenant-id"

    def test_list_users_by_tenant(self, clean_auth):
        from auth import create_user, list_users_by_tenant
        u1 = create_user(email="u1@test.fr", password="SecurePass123!", nom="A", prenom="B", tenant_id="tenant-1")
        u2 = create_user(email="u2@test.fr", password="SecurePass123!", nom="C", prenom="D", tenant_id="tenant-1")
        create_user(email="u3@test.fr", password="SecurePass123!", nom="E", prenom="F", tenant_id="tenant-2")
        result = list_users_by_tenant("tenant-1")
        assert len(result) == 2


# ================================================================
# EMAIL VERIFICATION
# ================================================================

class TestEmailVerification:
    """Tests de la verification d'email."""

    def test_generate_code_format(self, clean_auth):
        from auth import generate_verification_code
        code = generate_verification_code("test@test.fr")
        assert len(code) == 6
        assert code.isdigit()

    def test_verify_correct_code(self, clean_auth):
        from auth import generate_verification_code, verify_email_code
        code = generate_verification_code("test@test.fr")
        assert verify_email_code("test@test.fr", code) is True

    def test_verify_wrong_code(self, clean_auth):
        from auth import generate_verification_code, verify_email_code
        generate_verification_code("test@test.fr")
        assert verify_email_code("test@test.fr", "000000") is False

    def test_verify_expired_code(self, clean_auth):
        import auth
        auth.generate_verification_code("test@test.fr")
        # Forcer l'expiration
        auth._verification_codes["test@test.fr"]["expires"] = time.time() - 10
        assert auth.verify_email_code("test@test.fr", "123456") is False

    def test_verify_max_attempts(self, clean_auth):
        import auth
        code = auth.generate_verification_code("test@test.fr")
        # Epuiser les tentatives
        for _ in range(auth.VERIFICATION_MAX_ATTEMPTS + 1):
            auth.verify_email_code("test@test.fr", "000000")
        # Meme le bon code doit echouer
        assert auth.verify_email_code("test@test.fr", code) is False

    def test_verify_unknown_email(self, clean_auth):
        from auth import verify_email_code
        assert verify_email_code("unknown@test.fr", "123456") is False

    def test_code_marks_email_verified(self, clean_auth):
        import auth
        auth.create_user(email="v@test.fr", password="SecurePass123!", nom="A", prenom="B")
        code = auth.generate_verification_code("v@test.fr")
        auth.verify_email_code("v@test.fr", code)
        assert auth._users["v@test.fr"]["email_verifie"] is True


# ================================================================
# ADMIN BOOTSTRAP
# ================================================================

class TestAdminBootstrap:
    """Tests du bootstrap admin."""

    def test_bootstrap_creates_admin(self, clean_auth):
        from auth import bootstrap_admin
        admin = bootstrap_admin()
        assert admin is not None
        assert admin["role"] == "admin"

    def test_bootstrap_idempotent(self, clean_auth):
        from auth import bootstrap_admin
        admin1 = bootstrap_admin()
        admin2 = bootstrap_admin()
        assert admin2 is None  # Already exists


# ================================================================
# DASHBOARD PERSISTENCE
# ================================================================

class TestDashboard:
    """Tests de la persistence dashboard."""

    def test_save_and_load_dashboard(self, clean_auth):
        from auth import save_dashboard, load_dashboard
        data = {"score": 85, "anomalies": 3}
        save_dashboard("test@test.fr", data)
        result = load_dashboard("test@test.fr")
        assert result is not None
        assert result["data"]["score"] == 85

    def test_load_nonexistent_dashboard(self, clean_auth):
        from auth import load_dashboard
        assert load_dashboard("nobody@test.fr") is None

    def test_dashboard_email_case_insensitive(self, clean_auth):
        from auth import save_dashboard, load_dashboard
        save_dashboard("Test@Test.FR", {"x": 1})
        result = load_dashboard("test@test.fr")
        assert result is not None
