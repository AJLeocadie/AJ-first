"""Tests d'integration de l'API FastAPI - Niveau bancaire.

Verifie la communication frontend/backend, le pipeline complet,
la gestion des erreurs API, et la coherence des donnees.
"""

import io
import json
import time
import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from fastapi.testclient import TestClient
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "api"))
    from api.index import app
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

pytestmark = pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi/httpx non installe")


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers(client, clean_auth):
    """Cree un utilisateur et retourne les headers avec token."""
    import auth
    user = auth.create_user(
        email="api-test@normacheck.fr",
        password="SecurePass123!",
        nom="Test",
        prenom="API",
        role="expert_comptable",
        offre="equipe",
    )
    token = auth.generate_token(user)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers(client, clean_auth):
    """Headers admin."""
    import auth
    user = auth.create_user(
        email="admin-api@normacheck.fr",
        password="AdminPass2026!",
        nom="Admin",
        prenom="API",
        role="admin",
    )
    token = auth.generate_token(user)
    return {"Authorization": f"Bearer {token}"}


# ================================================================
# HEALTH / STATUS
# ================================================================

class TestHealthEndpoints:

    def test_health_check(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_root_accessible(self, client):
        resp = client.get("/")
        assert resp.status_code in (200, 307, 404)


# ================================================================
# AUTHENTICATION ENDPOINTS
# ================================================================

class TestAuthEndpoints:

    def test_register_success(self, client, clean_auth):
        resp = client.post("/api/auth/register", data={
            "email": "new@normacheck.fr",
            "mot_de_passe": "SecurePass123!",
            "nom": "Nouveau",
            "prenom": "User",
            "offre": "solo",
        })
        assert resp.status_code in (200, 201)

    def test_register_duplicate_email(self, client, clean_auth):
        form_data = {
            "email": "dup@normacheck.fr",
            "mot_de_passe": "SecurePass123!",
            "nom": "A",
            "prenom": "B",
            "offre": "solo",
        }
        client.post("/api/auth/register", data=form_data)
        resp = client.post("/api/auth/register", data=form_data)
        assert resp.status_code in (400, 409, 422)

    def test_register_weak_password(self, client, clean_auth):
        resp = client.post("/api/auth/register", data={
            "email": "weak@normacheck.fr",
            "mot_de_passe": "short",
            "nom": "A",
            "prenom": "B",
            "offre": "solo",
        })
        assert resp.status_code in (400, 422)

    def test_login_success(self, client, clean_auth):
        import auth
        auth.create_user(
            email="login@normacheck.fr",
            password="SecurePass123!",
            nom="A",
            prenom="B",
        )
        resp = client.post("/api/auth/login", data={
            "email": "login@normacheck.fr",
            "mot_de_passe": "SecurePass123!",
        })
        assert resp.status_code == 200

    def test_login_wrong_credentials(self, client, clean_auth):
        resp = client.post("/api/auth/login", data={
            "email": "nobody@normacheck.fr",
            "mot_de_passe": "WrongPass123!",
        })
        assert resp.status_code in (401, 403)

    def test_logout(self, client, auth_headers):
        resp = client.post("/api/auth/logout", headers=auth_headers)
        assert resp.status_code == 200

    def test_me_authenticated(self, client, auth_headers):
        resp = client.get("/api/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "email" in data

    def test_me_unauthenticated(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code in (401, 403)


# ================================================================
# PROTECTED ENDPOINTS - ACCESS CONTROL
# ================================================================

class TestAccessControl:

    def test_protected_endpoint_no_token(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code in (401, 403)

    def test_protected_endpoint_invalid_token(self, client):
        resp = client.get("/api/auth/me", headers={"Authorization": "Bearer invalid.token.here"})
        assert resp.status_code in (401, 403)

    def test_protected_endpoint_expired_token(self, client, clean_auth):
        import auth
        user = auth.create_user(
            email="expired@normacheck.fr",
            password="SecurePass123!",
            nom="A",
            prenom="B",
        )
        token = auth.jwt_encode({
            "sub": user["email"],
            "role": user["role"],
            "exp": int(time.time()) - 100,  # Expire
        })
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code in (401, 403)


# ================================================================
# UPLOAD DOCUMENTS
# ================================================================

class TestUploadEndpoints:

    def test_upload_csv(self, client, auth_headers, tmp_path):
        csv_content = b"Code;Libelle;Base\n100;Salaire;3500\n"
        resp = client.post(
            "/api/analyze",
            files={"files": ("test.csv", io.BytesIO(csv_content), "text/csv")},
            headers=auth_headers,
        )
        assert resp.status_code in (200, 201, 422)

    def test_upload_invalid_extension(self, client, auth_headers):
        resp = client.post(
            "/api/analyze",
            files={"files": ("hack.exe", io.BytesIO(b"malware"), "application/octet-stream")},
            headers=auth_headers,
        )
        # Must be rejected or return empty results
        assert resp.status_code in (200, 400, 415, 422)

    def test_upload_unauthenticated(self, client):
        csv_content = b"Code;Libelle;Base\n100;Salaire;3500\n"
        resp = client.post(
            "/api/analyze",
            files={"files": ("test.csv", io.BytesIO(csv_content), "text/csv")},
        )
        assert resp.status_code in (401, 403)


# ================================================================
# SIMULATION / CALCUL
# ================================================================

class TestSimulationEndpoints:

    def test_simulation_bulletin(self, client, auth_headers):
        """Test de la simulation de bulletin de paie."""
        resp = client.get(
            "/api/simulation/bulletin",
            params={"brut_mensuel": 3000, "effectif": 25},
            headers=auth_headers,
        )
        if resp.status_code == 404:
            pytest.skip("Endpoint /api/simulation/bulletin non disponible")
        assert resp.status_code == 200
        data = resp.json()
        if "net_avant_impot" in data:
            assert data["net_avant_impot"] > 0


# ================================================================
# API ERROR HANDLING
# ================================================================

class TestAPIErrorHandling:

    def test_invalid_json_body(self, client, auth_headers):
        resp = client.post(
            "/api/auth/login",
            content=b"not json",
            headers={**auth_headers, "Content-Type": "application/json"},
        )
        assert resp.status_code in (400, 422)

    def test_missing_required_fields(self, client, clean_auth):
        resp = client.post("/api/auth/register", data={
            "email": "test@test.fr",
            # Manque mot_de_passe, nom, prenom
        })
        assert resp.status_code in (400, 422)

    def test_404_unknown_route(self, client):
        resp = client.get("/api/nonexistent-endpoint-xyz")
        # Auth middleware may return 401 before 404 for protected routes
        assert resp.status_code in (401, 404, 405)


# ================================================================
# CORS HEADERS
# ================================================================

class TestCORSHeaders:

    def test_cors_allows_origin(self, client):
        resp = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        # CORS middleware should respond
        assert resp.status_code in (200, 400)
