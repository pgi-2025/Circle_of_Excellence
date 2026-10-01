"""
Basic smoke tests.

These import the Flask app and hit endpoints that don't require a live
Supabase connection (health check, 404 handling, CORS/rate-limit setup).
Full integration tests against assessment/coupon/enrollment flows need
a real (or test) Supabase project with SUPABASE_URL/keys set, since the
services call out to Supabase directly.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

import pytest
from app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_health_check(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["message"] == "API is running"


def test_404_on_unknown_route(client):
    resp = client.get("/api/does-not-exist")
    assert resp.status_code == 404
    body = resp.get_json()
    assert body["success"] is False


def test_protected_route_requires_auth(client):
    resp = client.get("/api/students/profile")
    assert resp.status_code == 401


def test_admin_route_requires_auth(client):
    resp = client.get("/api/admin/students")
    assert resp.status_code == 401


def test_ambassador_route_requires_auth(client):
    resp = client.get("/api/ambassador/profile")
    assert resp.status_code == 401


def test_ambassador_login_missing_fields(client):
    resp = client.post("/api/ambassador/login", json={})
    assert resp.status_code == 400


def test_certificate_verify_not_found(client, monkeypatch):
    def fake_verify(code):
        raise ValueError("Certificate not found.")

    import routes.certificates as cert_routes
    monkeypatch.setattr(cert_routes, "verify_certificate", fake_verify)

    resp = client.get("/api/certificates/verify/DOES-NOT-EXIST")
    assert resp.status_code == 404
