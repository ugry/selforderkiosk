"""
Health & connectivity tests — no API key required.
"""
import pytest
import httpx
from conftest import BASE_URL


def test_health_endpoint(http):
    """GET /health must return 200 and {"status": "ok"}."""
    r = http.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "ok"


def test_health_fast(http):
    """Health check must respond within 3 seconds."""
    import time
    start = time.time()
    http.get("/health")
    assert time.time() - start < 3.0


def test_admin_login_page(http):
    """Admin login page must be accessible without auth."""
    r = http.get("/admin/login")
    assert r.status_code == 200
    assert "login" in r.text.lower() or "password" in r.text.lower()


def test_api_requires_key(http):
    """API endpoints must reject requests without an API key."""
    r = http.get("/api/v1/settings")
    assert r.status_code in (401, 403)


def test_api_rejects_bad_key(http):
    """API endpoints must reject an invalid API key."""
    r = http.get("/api/v1/settings", headers={"X-Api-Key": "invalid-key-xyz"})
    assert r.status_code in (401, 403)
