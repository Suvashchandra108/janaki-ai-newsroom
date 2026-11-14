from __future__ import annotations

import pyotp
from fastapi.testclient import TestClient

from app.core import security
from tests.conftest import PASSWORD, auth, login, make_tenant, make_user, reset_totp_counter

LOGIN = "/api/v1/auth/login"


def test_admin_without_mfa_must_enrol_before_doing_anything(client: TestClient) -> None:
    t = make_tenant("alpha")
    # Second admin with no MFA yet.
    admin2 = make_user(t, "admin2@alpha.example.com", ["tenant_admin"])
    tokens = login(client, admin2)
    me = client.get("/api/v1/auth/me", headers=auth(tokens)).json()
    assert me["mfa_enrollment_required"] is True
    r = client.get("/api/v1/users", headers=auth(tokens))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "mfa_enrollment_required"

    setup = client.post("/api/v1/auth/mfa/setup", headers=auth(tokens)).json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/")
    bad = client.post("/api/v1/auth/mfa/enable", json={"code": "000000"}, headers=auth(tokens))
    assert bad.status_code == 400
    code = pyotp.TOTP(setup["secret"]).now()
    r = client.post("/api/v1/auth/mfa/enable", json={"code": code}, headers=auth(tokens))
    assert r.status_code == 204
    assert client.get("/api/v1/users", headers=auth(tokens)).status_code == 200


def test_mfa_login_requires_valid_code_and_blocks_replay(client: TestClient) -> None:
    t = make_tenant("alpha")
    assert t.totp_secret
    base = {"email": t.email, "password": PASSWORD, "tenant_slug": "alpha"}
    r = client.post(LOGIN, json=base)
    assert r.status_code == 401 and r.json()["error"]["code"] == "mfa_required"
    r = client.post(LOGIN, json={**base, "totp_code": "123456x"[:6]})
    assert r.status_code == 401

    reset_totp_counter(t.user_id)
    code = pyotp.TOTP(t.totp_secret).now()
    assert client.post(LOGIN, json={**base, "totp_code": code}).status_code == 200
    # Same code again is a replay.
    r = client.post(LOGIN, json={**base, "totp_code": code})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_mfa_code"


def test_non_admin_does_not_need_mfa(client: TestClient) -> None:
    t = make_tenant("alpha")
    rep = make_user(t, "rep@alpha.example.com", ["reporter"])
    me = client.get("/api/v1/auth/me", headers=auth(login(client, rep))).json()
    assert me["mfa_enrollment_required"] is False


def test_admin_can_reset_user_mfa(client: TestClient) -> None:
    t = make_tenant("alpha")
    rep = make_user(t, "rep@alpha.example.com", ["reporter"])
    rep_tokens = login(client, rep)
    secret = client.post("/api/v1/auth/mfa/setup", headers=auth(rep_tokens)).json()["secret"]
    code = pyotp.TOTP(secret).now()
    client.post("/api/v1/auth/mfa/enable", json={"code": code}, headers=auth(rep_tokens))
    r = client.patch(
        f"/api/v1/users/{rep.user_id}", json={"reset_mfa": True}, headers=auth(login(client, t))
    )
    assert r.status_code == 200 and r.json()["mfa_enabled"] is False
    # Existing sessions were revoked by the reset.
    assert client.get("/api/v1/auth/me", headers=auth(rep_tokens)).status_code == 401


def test_totp_unit_drift_and_replay() -> None:
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    now = int(security.utcnow().timestamp()) // 30
    prev_code = totp.generate_otp(now - 1)
    assert security.verify_totp(secret, prev_code, last_counter=None) == now - 1
    assert security.verify_totp(secret, prev_code, last_counter=now - 1) is None
    assert security.verify_totp(secret, totp.generate_otp(now - 5), last_counter=None) is None
    assert security.verify_totp(secret, "abcdef", last_counter=None) is None


def test_mfa_secret_encrypted_at_rest() -> None:
    enc = security.encrypt_secret("JBSWY3DPEHPK3PXP")
    assert "JBSWY3DPEHPK3PXP" not in enc
    assert security.decrypt_secret(enc) == "JBSWY3DPEHPK3PXP"
