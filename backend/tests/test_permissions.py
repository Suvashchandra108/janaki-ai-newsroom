from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.permissions import (
    API_KEY_ALLOWED,
    DESCRIPTIONS,
    HUMAN_ONLY,
    ROLES,
    P,
    effective_api_key_permissions,
    effective_user_permissions,
)
from app.db.session import new_session
from app.modules.identity.models import Permission, Role, RolePermission
from tests.conftest import auth, login, make_tenant, make_user


def test_database_catalogue_matches_code() -> None:
    db = new_session()
    db_perms = {p.key for p in db.scalars(select(Permission))}
    db_roles: dict[str, set[str]] = {}
    for r in db.scalars(select(Role)):
        db_roles[r.key] = set(
            db.scalars(select(RolePermission.permission_key).where(RolePermission.role_id == r.id))
        )
    db.close()
    assert db_perms == {str(k) for k in DESCRIPTIONS}
    assert db_roles == {k: {str(p) for p in v["permissions"]} for k, v in ROLES.items()}


def test_human_only_permissions_never_reach_machines() -> None:
    granted = {p.value for p in P}
    assert not (effective_user_permissions(granted, is_service=True) & HUMAN_ONLY)
    assert effective_user_permissions(granted, is_service=False) >= HUMAN_ONLY
    assert not (effective_api_key_permissions(granted) & HUMAN_ONLY)
    assert not (API_KEY_ALLOWED & {"users.manage", "apikeys.manage", "billing.manage"})


def test_role_matrix_enforced_by_api(client: TestClient) -> None:
    t = make_tenant("alpha")
    rep = make_user(t, "rep@alpha.example.com", ["reporter"])
    rev = make_user(t, "rev@alpha.example.com", ["reviewer"])
    h_rep, h_rev = auth(login(client, rep)), auth(login(client, rev))
    assert client.get("/api/v1/users", headers=h_rep).status_code == 403
    r = client.post(
        "/api/v1/users",
        json={
            "email": "x@alpha.example.com",
            "full_name": "X",
            "password": "x" * 14,
            "roles": ["tenant_admin"],
        },
        headers=h_rep,
    )
    assert r.status_code == 403  # no privilege escalation
    me = client.get("/api/v1/auth/me", headers=h_rev).json()
    assert "articles.approve" not in me["permissions"]
    assert "articles.reject" in me["permissions"]


def test_admin_creates_user_with_roles_and_unknown_role_rejected(client: TestClient) -> None:
    t = make_tenant("alpha")
    h = auth(login(client, t))
    r = client.post(
        "/api/v1/users",
        json={
            "email": "New@Alpha.example.com",
            "full_name": "New",
            "password": "p" * 14,
            "roles": ["reporter", "reviewer"],
        },
        headers=h,
    )
    assert r.status_code == 201
    assert r.json()["email"] == "new@alpha.example.com"
    assert r.json()["roles"] == ["reporter", "reviewer"]
    dup = client.post(
        "/api/v1/users",
        json={
            "email": "new@alpha.example.com",
            "full_name": "Dup",
            "password": "p" * 14,
            "roles": ["reporter"],
        },
        headers=h,
    )
    assert dup.status_code == 409
    bad = client.post(
        "/api/v1/users",
        json={
            "email": "z@alpha.example.com",
            "full_name": "Z",
            "password": "p" * 14,
            "roles": ["god_mode"],
        },
        headers=h,
    )
    assert bad.status_code == 422


def test_last_tenant_admin_cannot_be_removed(client: TestClient) -> None:
    t = make_tenant("alpha")
    h = auth(login(client, t))
    r = client.patch(f"/api/v1/users/{t.user_id}", json={"roles": ["editor"]}, headers=h)
    assert r.status_code == 409
    me = client.get("/api/v1/auth/me", headers=h).json()
    assert "users.manage" in me["permissions"]  # change was rolled back


def test_cannot_deactivate_self(client: TestClient) -> None:
    t = make_tenant("alpha")
    h = auth(login(client, t))
    r = client.patch(f"/api/v1/users/{t.user_id}", json={"is_active": False}, headers=h)
    assert r.status_code == 403


def test_roles_endpoint(client: TestClient) -> None:
    t = make_tenant("alpha")
    roles = client.get("/api/v1/roles", headers=auth(login(client, t))).json()
    assert {r["key"] for r in roles} == set(ROLES)
