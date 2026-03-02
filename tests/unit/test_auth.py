"""Tests du module d'authentification (JWT, hashing, utilisateurs)."""

import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from auth import (
    hash_password, verify_password,
    jwt_encode, jwt_decode,
    _b64url_encode, _b64url_decode,
    create_user, authenticate,
)


# ==============================
# Password Hashing (PBKDF2)
# ==============================

class TestPasswordHashing:
    """Tests du hashing de mots de passe."""

    def test_hash_produit_resultat(self):
        h = hash_password("monmotdepasse")
        assert h is not None
        assert "$" in h

    def test_hash_contient_salt_et_derive(self):
        h = hash_password("test123")
        parts = h.split("$")
        assert len(parts) == 2
        assert len(parts[0]) == 32  # Salt hex = 16 bytes = 32 chars
        assert len(parts[1]) == 64  # SHA256 = 32 bytes = 64 hex chars

    def test_verify_correct(self):
        password = "SuperSecret42!"
        h = hash_password(password)
        assert verify_password(password, h) is True

    def test_verify_incorrect(self):
        h = hash_password("correct_password")
        assert verify_password("wrong_password", h) is False

    def test_verify_format_invalide(self):
        assert verify_password("test", "pas_de_dollar") is False

    def test_hash_unique(self):
        """Deux hash du meme mot de passe sont differents (salt aleatoire)."""
        h1 = hash_password("same_password")
        h2 = hash_password("same_password")
        assert h1 != h2
        # Mais les deux doivent verifier
        assert verify_password("same_password", h1) is True
        assert verify_password("same_password", h2) is True

    def test_hash_vide(self):
        h = hash_password("")
        assert verify_password("", h) is True
        assert verify_password("non_vide", h) is False


# ==============================
# JWT
# ==============================

class TestJWT:
    """Tests de l'implementation JWT."""

    def test_encode_decode(self):
        payload = {"sub": "user123", "role": "admin"}
        token = jwt_encode(payload)
        decoded = jwt_decode(token)
        assert decoded is not None
        assert decoded["sub"] == "user123"
        assert decoded["role"] == "admin"

    def test_token_format(self):
        token = jwt_encode({"test": True})
        parts = token.split(".")
        assert len(parts) == 3  # header.payload.signature

    def test_token_invalide(self):
        assert jwt_decode("not.a.valid.token") is None
        assert jwt_decode("") is None
        assert jwt_decode("abc") is None

    def test_token_modifie(self):
        """Un token modifie doit etre rejete."""
        token = jwt_encode({"sub": "user1"})
        # Modifier un caractere du payload
        parts = token.split(".")
        modified = parts[0] + "." + parts[1] + "X" + "." + parts[2]
        assert jwt_decode(modified) is None

    def test_token_expire(self):
        payload = {"sub": "user1", "exp": time.time() - 3600}  # Expire il y a 1h
        token = jwt_encode(payload)
        assert jwt_decode(token) is None

    def test_token_non_expire(self):
        payload = {"sub": "user1", "exp": time.time() + 3600}  # Expire dans 1h
        token = jwt_encode(payload)
        decoded = jwt_decode(token)
        assert decoded is not None
        assert decoded["sub"] == "user1"

    def test_token_sans_expiration(self):
        payload = {"sub": "user1"}  # Pas d'exp
        token = jwt_encode(payload)
        decoded = jwt_decode(token)
        assert decoded is not None

    def test_payload_complexe(self):
        payload = {
            "sub": "user-uuid-123",
            "email": "test@example.com",
            "role": "manager",
            "tenant_id": "tenant-456",
            "iat": int(time.time()),
        }
        token = jwt_encode(payload)
        decoded = jwt_decode(token)
        assert decoded["email"] == "test@example.com"
        assert decoded["tenant_id"] == "tenant-456"


class TestB64url:
    """Tests de l'encodage base64url."""

    def test_encode_decode_roundtrip(self):
        data = b"Hello, World!"
        encoded = _b64url_encode(data)
        decoded = _b64url_decode(encoded)
        assert decoded == data

    def test_encode_bytes_speciaux(self):
        data = bytes(range(256))
        encoded = _b64url_encode(data)
        decoded = _b64url_decode(encoded)
        assert decoded == data

    def test_padding_removed(self):
        encoded = _b64url_encode(b"a")
        assert "=" not in encoded


# ==============================
# User Management
# ==============================

class TestUserManagement:
    """Tests de la gestion des utilisateurs (in-memory)."""

    def setup_method(self):
        # Reset le store in-memory
        import auth
        auth._users = {}

    def test_create_user(self):
        user = create_user("test@example.com", "password123", "Dupont", "Jean")
        assert user is not None
        assert user["email"] == "test@example.com"
        assert user["nom"] == "Dupont"
        assert user["prenom"] == "Jean"
        assert "password_hash" not in user  # Le hash ne doit pas etre expose

    def test_create_duplicate_user(self):
        import pytest
        create_user("dup@example.com", "pass123456", "User", "One")
        with pytest.raises(ValueError, match="deja utilise"):
            create_user("dup@example.com", "pass654321", "User", "Two")

    def test_create_user_password_trop_court(self):
        import pytest
        with pytest.raises(ValueError, match="trop court"):
            create_user("short@example.com", "12345", "Short", "Pass")

    def test_authenticate_success(self):
        create_user("login@example.com", "mypassword", "Login", "User")
        user = authenticate("login@example.com", "mypassword")
        assert user is not None
        assert user["email"] == "login@example.com"

    def test_authenticate_wrong_password(self):
        create_user("wrong@example.com", "correct_pass", "Wrong", "User")
        user = authenticate("wrong@example.com", "incorrect")
        assert user is None

    def test_authenticate_unknown_user(self):
        user = authenticate("nonexistent@example.com", "password")
        assert user is None

    def test_user_has_role(self):
        user = create_user("admin@example.com", "admin12345", "Admin", "User")
        assert "role" in user
        assert user["role"] == "collaborateur"

    def test_user_has_id(self):
        user = create_user("id@example.com", "password123", "ID", "User")
        assert "id" in user
        assert len(user["id"]) > 0

    def test_user_has_tenant(self):
        user = create_user("tenant@example.com", "password123", "Tenant", "User")
        assert "tenant_id" in user
