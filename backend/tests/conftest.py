"""Test fixtures. Tests run against a real PostgreSQL database using the RLS-enforced app role.

Required env (defaults match docs/TESTING.md):
  TEST_DATABASE_URL        app role  -> janaki_test
  TEST_DATABASE_OWNER_URL  owner role -> janaki_test
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://janaki_app:app_dev_pw@localhost:5432/janaki_test"
)
os.environ["DATABASE_OWNER_URL"] = os.environ.get(
    "TEST_DATABASE_OWNER_URL",
    "postgresql+psycopg://janaki_owner:owner_dev_pw@localhost:5432/janaki_test",
)

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core import security
from app.db.session import new_session, system_scope
from app.main import app
from app.modules.identity import service as identity
from app.modules.identity.models import User
from app.modules.tenancy import service as tenancy

PASSWORD = "correct horse battery staple"
TABLES = (
    "discovered_items, news_events, background_jobs, news_sources, "
    "audit_logs, api_keys, auth_sessions, user_roles, users, tenants"
)


@pytest.fixture(scope="session", autouse=True)
def migrated_db() -> Iterator[None]:
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    cfg.set_main_option("sqlalchemy.url", os.environ["DATABASE_OWNER_URL"])
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def clean_tables() -> Iterator[None]:
    yield
    engine = create_engine(os.environ["DATABASE_OWNER_URL"])
    with engine.begin() as conn:
        # A test that leaks an open transaction must fail loudly, not hang the suite.
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    engine.dispose()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@dataclass
class Account:
    user_id: uuid.UUID
    email: str
    tenant_slug: str | None
    tenant_id: uuid.UUID | None
    totp_secret: str | None = None


def enable_mfa(user_id: uuid.UUID) -> str:
    secret = pyotp.random_base32()
    db = new_session()
    with system_scope(db):
        u = db.get(User, user_id)
        assert u is not None
        u.mfa_secret_enc = security.encrypt_secret(secret)
        u.mfa_enabled = True
    db.commit()
    db.close()
    return secret


def reset_totp_counter(user_id: uuid.UUID) -> None:
    db = new_session()
    with system_scope(db):
        u = db.get(User, user_id)
        assert u is not None
        u.mfa_last_counter = None
    db.commit()
    db.close()


def make_tenant(slug: str, *, admin_email: str | None = None) -> Account:
    db = new_session()
    t, admin = tenancy.provision_tenant(
        db,
        None,
        slug=slug,
        name=slug.title(),
        default_language="en",
        admin_email=admin_email or f"admin@{slug}.example.com",
        admin_full_name="Admin",
        admin_password=PASSWORD,
    )
    db.commit()
    db.close()
    acct = Account(admin.id, admin.email, slug, t.id)
    acct.totp_secret = enable_mfa(admin.id)  # admins require MFA
    return acct


def make_user(tenant: Account, email: str, roles: list[str], kind: str = "human") -> Account:
    db = new_session()
    with system_scope(db):
        assert tenant.tenant_id
        u = identity.create_user(
            db,
            tenant_id=tenant.tenant_id,
            email=email,
            full_name=email.split("@")[0],
            password=PASSWORD if kind == "human" else None,
            roles=roles,
            kind=kind,
        )
    db.commit()
    db.close()
    return Account(u.id, u.email, tenant.tenant_slug, tenant.tenant_id)


def make_platform_admin(email: str = "ops@platform.example.com") -> Account:
    db = new_session()
    u = identity.create_platform_admin(db, email=email, full_name="Ops", password=PASSWORD)
    db.commit()
    db.close()
    acct = Account(u.id, u.email, None, None)
    acct.totp_secret = enable_mfa(u.id)
    return acct


def login(client: TestClient, acct: Account, password: str = PASSWORD) -> dict[str, str]:
    body: dict[str, str | None] = {
        "email": acct.email,
        "password": password,
        "tenant_slug": acct.tenant_slug,
    }
    if acct.totp_secret:
        reset_totp_counter(acct.user_id)  # allow several logins within one 30 s window
        body["totp_code"] = pyotp.TOTP(acct.totp_secret).now()
    r = client.post("/api/v1/auth/login", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def auth(tokens: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}
