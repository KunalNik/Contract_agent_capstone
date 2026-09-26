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


PUBLIC_ROUTES = {
    "/", "/api/health", "/api/documents/status", "/api/documents/enhanced/status",
    "/api/intelligence/models", "/api/contracts/search/clause-types", "/api/contracts/search/section-types",
    "/api/monitoring/health", "/api/patterns/capabilities", "/api/policies/",
}


def test_every_data_route_requires_authentication():
    from fastapi.routing import APIRoute
    from backend.main import app
    from backend.governance.rbac import get_current_user

    def has_auth(dep):
        return dep.call is get_current_user or any(has_auth(d) for d in dep.dependencies)

    unauthenticated = [r.path for r in app.routes
                       if isinstance(r, APIRoute) and r.path not in PUBLIC_ROUTES and not has_auth(r.dependant)]
    assert unauthenticated == []


def test_header_auth_cannot_be_enabled_in_production(monkeypatch):
    from backend.governance.rbac import auth_mode
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_MODE", "header")
    assert auth_mode() == "jwt"
