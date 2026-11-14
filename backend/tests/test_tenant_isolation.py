"""Acceptance: users belong to the correct tenant and cannot access other tenants."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.db.session import new_session, set_tenant_context
from app.modules.identity.models import ApiKey, User
from app.modules.tenancy.models import Tenant
from tests.conftest import auth, login, make_tenant, make_user


@pytest.fixture
def two_tenants(client: TestClient):
    a = make_tenant("janaki-tv")
    b = make_tenant("news-co-b")
    a_ed = make_user(a, "ed@janaki.example.com", ["editor"])
    b_ed = make_user(b, "ed@newsb.example.com", ["editor"])
    return a, b, a_ed, b_ed


def test_same_email_can_exist_in_two_tenants(client: TestClient) -> None:
    a = make_tenant("janaki-tv")
    b = make_tenant("news-co-b")
    make_user(a, "shared@example.com", ["reporter"])
    make_user(b, "shared@example.com", ["reporter"])


def test_user_listing_is_scoped(client: TestClient, two_tenants) -> None:
    a, _b, a_ed, _b_ed = two_tenants
    r = client.get("/api/v1/users", headers=auth(login(client, a)))
    emails = {u["email"] for u in r.json()}
    assert emails == {a.email, a_ed.email}
    assert all(u["tenant_id"] == str(a.tenant_id) for u in r.json())


def test_cross_tenant_direct_id_access_returns_404(client: TestClient, two_tenants) -> None:
    a, _b, _, b_ed = two_tenants
    h = auth(login(client, a))
    assert client.get(f"/api/v1/users/{b_ed.user_id}", headers=h).status_code == 404
    assert (
        client.patch(
            f"/api/v1/users/{b_ed.user_id}", json={"is_active": False}, headers=h
        ).status_code
        == 404
    )
    # B's user is untouched.
    assert client.get("/api/v1/auth/me", headers=auth(login(client, b_ed))).status_code == 200


def test_cross_tenant_api_key_operations_return_404(client: TestClient, two_tenants) -> None:
    a, b, _, _ = two_tenants
    hb = auth(login(client, b))
    key = client.post(
        "/api/v1/api-keys", json={"name": "b-key", "scopes": ["articles.read"]}, headers=hb
    ).json()
    key_id = key["api_key"]["id"]
    ha = auth(login(client, a))
    assert client.post(f"/api/v1/api-keys/{key_id}/rotate", headers=ha).status_code == 404
    assert client.delete(f"/api/v1/api-keys/{key_id}", headers=ha).status_code == 404
    assert key_id not in {k["id"] for k in client.get("/api/v1/api-keys", headers=ha).json()}


def test_audit_log_is_scoped(client: TestClient, two_tenants) -> None:
    a, b, _, _ = two_tenants
    client.patch(
        "/api/v1/tenants/current", json={"name": "B Renamed"}, headers=auth(login(client, b))
    )
    rows = client.get("/api/v1/audit-logs", headers=auth(login(client, a))).json()
    assert rows and all(r["action"] != "tenant.updated" for r in rows)


def test_current_tenant_is_derived_from_credential(client: TestClient, two_tenants) -> None:
    a, _b, _, _ = two_tenants
    r = client.get("/api/v1/tenants/current", headers=auth(login(client, a)))
    assert r.json()["id"] == str(a.tenant_id)


# --- database-level RLS (defence in depth, independent of application filters) -------------


def test_rls_hides_other_tenants_rows_even_without_where_clause(two_tenants) -> None:
    a, _b, _, _ = two_tenants
    db = new_session()
    set_tenant_context(db, a.tenant_id)
    user_tenants = [u.tenant_id for u in db.scalars(select(User))]  # deliberately unfiltered
    tenant_ids = [t.id for t in db.scalars(select(Tenant))]
    db.rollback()
    db.close()
    assert user_tenants and set(user_tenants) == {a.tenant_id}
    assert tenant_ids == [a.tenant_id]


def test_rls_without_context_sees_nothing(two_tenants) -> None:
    db = new_session()
    count = db.scalar(text("SELECT count(*) FROM users"))
    db.rollback()
    db.close()
    assert count == 0


def test_rls_blocks_writes_into_another_tenant(two_tenants) -> None:
    a, b, _, _ = two_tenants
    db = new_session()
    set_tenant_context(db, a.tenant_id)
    db.add(
        ApiKey(
            tenant_id=b.tenant_id,
            name="x",
            prefix=uuid.uuid4().hex[:12],
            secret_hash="0" * 64,
            scopes=[],
        )
    )
    with pytest.raises(DBAPIError, match="row-level security"):
        db.flush()
    db.rollback()
    db.close()


def test_rls_blocks_updates_to_another_tenant(two_tenants) -> None:
    a, _b, _, b_ed = two_tenants
    db = new_session()
    set_tenant_context(db, a.tenant_id)
    res = db.execute(
        text("UPDATE users SET full_name='pwned' WHERE id = :id"), {"id": b_ed.user_id}
    )
    db.commit()
    db.close()
    assert res.rowcount == 0  # type: ignore[attr-defined]


def test_tenant_context_does_not_leak_across_transactions(two_tenants) -> None:
    a, _, _, _ = two_tenants
    db = new_session()
    set_tenant_context(db, a.tenant_id)
    assert db.scalar(text("SELECT count(*) FROM users")) > 0
    db.commit()  # transaction-local settings end here
    assert db.scalar(text("SELECT count(*) FROM users")) == 0
    db.close()


def test_app_role_cannot_bypass_rls() -> None:
    db = new_session()
    row = db.execute(
        text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
    ).one()
    db.close()
    assert row == (False, False)
