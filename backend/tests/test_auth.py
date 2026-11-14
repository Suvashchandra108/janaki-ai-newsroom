from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import new_session, system_scope
from app.modules.audit.models import AuditLog
from tests.conftest import PASSWORD, auth, login, make_tenant, make_user

LOGIN = "/api/v1/auth/login"


def test_login_and_me(client: TestClient) -> None:
    t = make_tenant("alpha")
    editor = make_user(t, "ed@alpha.example.com", ["editor"])
    tokens = login(client, editor)
    assert tokens["token_type"] == "bearer"
    r = client.get("/api/v1/auth/me", headers=auth(tokens))
    assert r.status_code == 200
    me = r.json()
    assert me["tenant_id"] == str(t.tenant_id)
    assert "articles.approve" in me["permissions"]
    assert me["mfa_enrollment_required"] is False


def test_wrong_password_unknown_user_and_unknown_tenant_look_identical(client: TestClient) -> None:
    t = make_tenant("alpha")
    make_user(t, "ed@alpha.example.com", ["editor"])
    cases = [
        {"email": "ed@alpha.example.com", "password": "wrong-password-xx", "tenant_slug": "alpha"},
        {"email": "nobody@alpha.example.com", "password": PASSWORD, "tenant_slug": "alpha"},
        {"email": "ed@alpha.example.com", "password": PASSWORD, "tenant_slug": "nope"},
    ]
    bodies = []
    for c in cases:
        r = client.post(LOGIN, json=c)
        assert r.status_code == 401
        err = r.json()["error"]
        bodies.append((err["code"], err["message"]))
    assert len(set(bodies)) == 1


def test_lockout_after_repeated_failures_and_failures_are_audited(client: TestClient) -> None:
    t = make_tenant("alpha")
    ed = make_user(t, "ed@alpha.example.com", ["editor"])
    bad = {"email": ed.email, "password": "wrong-password-xx", "tenant_slug": "alpha"}
    for _ in range(5):
        assert client.post(LOGIN, json=bad).status_code == 401
    # Correct password is now refused while locked.
    good = {"email": ed.email, "password": PASSWORD, "tenant_slug": "alpha"}
    assert client.post(LOGIN, json=good).status_code == 401

    db = new_session()
    with system_scope(db):
        rows = db.scalars(select(AuditLog).where(AuditLog.action == "auth.login_failed")).all()
    db.close()
    assert len(rows) == 6  # persisted despite the requests failing
    assert any("locked" in r.details["reason"] for r in rows)


def test_email_is_case_insensitive(client: TestClient) -> None:
    t = make_tenant("alpha")
    make_user(t, "ed@alpha.example.com", ["editor"])
    r = client.post(
        LOGIN, json={"email": "ED@Alpha.Example.com", "password": PASSWORD, "tenant_slug": "alpha"}
    )
    assert r.status_code == 200


def test_refresh_rotates_and_reuse_kills_session(client: TestClient) -> None:
    t = make_tenant("alpha")
    ed = make_user(t, "ed@alpha.example.com", ["editor"])
    first = login(client, ed)
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 200
    second = r.json()
    assert second["refresh_token"] != first["refresh_token"]

    # Replay the old (rotated) refresh token -> theft detected, session revoked.
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 401
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]})
    assert r.status_code == 401
    assert client.get("/api/v1/auth/me", headers=auth(second)).status_code == 401


def test_garbage_refresh_token(client: TestClient) -> None:
    for tok in ["not-a-token-at-all", "00000000-0000-0000-0000-000000000000.abc"]:
        r = client.post("/api/v1/auth/refresh", json={"refresh_token": tok})
        assert r.status_code == 401


def test_logout_revokes_access_immediately(client: TestClient) -> None:
    t = make_tenant("alpha")
    ed = make_user(t, "ed@alpha.example.com", ["editor"])
    tokens = login(client, ed)
    assert client.post("/api/v1/auth/logout", json={}, headers=auth(tokens)).status_code == 204
    assert client.get("/api/v1/auth/me", headers=auth(tokens)).status_code == 401


def test_password_change_revokes_other_sessions(client: TestClient) -> None:
    t = make_tenant("alpha")
    ed = make_user(t, "ed@alpha.example.com", ["editor"])
    s1 = login(client, ed)
    s2 = login(client, ed)
    r = client.post(
        "/api/v1/auth/password",
        json={"current_password": PASSWORD, "new_password": "a brand new long passphrase"},
        headers=auth(s1),
    )
    assert r.status_code == 204
    assert client.get("/api/v1/auth/me", headers=auth(s1)).status_code == 200
    assert client.get("/api/v1/auth/me", headers=auth(s2)).status_code == 401
    login(client, ed, password="a brand new long passphrase")


def test_weak_password_rejected(client: TestClient) -> None:
    t = make_tenant("alpha")
    ed = make_user(t, "ed@alpha.example.com", ["editor"])
    r = client.post(
        "/api/v1/auth/password",
        json={"current_password": PASSWORD, "new_password": "short"},
        headers=auth(login(client, ed)),
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "weak_password"


def test_service_account_cannot_log_in(client: TestClient) -> None:
    t = make_tenant("alpha")
    svc = make_user(t, "worker@alpha.example.com", ["editor"], kind="service")
    r = client.post(LOGIN, json={"email": svc.email, "password": PASSWORD, "tenant_slug": "alpha"})
    assert r.status_code == 401


def test_deactivated_user_token_is_rejected_immediately(client: TestClient) -> None:
    t = make_tenant("alpha")
    ed = make_user(t, "ed@alpha.example.com", ["editor"])
    ed_tokens = login(client, ed)
    admin_tokens = login(client, t)
    r = client.patch(
        f"/api/v1/users/{ed.user_id}", json={"is_active": False}, headers=auth(admin_tokens)
    )
    assert r.status_code == 200
    assert client.get("/api/v1/auth/me", headers=auth(ed_tokens)).status_code == 401


def test_tampered_jwt_rejected(client: TestClient) -> None:
    t = make_tenant("alpha")
    tokens = login(client, make_user(t, "ed@alpha.example.com", ["editor"]))
    head, payload, sig = tokens["access_token"].split(".")
    forged = f"{head}.{payload}.{sig[:-2]}AA"
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


def test_unauthenticated_and_error_shape(client: TestClient) -> None:
    r = client.get("/api/v1/users")
    assert r.status_code == 401
    body = r.json()["error"]
    assert body["code"] == "unauthorized" and body["request_id"]
    assert r.headers["x-content-type-options"] == "nosniff"
