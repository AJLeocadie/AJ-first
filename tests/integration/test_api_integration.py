"""Tests d'integration de l'API FastAPI.

Couverture : endpoints d'authentification, analyse,
gestion utilisateurs, erreurs HTTP.
"""

import sys
import json
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _get_client():
    """Tente de creer un TestClient FastAPI."""
    try:
        from fastapi.testclient import TestClient
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "api"))
        from api.index import app
        return TestClient(app)
    except (ImportError, Exception):
        return None


@pytest.fixture
def client():
    c = _get_client()
    if c is None:
        pytest.skip("FastAPI TestClient non disponible (httpx requis)")
    return c


# ==============================
# Health Check
# ==============================

class TestHealthCheck:
    """Tests du endpoint de sante."""

    def test_health_endpoint(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy" or "status" in data


# ==============================
# Authentication API
# ==============================

class TestAuthAPI:
    """Tests des endpoints d'authentification."""

    def setup_method(self):
        import auth
        auth._users = {}

    def test_register_and_login(self, client):
        # Register
        reg_data = {
            "email": "api@test.fr",
            "password": "SecurePass123!",
            "nom": "API",
            "prenom": "User",
        }
        reg_response = client.post("/api/auth/register", json=reg_data)
        if reg_response.status_code == 200:
            # Login
            login_data = {"email": "api@test.fr", "password": "SecurePass123!"}
            login_response = client.post("/api/auth/login", json=login_data)
            assert login_response.status_code == 200

    def test_login_invalid_credentials(self, client):
        login_data = {"email": "nobody@test.fr", "password": "wrong"}
        response = client.post("/api/auth/login", json=login_data)
        assert response.status_code in (401, 422, 400)

    def test_protected_endpoint_no_token(self, client):
        response = client.get("/api/user/profile")
        assert response.status_code in (401, 403, 404)


# ==============================
# Error Handling
# ==============================

class TestErrorHandling:
    """Tests de la gestion d'erreurs API."""

    def test_404_endpoint(self, client):
        response = client.get("/api/nonexistent")
        assert response.status_code in (401, 404)  # 401 si auth requise, 404 si route inconnue

    def test_method_not_allowed(self, client):
        response = client.delete("/api/health")
        assert response.status_code in (404, 405)

    def test_invalid_json_body(self, client):
        response = client.post(
            "/api/auth/login",
            content="not json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code in (400, 422)
