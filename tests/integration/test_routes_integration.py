"""Integration tests for RH, Simulation, and Comptabilite route modules.

Covers the main endpoints from each module with valid parameters,
invalid parameters, and authentication checks.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
from starlette.testclient import TestClient
from api.index import app


# ==============================
# Fixtures
# ==============================

@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def clean_auth():
    import auth
    auth._users.clear()
    if auth._users_store:
        auth._users_store.save({})
    auth._token_blacklist.clear()
    yield
    auth._users.clear()
    if auth._users_store:
        auth._users_store.save({})


@pytest.fixture
def auth_headers(client, clean_auth):
    import auth
    user = auth.create_user(
        email="route-test@normacheck.fr",
        password="SecurePass123!",
        nom="Test",
        prenom="Routes",
        role="expert_comptable",
        offre="equipe",
    )
    token = auth.generate_token(user)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def reset_rate_limit():
    """Reset rate limiting before each test to avoid 429 errors."""
    from api import state
    from api import index as api_index
    state.rate_store.clear()
    api_index._rate_store.clear()
    yield
    state.rate_store.clear()
    api_index._rate_store.clear()


@pytest.fixture(autouse=True)
def clean_rh_state():
    """Clear RH in-memory state before and after each test."""
    from api import state
    from api.routes import rh as rh_mod
    state.rh_contrats[:] = []
    state.rh_conges[:] = []
    state.rh_arrets[:] = []
    rh_mod._rh_bulletins[:] = []
    yield
    state.rh_contrats[:] = []
    state.rh_conges[:] = []
    state.rh_arrets[:] = []
    rh_mod._rh_bulletins[:] = []


def _create_contrat(client, headers=None, **overrides):
    """Helper to create a contract via POST and return response."""
    data = {
        "type_contrat": "CDI",
        "nom_salarie": "Dupont",
        "prenom_salarie": "Jean",
        "poste": "Developpeur",
        "date_debut": "2026-01-15",
        "salaire_brut": "3000",
    }
    data.update(overrides)
    return client.post("/api/rh/contrats", data=data, headers=headers)


# ==============================
# RH - Contrats
# ==============================

class TestRHContrats:
    """Tests for POST /api/rh/contrats and GET /api/rh/contrats."""

    def test_create_contrat_cdi(self, client, auth_headers):
        resp = _create_contrat(client, headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["type_contrat"] == "CDI"
        assert body["nom_salarie"] == "Dupont"
        assert body["prenom_salarie"] == "Jean"
        assert "id" in body

    def test_create_contrat_cdd_requires_motif(self, client, auth_headers):
        resp = _create_contrat(
            client,
            headers=auth_headers,
            type_contrat="CDD",
            date_fin="2026-06-30",
        )
        assert resp.status_code == 400
        assert "motif" in resp.json()["detail"].lower()

    def test_create_contrat_cdd_with_motif(self, client, auth_headers):
        resp = _create_contrat(
            client,
            headers=auth_headers,
            type_contrat="CDD",
            date_fin="2026-06-30",
            motif_cdd="remplacement",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["type_contrat"] == "CDD"

    def test_create_contrat_invalid_type(self, client, auth_headers):
        resp = _create_contrat(
            client,
            headers=auth_headers,
            type_contrat="INVALIDE",
        )
        assert resp.status_code == 400
        assert "invalide" in resp.json()["detail"].lower()

    def test_list_contrats(self, client, auth_headers):
        resp = client.get("/api/rh/contrats", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "total" in body
        assert "items" in body

    def test_list_contrats_after_creation(self, client, auth_headers):
        initial = client.get("/api/rh/contrats", headers=auth_headers).json()["total"]
        _create_contrat(client, headers=auth_headers)
        resp = client.get("/api/rh/contrats", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == initial + 1

    def test_create_contrat_no_auth(self, client):
        """Endpoints RH require authentication via middleware."""
        resp = _create_contrat(client)
        assert resp.status_code in (401, 403)

    def test_list_contrats_no_auth(self, client):
        """GET contrats also requires authentication."""
        resp = client.get("/api/rh/contrats")
        assert resp.status_code in (401, 403)

    def test_get_contrat_by_id(self, client, auth_headers):
        create_resp = _create_contrat(client, headers=auth_headers)
        contrat_id = create_resp.json()["id"]
        resp = client.get(f"/api/rh/contrats/{contrat_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == contrat_id

    def test_get_contrat_not_found(self, client, auth_headers):
        resp = client.get("/api/rh/contrats/nonexistent", headers=auth_headers)
        assert resp.status_code == 404


# ==============================
# RH - Bulletins
# ==============================

class TestRHBulletins:
    """Tests for POST /api/rh/bulletins/generer and GET /api/rh/bulletins."""

    def test_generate_bulletin_standalone(self, client, auth_headers):
        resp = client.post(
            "/api/rh/bulletins/generer",
            data={
                "nom_salarie": "Martin",
                "prenom_salarie": "Sophie",
                "mois": "2026-03",
                "salaire_brut": "3000",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "id" in body
        assert body["brut_total"] > 0

    def test_generate_bulletin_from_contrat(self, client, auth_headers):
        create_resp = _create_contrat(client, headers=auth_headers)
        contrat_id = create_resp.json()["id"]
        resp = client.post(
            "/api/rh/bulletins/generer",
            data={
                "contrat_id": contrat_id,
                "mois": "2026-03",
                "salaire_brut": "3000",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["brut_total"] > 0

    def test_list_bulletins(self, client, auth_headers):
        resp = client.get("/api/rh/bulletins", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "total" in body
        assert "items" in body

    def test_list_bulletins_after_generation(self, client, auth_headers):
        initial = client.get("/api/rh/bulletins", headers=auth_headers).json()["total"]
        client.post(
            "/api/rh/bulletins/generer",
            data={
                "nom_salarie": "Martin",
                "prenom_salarie": "Sophie",
                "mois": "2026-03",
                "salaire_brut": "2800",
            },
            headers=auth_headers,
        )
        resp = client.get("/api/rh/bulletins", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["total"] >= initial + 1

    def test_generate_bulletin_with_primes(self, client, auth_headers):
        resp = client.post(
            "/api/rh/bulletins/generer",
            data={
                "nom_salarie": "Leroy",
                "prenom_salarie": "Paul",
                "mois": "2026-01",
                "salaire_brut": "2500",
                "primes": "500",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["brut_total"] >= 3000

    def test_generate_bulletin_no_auth(self, client):
        """Bulletin generation requires authentication."""
        resp = client.post(
            "/api/rh/bulletins/generer",
            data={
                "nom_salarie": "Martin",
                "prenom_salarie": "Sophie",
                "mois": "2026-03",
                "salaire_brut": "3000",
            },
        )
        assert resp.status_code in (401, 403)


# ==============================
# RH - Conges
# ==============================

class TestRHConges:
    """Tests for POST /api/rh/conges and GET /api/rh/conges."""

    def test_create_conge_cp(self, client, auth_headers):
        resp = client.post(
            "/api/rh/conges",
            data={
                "nom_salarie": "Dupont",
                "type_conge": "cp",
                "date_debut": "2026-08-01",
                "date_fin": "2026-08-15",
                "nb_jours": "10",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["type_conge"] == "cp"
        assert body["nb_jours"] == 10
        assert "id" in body
        assert "info_legale" in body

    def test_create_conge_invalid_type(self, client, auth_headers):
        resp = client.post(
            "/api/rh/conges",
            data={
                "nom_salarie": "Dupont",
                "type_conge": "vacances",
                "date_debut": "2026-08-01",
                "date_fin": "2026-08-15",
                "nb_jours": "5",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert "invalide" in resp.json()["detail"].lower()

    def test_list_conges(self, client, auth_headers):
        resp = client.get("/api/rh/conges", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "total" in body
        assert "items" in body

    def test_list_conges_after_creation(self, client, auth_headers):
        initial = client.get("/api/rh/conges", headers=auth_headers).json()["total"]
        client.post(
            "/api/rh/conges",
            data={
                "nom_salarie": "Dupont",
                "type_conge": "rtt",
                "date_debut": "2026-05-01",
                "date_fin": "2026-05-02",
                "nb_jours": "1",
            },
            headers=auth_headers,
        )
        resp = client.get("/api/rh/conges", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["total"] >= initial + 1

    def test_create_conge_invalid_statut(self, client, auth_headers):
        resp = client.post(
            "/api/rh/conges",
            data={
                "nom_salarie": "Dupont",
                "type_conge": "cp",
                "date_debut": "2026-08-01",
                "date_fin": "2026-08-15",
                "nb_jours": "10",
                "statut": "invalid_status",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_create_conge_no_auth(self, client):
        """Leave creation requires authentication."""
        resp = client.post(
            "/api/rh/conges",
            data={
                "nom_salarie": "Dupont",
                "type_conge": "cp",
                "date_debut": "2026-08-01",
                "date_fin": "2026-08-15",
                "nb_jours": "10",
            },
        )
        assert resp.status_code in (401, 403)


# ==============================
# Simulation - Bulletin
# ==============================

class TestSimulationBulletin:
    """Tests for GET /api/simulation/bulletin."""

    def test_sim_bulletin_defaults(self, client, auth_headers):
        resp = client.get("/api/simulation/bulletin", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "net_a_payer" in body
        assert "cout_total_employeur" in body
        assert body["brut_mensuel"] == 2500  # default

    def test_sim_bulletin_custom(self, client, auth_headers):
        resp = client.get(
            "/api/simulation/bulletin",
            params={"brut_mensuel": 3000, "effectif": 25},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["brut_mensuel"] == 3000
        assert body["net_a_payer"] > 0
        assert body["net_a_payer"] < 3000

    def test_sim_bulletin_cadre(self, client, auth_headers):
        resp = client.get(
            "/api/simulation/bulletin",
            params={"brut_mensuel": 4000, "est_cadre": True},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["brut_mensuel"] == 4000

    def test_sim_bulletin_with_absence(self, client, auth_headers):
        resp = client.get(
            "/api/simulation/bulletin",
            params={
                "brut_mensuel": 3000,
                "jours_absence": 5,
                "type_absence": "maladie",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["retenue_absences"] > 0
        assert body["brut_effectif"] < body["brut_mensuel"]

    def test_sim_bulletin_no_auth(self, client):
        """Simulation endpoints require authentication."""
        resp = client.get("/api/simulation/bulletin")
        assert resp.status_code in (401, 403)


# ==============================
# Simulation - Micro-entrepreneur
# ==============================

class TestSimulationMicro:
    """Tests for GET /api/simulation/micro-entrepreneur."""

    def test_sim_micro_defaults(self, client, auth_headers):
        resp = client.get("/api/simulation/micro-entrepreneur", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["chiffre_affaires"] == 50000
        assert "cotisations_sociales" in body
        assert "revenu_net" in body

    def test_sim_micro_services(self, client, auth_headers):
        resp = client.get(
            "/api/simulation/micro-entrepreneur",
            params={"chiffre_affaires": 5000, "activite": "prestations_bnc"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["chiffre_affaires"] == 5000
        assert body["cotisations_sociales"] > 0
        assert body["revenu_net"] < 5000

    def test_sim_micro_with_acre(self, client, auth_headers):
        resp = client.get(
            "/api/simulation/micro-entrepreneur",
            params={"chiffre_affaires": 30000, "acre": True},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["acre_applique"] is True
        # With ACRE, cotisations should be lower
        resp_no_acre = client.get(
            "/api/simulation/micro-entrepreneur",
            params={"chiffre_affaires": 30000, "acre": False},
            headers=auth_headers,
        )
        body_no_acre = resp_no_acre.json()
        assert body["cotisations_sociales"] < body_no_acre["cotisations_sociales"]

    def test_sim_micro_vente_marchandises(self, client, auth_headers):
        resp = client.get(
            "/api/simulation/micro-entrepreneur",
            params={"chiffre_affaires": 80000, "activite": "vente_marchandises"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["chiffre_affaires"] == 80000


# ==============================
# Simulation - TNS
# ==============================

class TestSimulationTNS:
    """Tests for GET /api/simulation/tns."""

    def test_sim_tns_defaults(self, client, auth_headers):
        resp = client.get("/api/simulation/tns", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["revenu_net"] == 40000
        assert "total_cotisations" in body
        assert body["total_cotisations"] > 0

    def test_sim_tns_custom_revenu(self, client, auth_headers):
        resp = client.get(
            "/api/simulation/tns",
            params={"revenu_net": 50000},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["revenu_net"] == 50000
        assert body["maladie_maternite"] > 0
        assert body["vieillesse_base"] > 0

    def test_sim_tns_with_acre(self, client, auth_headers):
        resp = client.get(
            "/api/simulation/tns",
            params={"revenu_net": 50000, "acre": True},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["acre_applique"] is True

    def test_sim_tns_gerant_majoritaire(self, client, auth_headers):
        resp = client.get(
            "/api/simulation/tns",
            params={"revenu_net": 60000, "type_statut": "gerant_majoritaire"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["type_statut"] == "gerant_majoritaire"


# ==============================
# Simulation - Cout employeur
# ==============================

class TestSimulationCoutEmployeur:
    """Tests for GET /api/simulation/cout-employeur."""

    def test_sim_cout_employeur_defaults(self, client, auth_headers):
        resp = client.get("/api/simulation/cout-employeur", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "cout_total_mensuel" in body
        assert "cout_total_annuel" in body
        assert body["cout_total_annuel"] == round(body["cout_total_mensuel"] * 12, 2)

    def test_sim_cout_employeur_custom(self, client, auth_headers):
        resp = client.get(
            "/api/simulation/cout-employeur",
            params={"brut_mensuel": 3000, "effectif": 10},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["brut_mensuel"] == 3000
        assert body["charges_patronales_urssaf"] > 0
        assert body["net_a_payer"] > 0
        assert body["net_a_payer"] < 3000

    def test_sim_cout_employeur_with_primes(self, client, auth_headers):
        resp = client.get(
            "/api/simulation/cout-employeur",
            params={"brut_mensuel": 3000, "effectif": 10, "primes": 500},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["primes"] == 500
        assert body["brut_total"] == 3500


# ==============================
# Simulation - Exonerations
# ==============================

class TestSimulationExonerations:
    """Tests for GET /api/simulation/exonerations."""

    def test_sim_exonerations_defaults(self, client, auth_headers):
        resp = client.get("/api/simulation/exonerations", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "exonerations" in body
        assert "taux_patronal_detaille" in body

    def test_sim_exonerations_custom(self, client, auth_headers):
        resp = client.get(
            "/api/simulation/exonerations",
            params={"brut_mensuel": 2500, "effectif": 10},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["brut_mensuel"] == 2500

    def test_sim_exonerations_high_salary(self, client, auth_headers):
        """High salary should not be eligible for most exonerations."""
        resp = client.get(
            "/api/simulation/exonerations",
            params={"brut_mensuel": 8000, "effectif": 10},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["exonerations"], list)

    def test_sim_exonerations_large_company(self, client, auth_headers):
        resp = client.get(
            "/api/simulation/exonerations",
            params={"brut_mensuel": 2000, "effectif": 100},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["exonerations"], list)


# ==============================
# Comptabilite - Journal
# ==============================

class TestComptabiliteJournal:
    """Tests for GET /api/comptabilite/journal."""

    def test_journal_returns_list(self, client, auth_headers):
        resp = client.get("/api/comptabilite/journal", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)

    def test_journal_no_auth(self, client):
        """Comptabilite endpoints require authentication."""
        resp = client.get("/api/comptabilite/journal")
        assert resp.status_code in (401, 403)


# ==============================
# Comptabilite - Balance
# ==============================

class TestComptabiliteBalance:
    """Tests for GET /api/comptabilite/balance."""

    def test_balance_returns_list(self, client, auth_headers):
        resp = client.get("/api/comptabilite/balance", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)

    def test_balance_items_structure(self, client, auth_headers):
        resp = client.get("/api/comptabilite/balance", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        # If there are items, check structure
        if body:
            item = body[0]
            for key in ("total_debit", "total_credit", "solde_debiteur", "solde_crediteur"):
                assert key in item


# ==============================
# Comptabilite - Grand livre detail
# ==============================

class TestComptabiliteGrandLivre:
    """Tests for GET /api/comptabilite/grand-livre-detail."""

    def test_grand_livre_returns_list(self, client, auth_headers):
        resp = client.get("/api/comptabilite/grand-livre-detail", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)

    def test_grand_livre_with_date_filter(self, client, auth_headers):
        resp = client.get(
            "/api/comptabilite/grand-livre-detail",
            params={"date_debut": "2026-01-01", "date_fin": "2026-12-31"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ==============================
# Comptabilite - Bilan
# ==============================

class TestComptabiliteBilan:
    """Tests for GET /api/comptabilite/bilan."""

    def test_bilan_structure(self, client, auth_headers):
        resp = client.get("/api/comptabilite/bilan", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "actif" in body
        assert "passif" in body
        assert "total" in body["actif"]
        assert "total" in body["passif"]

    def test_bilan_numeric_values(self, client, auth_headers):
        resp = client.get("/api/comptabilite/bilan", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["actif"]["total"], (int, float))
        assert isinstance(body["passif"]["total"], (int, float))


# ==============================
# Comptabilite - Compte de resultat
# ==============================

class TestComptabiliteCompteResultat:
    """Tests for GET /api/comptabilite/compte-resultat."""

    def test_compte_resultat_returns_data(self, client, auth_headers):
        resp = client.get("/api/comptabilite/compte-resultat", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)

    def test_compte_resultat_no_auth(self, client):
        """Comptabilite endpoints require authentication."""
        resp = client.get("/api/comptabilite/compte-resultat")
        assert resp.status_code in (401, 403)
