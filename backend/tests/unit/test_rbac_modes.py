"""Regression tests for authentication modes and tenant binding."""
import pytest


def test_header_mode_is_default_in_development(client, monkeypatch):
    monkeypatch.delenv("AUTH_MODE", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "development")
    assert client.get("/api/audit/errors/recent").status_code == 200
    r = client.get("/api/audit/errors/recent", headers={"X-User-Role": "viewer"})
    assert r.status_code == 403


def test_production_requires_a_valid_token(client, monkeypatch):
    monkeypatch.delenv("AUTH_MODE", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET", "unit-test-secret-with-enough-length-123")
    # No token -> 401, and a role header cannot grant access
    assert client.get("/api/audit/errors/recent").status_code == 401
    assert client.get("/api/audit/errors/recent", headers={"X-User-Role": "ADMIN"}).status_code == 401

    from backend.governance.rbac import create_access_token
    token = create_access_token("u1", "AUDITOR", "tenant-x")
    r = client.get("/api/audit/errors/recent", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    bad = client.get("/api/audit/errors/recent", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401


def test_token_tenant_cannot_be_overridden_by_header(monkeypatch):
    import asyncio
    from backend.governance.rbac import create_access_token, get_current_user

    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setenv("JWT_SECRET", "unit-test-secret-with-enough-length-123")
    token = create_access_token("u1", "VIEWER", "tenant-x")
    user = asyncio.run(get_current_user(authorization=f"Bearer {token}", x_user_role="ADMIN", x_tenant_id="tenant-y"))
    assert (user.role.value, user.tenant_id) == ("VIEWER", "tenant-x")
