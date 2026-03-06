"""Tests d'integration du workflow d'authentification complet.

Couverture : inscription -> verification email -> login -> acces protege ->
changement role -> revocation -> logout.
"""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from auth import (
    create_user, authenticate, generate_token, jwt_decode,
    revoke_token, generate_verification_code, verify_email_code,
    get_user, update_user_role, list_users_by_tenant,
)


class TestAuthWorkflowComplet:
    """Test du workflow complet d'authentification."""

    def setup_method(self):
        import auth
        auth._users = {}
        auth._token_blacklist = {}
        auth._verification_codes = {}

    def test_inscription_login_acces(self):
        """Workflow : inscription -> login -> token -> acces."""
        # 1. Inscription
        user = create_user("workflow@test.fr", "SecurePass123!", "Work", "Flow")
        assert user is not None
        assert user["email"] == "workflow@test.fr"

        # 2. Login
        authenticated = authenticate("workflow@test.fr", "SecurePass123!")
        assert authenticated is not None

        # 3. Token
        token = generate_token(authenticated)
        payload = jwt_decode(token)
        assert payload is not None
        assert payload["sub"] == "workflow@test.fr"

    def test_inscription_verification_login(self):
        """Workflow : inscription -> code verification -> validation email -> login."""
        # 1. Inscription
        user = create_user("verify@test.fr", "SecurePass123!", "Verify", "Flow")
        assert user["email_verifie"] is False

        # 2. Code de verification
        code = generate_verification_code("verify@test.fr")
        assert len(code) == 6

        # 3. Validation
        result = verify_email_code("verify@test.fr", code)
        assert result is True

        # 4. Verifier que l'email est marque comme verifie
        import auth
        assert auth._users["verify@test.fr"]["email_verifie"] is True

    def test_multi_tenant_workflow(self):
        """Workflow : creation multi-utilisateurs dans un tenant."""
        # Admin cree un tenant
        admin = create_user(
            "admin@acme.fr", "AdminPass2026!", "Admin", "ACME",
            role="admin", tenant_id="acme-tenant",
        )

        # Ajouter des collaborateurs au tenant
        collab1 = create_user(
            "collab1@acme.fr", "CollabPass123!", "Collab", "Un",
            tenant_id="acme-tenant",
        )
        collab2 = create_user(
            "collab2@acme.fr", "CollabPass123!", "Collab", "Deux",
            tenant_id="acme-tenant",
        )
        external = create_user(
            "external@other.fr", "ExternalPass123!", "External", "User",
            tenant_id="other-tenant",
        )

        # Lister les utilisateurs du tenant
        tenant_users = list_users_by_tenant("acme-tenant")
        assert len(tenant_users) == 3  # admin + 2 collabs
        assert all(u["tenant_id"] == "acme-tenant" for u in tenant_users)

        # L'utilisateur externe ne doit pas apparaitre
        emails = {u["email"] for u in tenant_users}
        assert "external@other.fr" not in emails

    def test_token_revocation_workflow(self):
        """Workflow : login -> utilisation token -> revocation -> acces refuse."""
        user = create_user("revoke@test.fr", "SecurePass123!", "Revoke", "User")
        token = generate_token(user)

        # Token valide
        assert jwt_decode(token) is not None

        # Revocation
        assert revoke_token(token) is True

        # Token invalide apres revocation
        assert jwt_decode(token) is None

    def test_role_change_workflow(self):
        """Workflow : inscription collaborateur -> promotion expert."""
        user = create_user("promo@test.fr", "SecurePass123!", "Promo", "User")
        assert user["role"] == "collaborateur"

        updated = update_user_role("promo@test.fr", "expert_comptable")
        assert updated["role"] == "expert_comptable"

        # Re-authentifier et verifier
        auth_user = authenticate("promo@test.fr", "SecurePass123!")
        retrieved = get_user("promo@test.fr")
        assert retrieved["role"] == "expert_comptable"
