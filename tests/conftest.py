"""Configuration globale des tests NormaCheck.

Fixtures partagees, configuration pytest, et utilitaires de test.
Niveau de fiabilite : bancaire (ISO 27001, ISO 42001, RGPD).
"""

import os
import sys
import json
import sqlite3
import tempfile
from pathlib import Path
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

# Ajouter la racine du projet au path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).parent / "fixtures"


# =============================================
# FIXTURES : Paths et configuration
# =============================================

@pytest.fixture
def fixtures_dir():
    """Repertoire des fixtures de test."""
    return FIXTURES


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Cree une arborescence temporaire complete pour les tests."""
    dirs = {
        "base": tmp_path,
        "data": tmp_path / "data",
        "reports": tmp_path / "reports",
        "temp": tmp_path / "temp",
        "uploads": tmp_path / "uploads",
        "encrypted": tmp_path / "encrypted",
        "logs": tmp_path / "logs",
        "backups": tmp_path / "backups",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


@pytest.fixture
def app_config(tmp_data_dir):
    """Configuration AppConfig pour les tests."""
    from urssaf_analyzer.config.settings import AppConfig
    return AppConfig(
        base_dir=tmp_data_dir["base"],
        data_dir=tmp_data_dir["data"],
        reports_dir=tmp_data_dir["reports"],
        temp_dir=tmp_data_dir["temp"],
        audit_log_path=tmp_data_dir["logs"] / "audit.log",
    )


# =============================================
# FIXTURES : Auth
# =============================================

@pytest.fixture(autouse=False)
def clean_auth():
    """Reset le store d'authentification entre les tests."""
    import auth
    original_users = auth._users.copy()
    original_blacklist = auth._token_blacklist.copy()
    original_codes = auth._verification_codes.copy()
    auth._users = {}
    auth._token_blacklist = {}
    auth._verification_codes = {}
    yield
    auth._users = original_users
    auth._token_blacklist = original_blacklist
    auth._verification_codes = original_codes


@pytest.fixture
def sample_user(clean_auth):
    """Cree un utilisateur de test standard."""
    from auth import create_user
    return create_user(
        email="test@normacheck.fr",
        password="SecurePass123!",
        nom="Dupont",
        prenom="Jean",
        role="expert_comptable",
        offre="equipe",
    )


@pytest.fixture
def admin_user(clean_auth):
    """Cree un utilisateur admin de test."""
    from auth import create_user
    return create_user(
        email="admin@normacheck.fr",
        password="AdminPass2026!",
        nom="Admin",
        prenom="NormaCheck",
        role="admin",
    )


@pytest.fixture
def auth_token(sample_user):
    """Genere un token JWT valide pour les tests."""
    from auth import generate_token
    return generate_token(sample_user)


# =============================================
# FIXTURES : Database
# =============================================

@pytest.fixture
def test_db(tmp_path):
    """Cree une base de donnees SQLite de test."""
    from urssaf_analyzer.database.db_manager import Database
    db_path = tmp_path / "test.db"
    return Database(db_path)


# =============================================
# FIXTURES : Documents et declarations
# =============================================

@pytest.fixture
def sample_document():
    """Document de test."""
    from urssaf_analyzer.models.documents import Document, FileType
    return Document(
        nom_fichier="test_paie.csv",
        chemin=FIXTURES / "sample_paie.csv",
        type_fichier=FileType.CSV,
        hash_sha256="a" * 64,
        taille_octets=1024,
    )


@pytest.fixture
def sample_declaration():
    """Declaration de test avec cotisations."""
    from urssaf_analyzer.models.documents import (
        Declaration, Employeur, Employe, Cotisation, DateRange,
    )
    from urssaf_analyzer.config.constants import ContributionType
    from datetime import date

    employeur = Employeur(
        siret="12345678901234",
        siren="123456789",
        raison_sociale="ACME SARL",
        effectif=25,
        taux_at=Decimal("0.0208"),
    )

    employe = Employe(
        nir="1850175123456",
        nom="Martin",
        prenom="Pierre",
        statut="non-cadre",
        temps_travail=Decimal("1.0"),
    )

    cotisations = [
        Cotisation(
            type_cotisation=ContributionType.MALADIE,
            base_brute=Decimal("3000"),
            assiette=Decimal("3000"),
            taux_patronal=Decimal("0.07"),
            taux_salarial=Decimal("0"),
            montant_patronal=Decimal("210"),
            montant_salarial=Decimal("0"),
        ),
        Cotisation(
            type_cotisation=ContributionType.VIEILLESSE_PLAFONNEE,
            base_brute=Decimal("3000"),
            assiette=Decimal("3000"),
            taux_patronal=Decimal("0.0855"),
            taux_salarial=Decimal("0.069"),
            montant_patronal=Decimal("256.50"),
            montant_salarial=Decimal("207"),
        ),
    ]

    return Declaration(
        type_declaration="DSN",
        reference="DSN-2026-01",
        employeur=employeur,
        employes=[employe],
        cotisations=cotisations,
        masse_salariale_brute=Decimal("3000"),
        effectif_declare=1,
        periode=DateRange(debut=date(2026, 1, 1), fin=date(2026, 1, 31)),
    )


@pytest.fixture
def sample_csv_file(tmp_path):
    """Cree un fichier CSV de paie de test."""
    csv_content = """Code;Libelle;Base;Taux Patronal;Taux Salarial;Montant Patronal;Montant Salarial
100;Salaire de base;3500.00;0;0;0;0
201;Maladie;3500.00;0.070;0.000;245.00;0.00
202;Vieillesse plafonnee;3500.00;0.0855;0.069;299.25;241.50
203;Vieillesse deplafonnee;3500.00;0.019;0.004;66.50;14.00
310;Allocations familiales;3500.00;0.0345;0.000;120.75;0.00
400;CSG imposable;3500.00;0.024;0.024;0;84.00
401;CSG deductible;3500.00;0.068;0.068;0;238.00
402;CRDS;3500.00;0.005;0.005;0;17.50
"""
    csv_file = tmp_path / "test_paie.csv"
    csv_file.write_text(csv_content, encoding="utf-8")
    return csv_file


@pytest.fixture
def sample_anomaly_csv(tmp_path):
    """Cree un fichier CSV avec des anomalies deliberees."""
    csv_content = """Code;Libelle;Base;Taux Patronal;Taux Salarial;Montant Patronal;Montant Salarial
201;Maladie;-500.00;0.070;0.000;-35.00;0.00
202;Vieillesse plafonnee;50000.00;0.15;0.069;7500.00;3450.00
203;Vieillesse deplafonnee;3500.00;0.019;0.004;100.00;14.00
201;Maladie;3500.00;0.070;0.000;245.00;0.00
201;Maladie;3500.00;0.070;0.000;245.00;0.00
"""
    csv_file = tmp_path / "anomalies.csv"
    csv_file.write_text(csv_content, encoding="utf-8")
    return csv_file


# =============================================
# FIXTURES : FastAPI test client
# =============================================

@pytest.fixture
def api_client():
    """Client de test FastAPI."""
    try:
        from fastapi.testclient import TestClient
        sys.path.insert(0, str(ROOT / "api"))
        from api.index import app
        return TestClient(app)
    except ImportError:
        pytest.skip("fastapi[testclient] ou httpx non installe")
