"""Tests d'integration de securite - Niveau bancaire.

Verifie le pipeline complet de securite : auth -> chiffrement -> audit.
Ref: ISO 27001, RGPD art. 32.
"""

import pytest
import time

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ================================================================
# AUTH -> TOKEN -> ACCESS CONTROL
# ================================================================

class TestAuthPipeline:
    """Pipeline complet d'authentification."""

    def test_register_login_access_logout(self, clean_auth):
        """Cycle complet : inscription -> connexion -> acces -> deconnexion."""
        import auth

        # 1. Inscription
        user = auth.create_user(
            email="cycle@test.fr",
            password="SecurePass123!",
            nom="Cycle",
            prenom="Test",
            role="expert_comptable",
            offre="equipe",
        )
        assert user is not None

        # 2. Connexion
        authenticated = auth.authenticate("cycle@test.fr", "SecurePass123!")
        assert authenticated is not None

        # 3. Generation token
        token = auth.generate_token(authenticated)
        assert token is not None

        # 4. Verification token
        payload = auth.jwt_decode(token)
        assert payload is not None
        assert payload["sub"] == "cycle@test.fr"

        # 5. Revocation (logout)
        assert auth.revoke_token(token) is True
        assert auth.jwt_decode(token) is None

    def test_email_verification_flow(self, clean_auth):
        """Cycle complet de verification email."""
        import auth

        user = auth.create_user(
            email="verify@test.fr",
            password="SecurePass123!",
            nom="V",
            prenom="E",
        )
        assert user.get("email_verifie") is False

        code = auth.generate_verification_code("verify@test.fr")
        assert len(code) == 6

        result = auth.verify_email_code("verify@test.fr", code)
        assert result is True

        # Verifier que l'email est marque comme verifie
        assert auth._users["verify@test.fr"]["email_verifie"] is True


# ================================================================
# MULTI-TENANT ISOLATION
# ================================================================

class TestMultiTenantIsolation:
    """Tests d'isolation multi-entreprises."""

    def test_tenant_isolation(self, clean_auth):
        import auth

        u1 = auth.create_user(
            email="u1@tenant1.fr",
            password="SecurePass123!",
            nom="User1",
            prenom="T1",
            tenant_id="tenant-A",
        )
        u2 = auth.create_user(
            email="u2@tenant2.fr",
            password="SecurePass123!",
            nom="User2",
            prenom="T2",
            tenant_id="tenant-B",
        )

        users_a = auth.list_users_by_tenant("tenant-A")
        users_b = auth.list_users_by_tenant("tenant-B")

        assert len(users_a) == 1
        assert users_a[0]["email"] == "u1@tenant1.fr"
        assert len(users_b) == 1
        assert users_b[0]["email"] == "u2@tenant2.fr"

    def test_tenant_reassignment(self, clean_auth):
        import auth

        user = auth.create_user(
            email="move@test.fr",
            password="SecurePass123!",
            nom="Move",
            prenom="User",
            tenant_id="old-tenant",
        )
        auth.set_user_tenant("move@test.fr", "new-tenant")

        assert len(auth.list_users_by_tenant("old-tenant")) == 0
        assert len(auth.list_users_by_tenant("new-tenant")) == 1


# ================================================================
# ROLE-BASED ACCESS CONTROL
# ================================================================

class TestRBAC:
    """Tests du controle d'acces base sur les roles."""

    def test_role_hierarchy(self, clean_auth):
        import auth

        auth.create_user(
            email="collab@test.fr",
            password="SecurePass123!",
            nom="A",
            prenom="B",
            role="collaborateur",
        )
        auth.create_user(
            email="expert@test.fr",
            password="SecurePass123!",
            nom="C",
            prenom="D",
            role="expert_comptable",
        )
        auth.create_user(
            email="admin@test.fr",
            password="SecurePass123!",
            nom="E",
            prenom="F",
            role="admin",
        )

        # Verification des roles
        collab = auth.get_user("collab@test.fr")
        expert = auth.get_user("expert@test.fr")
        admin = auth.get_user("admin@test.fr")

        assert collab["role"] == "collaborateur"
        assert expert["role"] == "expert_comptable"
        assert admin["role"] == "admin"

    def test_role_promotion(self, clean_auth):
        import auth

        auth.create_user(
            email="promo@test.fr",
            password="SecurePass123!",
            nom="P",
            prenom="R",
            role="collaborateur",
        )
        updated = auth.update_user_role("promo@test.fr", "expert_comptable")
        assert updated["role"] == "expert_comptable"


# ================================================================
# PASSWORD SECURITY
# ================================================================

class TestPasswordSecurity:
    """Tests de securite des mots de passe."""

    def test_password_not_stored_in_clear(self, clean_auth):
        import auth

        auth.create_user(
            email="sec@test.fr",
            password="SecurePass123!",
            nom="S",
            prenom="E",
        )
        # Verifier que le mot de passe n'est pas en clair dans le store
        user_data = auth._users["sec@test.fr"]
        assert "SecurePass123!" not in str(user_data.values())
        assert "password_hash" in user_data
        assert "$" in user_data["password_hash"]

    def test_password_hash_not_exposed_via_api(self, clean_auth):
        import auth

        auth.create_user(
            email="api@test.fr",
            password="SecurePass123!",
            nom="A",
            prenom="P",
        )
        user = auth.get_user("api@test.fr")
        assert "password_hash" not in user

    def test_different_users_different_hashes(self, clean_auth):
        import auth

        auth.create_user(email="a@test.fr", password="SecurePass123!", nom="A", prenom="B")
        auth.create_user(email="b@test.fr", password="SecurePass123!", nom="C", prenom="D")
        # Meme mot de passe, mais hashes differents (sel aleatoire)
        assert auth._users["a@test.fr"]["password_hash"] != auth._users["b@test.fr"]["password_hash"]
