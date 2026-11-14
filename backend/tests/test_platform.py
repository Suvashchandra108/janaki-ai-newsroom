"""Acceptance: multiple tenants can be created; platform admin powers are limited."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.config import Settings
from app.db.session import new_session
from tests.conftest import PASSWORD, Account, auth, login, make_platform_admin, make_tenant


def _provision(client: TestClient, h: dict[str, str], slug: str) -> object:
    return client.post(
        "/api/v1/tenants",
        json={
            "slug": slug,
            "name": slug.title(),
            "default_language": "en",
            "admin_email": f"admin@{slug}.example.com",
            "admin_full_name": "Admin",
            "admin_password": PASSWORD,
        },
        headers=h,
    )


def test_platform_admin_provisions_multiple_tenants(client: TestClient) -> None:
    ops = make_platform_admin()
    h = auth(login(client, ops))
    for slug in ["janaki-tv", "news-co-a", "newspaper-c"]:
        r = _provision(client, h, slug)
        assert r.status_code == 201, r.text
        assert r.json()["tenant"]["settings"]["generation"]["daily_event_cap"] == 10
    assert _provision(client, h, "janaki-tv").status_code == 409
    assert _provision(client, h, "Bad Slug!").status_code == 422
    slugs = {t["slug"] for t in client.get("/api/v1/tenants", headers=h).json()}
    assert slugs == {"janaki-tv", "news-co-a", "newspaper-c"}

    # The new tenant admin can sign in (MFA enrolment then required).
    r = client.post(
        "/api/v1/auth/login",
        json={
            "email": "admin@news-co-a.example.com",
            "password": PASSWORD,
            "tenant_slug": "news-co-a",
        },
    )
    assert r.status_code == 200


def test_tenant_users_cannot_use_platform_endpoints(client: TestClient) -> None:
    t = make_tenant("alpha")
    h = auth(login(client, t))
    assert _provision(client, h, "evil").status_code == 403
    assert client.get("/api/v1/tenants", headers=h).status_code == 403


def test_platform_admin_cannot_read_tenant_newsroom_data(client: TestClient) -> None:
    make_tenant("alpha")
    h = auth(login(client, make_platform_admin()))
    assert client.get("/api/v1/users", headers=h).status_code == 403
    assert client.get("/api/v1/audit-logs", headers=h).status_code == 403


def test_suspending_tenant_blocks_existing_tokens_and_login(client: TestClient) -> None:
    t = make_tenant("alpha")
    tenant_tokens = login(client, t)
    ops_h = auth(login(client, make_platform_admin()))
    r = client.patch(f"/api/v1/tenants/{t.tenant_id}", json={"status": "suspended"}, headers=ops_h)
    assert r.status_code == 200
    r = client.get("/api/v1/tenants/current", headers=auth(tenant_tokens))
    assert r.status_code == 403 and r.json()["error"]["code"] == "tenant_suspended"
    with pytest.raises(AssertionError):
        login(client, Account(t.user_id, t.email, "alpha", t.tenant_id, t.totp_secret))
    client.patch(f"/api/v1/tenants/{t.tenant_id}", json={"status": "active"}, headers=ops_h)
    assert client.get("/api/v1/tenants/current", headers=auth(tenant_tokens)).status_code == 200


def test_audit_log_is_append_only_for_app_role(client: TestClient) -> None:
    t = make_tenant("alpha")
    login(client, t)
    db = new_session()
    with pytest.raises(DBAPIError, match="permission denied"):
        db.execute(text("UPDATE audit_logs SET action = 'x'"))
    db.rollback()
    with pytest.raises(DBAPIError, match="permission denied"):
        db.execute(text("DELETE FROM audit_logs"))
    db.rollback()
    db.close()


def test_production_refuses_default_secrets() -> None:
    with pytest.raises(ValueError, match="Insecure secrets"):
        Settings(environment="production")


def test_health_and_ready(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ready"}
