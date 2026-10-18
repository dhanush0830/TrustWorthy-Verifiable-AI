"""Tests for CORS configuration and origin enforcement."""
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app


def test_cors_allowed_origin():
    """Verify preflight and requests from configured origin receive allow origin headers."""
    client = TestClient(app)
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_cors_disallowed_origin():
    """Verify requests from unconfigured origins do not receive allow origin headers."""
    client = TestClient(app)
    response = client.options(
        "/health",
        headers={
            "Origin": "http://malicious-site.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") is None


def test_cors_settings_parsing():
    """Verify comma-separated and JSON list CORS_ORIGINS parsing."""
    s1 = Settings(CORS_ORIGINS="https://my-app.vercel.app,http://localhost:3000")
    assert s1.CORS_ORIGINS == ["https://my-app.vercel.app", "http://localhost:3000"]

    s2 = Settings(CORS_ORIGINS='["https://my-app.vercel.app/"]')
    assert s2.CORS_ORIGINS == ["https://my-app.vercel.app"]
