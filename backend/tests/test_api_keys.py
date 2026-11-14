"""Acceptance: API keys are securely stored and rotatable."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core import security
from app.db.session import new_session, system_scope
from app.modules.identity.models import ApiKey
from tests.conftest import auth, login, make_tenant


def _create(client: TestClient, h: dict[str, str], scopes: list[str], **kw) -> dict:
    r = client.post(
        "/api/v1/api-keys", json={"name": "cms-sync", "scopes": scopes, **kw}, headers=h
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_key_shown_once_and_stored_hashed(client: TestClient) -> None:
    t = make_tenant("alpha")
    h = auth(login(client, t))
    created = _create(client, h, ["tenant.read", "articles.read"])
    plaintext = created["key"]
    assert plaintext.startswith("jnk_")
    listed = client.get("/api/v1/api-keys", headers=h).json()
    assert plaintext not in str(listed)

    db = new_session()
    with system_scope(db):
        row = db.scalar(
            text("SELECT secret_hash || prefix || array_to_string(scopes, ',') FROM api_keys")
        )
    db.close()
    secret = plaintext.split("_", 2)[2]
    assert secret not in row
    assert security.hash_api_key_secret(secret) in row


def test_key_authenticates_with_scoped_permissions(client: TestClient) -> None:
    t = make_tenant("alpha")
    key = _create(client, auth(login(client, t)), ["tenant.read"])["key"]
    hk = {"X-API-Key": key}
    r = client.get("/api/v1/tenants/current", headers=hk)
    assert r.status_code == 200 and r.json()["slug"] == "alpha"
    assert client.get("/api/v1/users", headers=hk).status_code == 403
    assert client.get("/api/v1/auth/me", headers=hk).status_code == 403  # user-only endpoint


def test_forbidden_scopes_rejected(client: TestClient) -> None:
    t = make_tenant("alpha")
    h = auth(login(client, t))
    for scope in [
        "articles.approve",
        "articles.publish",
        "users.manage",
        "apikeys.manage",
        "made.up",
    ]:
        r = client.post("/api/v1/api-keys", json={"name": "x", "scopes": [scope]}, headers=h)
        assert r.status_code == 422, scope


def test_rotation_revokes_old_key(client: TestClient) -> None:
    t = make_tenant("alpha")
    h = auth(login(client, t))
    old = _create(client, h, ["tenant.read"])
    r = client.post(f"/api/v1/api-keys/{old['api_key']['id']}/rotate", headers=h)
    assert r.status_code == 200
    new = r.json()
    assert new["api_key"]["rotated_from_id"] == old["api_key"]["id"]
    assert new["api_key"]["scopes"] == ["tenant.read"]
    assert (
        client.get("/api/v1/tenants/current", headers={"X-API-Key": old["key"]}).status_code == 401
    )
    assert (
        client.get("/api/v1/tenants/current", headers={"X-API-Key": new["key"]}).status_code == 200
    )
    again = client.post(f"/api/v1/api-keys/{old['api_key']['id']}/rotate", headers=h)
    assert again.status_code == 409


def test_revoked_and_expired_keys_fail(client: TestClient) -> None:
    t = make_tenant("alpha")
    h = auth(login(client, t))
    k1 = _create(client, h, ["tenant.read"])
    assert client.delete(f"/api/v1/api-keys/{k1['api_key']['id']}", headers=h).status_code == 200
    assert (
        client.get("/api/v1/tenants/current", headers={"X-API-Key": k1["key"]}).status_code == 401
    )

    k2 = _create(client, h, ["tenant.read"])
    db = new_session()
    with system_scope(db):
        row = db.get(ApiKey, k2["api_key"]["id"])
        assert row is not None
        row.expires_at = security.utcnow() - timedelta(seconds=1)
    db.commit()
    db.close()
    assert (
        client.get("/api/v1/tenants/current", headers={"X-API-Key": k2["key"]}).status_code == 401
    )


def test_malformed_and_wrong_secret_keys(client: TestClient) -> None:
    t = make_tenant("alpha")
    real = _create(client, auth(login(client, t)), ["tenant.read"])["key"]
    prefix = real.split("_")[1]
    for bad in ["garbage", "jnk__", f"jnk_{prefix}_wrongsecret"]:
        assert client.get("/api/v1/tenants/current", headers={"X-API-Key": bad}).status_code == 401
