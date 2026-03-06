"""Configuration Playwright pour les tests E2E.

Lance le serveur FastAPI en arriere-plan et configure le navigateur.
Screenshots automatiques en cas d'echec.
"""

import os
import sys
import time
import signal
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
SCREENSHOTS_DIR = ROOT / "tests" / "e2e" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8765
BASE_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"


@pytest.fixture(scope="session")
def server():
    """Lance le serveur FastAPI pour les tests E2E."""
    env = os.environ.copy()
    env["NORMACHECK_ENV"] = "test"
    env["NORMACHECK_SECRET_KEY"] = "test-secret-key-for-e2e-testing-only-2026"
    env["PORT"] = str(SERVER_PORT)

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.index:app",
         "--host", SERVER_HOST, "--port", str(SERVER_PORT)],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Attendre que le serveur demarre
    for _ in range(30):
        try:
            import urllib.request
            urllib.request.urlopen(f"{BASE_URL}/api/health", timeout=1)
            break
        except Exception:
            time.sleep(0.5)
    else:
        proc.terminate()
        pytest.skip("Serveur FastAPI non disponible pour les tests E2E")

    yield BASE_URL

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="session")
def browser_context(server):
    """Configure le navigateur Playwright."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("Playwright non installe. Installer avec: pip install playwright && playwright install")

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1280, "height": 720},
        base_url=server,
    )
    context.set_default_timeout(10000)

    yield context

    context.close()
    browser.close()
    pw.stop()


@pytest.fixture
def page(browser_context, request):
    """Page Playwright avec screenshot automatique en cas d'echec."""
    pg = browser_context.new_page()
    yield pg

    # Screenshot automatique en cas d'echec
    if request.node.rep_call and request.node.rep_call.failed:
        test_name = request.node.name.replace("/", "_").replace("::", "_")
        screenshot_path = SCREENSHOTS_DIR / f"FAIL_{test_name}.png"
        try:
            pg.screenshot(path=str(screenshot_path), full_page=True)
        except Exception:
            pass

    pg.close()


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Hook pour capturer le statut du test pour les screenshots."""
    import pluggy
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)
