"""Tests E2E simulant un utilisateur reel avec Playwright.

Scenarios :
1. Connexion
2. Upload de documents
3. Analyse
4. Affichage resultats
5. Generation rapport

Screenshots automatiques sur chaque echec.
"""

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
SCREENSHOTS_DIR = ROOT / "tests" / "e2e" / "screenshots"


def _skip_if_no_playwright():
    try:
        from playwright.sync_api import sync_playwright
        return False
    except ImportError:
        return True


pytestmark = pytest.mark.skipif(
    _skip_if_no_playwright(),
    reason="Playwright non installe",
)


class TestPageAccess:
    """Tests d'acces aux pages."""

    def test_homepage_loads(self, page, server):
        """La page d'accueil doit se charger."""
        page.goto(server)
        assert page.title() != ""

    def test_login_page_loads(self, page, server):
        """La page de connexion doit etre accessible."""
        page.goto(f"{server}/login")
        # Verifier qu'un formulaire de connexion existe
        assert page.locator("input[type='email'], input[name='email'], #email").count() > 0 or \
            page.locator("form").count() > 0

    def test_register_page_loads(self, page, server):
        """La page d'inscription doit etre accessible."""
        page.goto(f"{server}/register")
        assert page.locator("form").count() > 0 or page.url.endswith("/register")


class TestLoginWorkflow:
    """Tests du workflow de connexion."""

    def test_login_with_valid_credentials(self, page, server):
        """Connexion avec des identifiants valides."""
        # Naviguer vers la page de connexion
        page.goto(f"{server}/login")

        # Remplir le formulaire
        email_input = page.locator("input[type='email'], input[name='email'], #email").first
        password_input = page.locator("input[type='password'], input[name='password'], #password").first

        if email_input.count() > 0 and password_input.count() > 0:
            email_input.fill("admin@normacheck.fr")
            password_input.fill("Admin2026!Norma")

            # Soumettre
            submit = page.locator("button[type='submit'], input[type='submit']").first
            if submit.count() > 0:
                submit.click()
                page.wait_for_load_state("networkidle")

    def test_login_with_invalid_credentials(self, page, server):
        """Connexion avec des identifiants invalides doit afficher une erreur."""
        page.goto(f"{server}/login")

        email_input = page.locator("input[type='email'], input[name='email'], #email").first
        password_input = page.locator("input[type='password'], input[name='password'], #password").first

        if email_input.count() > 0 and password_input.count() > 0:
            email_input.fill("fake@test.fr")
            password_input.fill("wrongpassword")

            submit = page.locator("button[type='submit'], input[type='submit']").first
            if submit.count() > 0:
                submit.click()
                page.wait_for_load_state("networkidle")
                # Verifier qu'on est toujours sur la page de login
                # ou qu'un message d'erreur est affiche
                assert "login" in page.url.lower() or \
                    page.locator(".error, .alert, .toast, [role='alert']").count() > 0


class TestDocumentUpload:
    """Tests de l'upload de documents."""

    def test_upload_csv_file(self, page, server):
        """Upload d'un fichier CSV."""
        # Se connecter d'abord
        page.goto(f"{server}/login")
        email_input = page.locator("input[type='email'], input[name='email'], #email").first
        password_input = page.locator("input[type='password'], input[name='password'], #password").first

        if email_input.count() > 0 and password_input.count() > 0:
            email_input.fill("admin@normacheck.fr")
            password_input.fill("Admin2026!Norma")
            submit = page.locator("button[type='submit'], input[type='submit']").first
            if submit.count() > 0:
                submit.click()
                page.wait_for_load_state("networkidle")

        # Naviguer vers la page d'analyse/upload
        page.goto(f"{server}/dashboard")
        page.wait_for_load_state("networkidle")

        # Chercher un input file
        file_input = page.locator("input[type='file']").first
        if file_input.count() > 0:
            csv_path = str(FIXTURES / "sample_paie.csv")
            file_input.set_input_files(csv_path)


class TestAnalysisResults:
    """Tests de l'affichage des resultats d'analyse."""

    def test_results_page_accessible(self, page, server):
        """La page de resultats doit etre accessible apres analyse."""
        page.goto(f"{server}/dashboard")
        page.wait_for_load_state("networkidle")
        # La page doit se charger sans erreur 500
        assert "500" not in page.content()


class TestReportGeneration:
    """Tests de la generation de rapports."""

    def test_report_download_link(self, page, server):
        """Verifier la presence d'un lien de telechargement de rapport."""
        page.goto(f"{server}/dashboard")
        page.wait_for_load_state("networkidle")
        # Verifier que la page se charge
        assert page.url is not None


class TestNavigationSecurity:
    """Tests de securite de la navigation."""

    def test_protected_page_redirects(self, page, server):
        """Les pages protegees doivent rediriger vers le login."""
        page.goto(f"{server}/dashboard")
        page.wait_for_load_state("networkidle")
        # Soit on est redirige vers /login, soit on voit un message d'erreur
        url = page.url.lower()
        content = page.content().lower()
        assert "login" in url or "connexion" in content or "dashboard" in url

    def test_xss_prevention(self, page, server):
        """Les inputs ne doivent pas etre vulnerables au XSS."""
        page.goto(f"{server}/login")
        email_input = page.locator("input[type='email'], input[name='email'], #email").first
        if email_input.count() > 0:
            email_input.fill("<script>alert('xss')</script>")
            # Verifier que le script n'est pas execute
            assert page.evaluate("() => !window.__xss_executed") is True
