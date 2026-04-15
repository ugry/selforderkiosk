"""
Shared fixtures for the restaurant kiosk test suite.
Tests can run against a live stack (BASE_URL env var) or a local dev server.
"""
import os
import pytest
import httpx
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page


# ── Configuration ──────────────────────────────────────────────────────────────

BASE_URL     = os.environ.get("BASE_URL",     "http://localhost:8080")
ADMIN_USER   = os.environ.get("ADMIN_USER",   "admin")
ADMIN_PASS   = os.environ.get("ADMIN_PASS",   "admin123")
TEST_API_KEY = os.environ.get("TEST_API_KEY", "")


# ── pytest-playwright base_url injection ──────────────────────────────────────

def pytest_configure(config):
    """Push BASE_URL into pytest-playwright's base_url option."""
    if not config.option.__dict__.get("base_url"):
        config.option.base_url = BASE_URL


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


# ── HTTP client ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def http():
    """Plain httpx client (no auth) for health-check and public API calls."""
    with httpx.Client(base_url=BASE_URL, timeout=15) as client:
        yield client


@pytest.fixture(scope="session")
def api():
    """httpx client pre-configured with the test machine's API key."""
    assert TEST_API_KEY, (
        "Set TEST_API_KEY env var to a valid machine API key before running tests.\n"
        "Create a machine in the admin panel and copy its key."
    )
    with httpx.Client(
        base_url=BASE_URL,
        headers={"X-Api-Key": TEST_API_KEY},
        timeout=15,
    ) as client:
        yield client


# ── Playwright browser ─────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def browser_instance():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        yield browser
        browser.close()


@pytest.fixture
def browser_ctx(browser_instance: Browser) -> BrowserContext:
    ctx = browser_instance.new_context(
        base_url=BASE_URL,
        ignore_https_errors=True,
    )
    yield ctx
    ctx.close()


@pytest.fixture
def page(browser_ctx: BrowserContext) -> Page:
    p = browser_ctx.new_page()
    yield p
    p.close()


@pytest.fixture
def admin_page(browser_ctx: BrowserContext) -> Page:
    """A Playwright page already authenticated as admin."""
    p = browser_ctx.new_page()
    p.goto(f"{BASE_URL}/admin/login")
    p.fill("input[name='username']", ADMIN_USER)
    p.fill("input[name='password']", ADMIN_PASS)
    p.click("button[type='submit']")
    p.wait_for_url("**/admin/**", timeout=10_000)
    yield p
    p.close()
