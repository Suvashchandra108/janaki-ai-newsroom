# Testing

Tests run against a **real PostgreSQL** database, connected as the RLS-enforced app role, because tenant isolation cannot be meaningfully tested on SQLite or as a superuser.

## One-time setup

```sql
-- as a PostgreSQL superuser
CREATE ROLE janaki_owner LOGIN PASSWORD 'owner_dev_pw';
CREATE ROLE janaki_app   LOGIN PASSWORD 'app_dev_pw' NOSUPERUSER NOBYPASSRLS;
CREATE DATABASE janaki_test OWNER janaki_owner;
```

```bash
cd backend
pip install -e ".[dev]"
```

Override connection strings with `TEST_DATABASE_URL` (app role) and `TEST_DATABASE_OWNER_URL` (owner role).

## Commands

```bash
cd backend
pytest --cov=app                 # migrates janaki_test down/up, then runs all tests
ruff format --check . && ruff check .
mypy
alembic check                    # models and migrations agree (needs DATABASE_OWNER_URL)
python -c "import json; from app.main import app; json.dump(app.openapi(), open('../docs/openapi.json','w'), indent=2)"
```

## Phase 1 results (actually executed, 14 Nov 2026, PostgreSQL 16.15, Python 3.13)

| Check | Result |
|---|---|
| `pytest` | **51 passed**, 0 failed |
| Coverage (`app/`) | **97%** |
| `ruff check` / `ruff format --check` | clean |
| `mypy` | no issues (34 files) |
| `alembic upgrade → downgrade → upgrade` | clean |
| `alembic check` | no drift between models and migration |
| Live HTTP smoke test (uvicorn + bootstrap scripts) | login → MFA enrolment gate → enable → users/tenant/API key/audit all as expected |
| `docker compose config` | valid |
| `docker compose up` | **not run** — no Docker daemon in the build environment. Run locally: `docker compose up --build` |

## What the suite covers

- **Tenant isolation (API):** listing, direct-ID read/update, API-key rotate/revoke and audit log access across tenants.
- **Tenant isolation (database):** unfiltered queries under RLS; no context ⇒ zero rows; cross-tenant INSERT blocked by `WITH CHECK`; cross-tenant UPDATE matches 0 rows; context does not survive commit; app role is not superuser and cannot bypass RLS.
- **Auth:** identical errors for wrong password / unknown user / unknown tenant; lockout; failures audited despite rollback; refresh rotation and reuse detection; logout and password change revoke sessions; deactivation is immediate; tampered JWT; service accounts cannot log in.
- **MFA:** admin enrolment gate; login requires code; replay rejected; drift window; secret encrypted at rest; admin reset revokes sessions.
- **RBAC:** DB catalogue equals code; human-only permissions never reach service accounts or API keys; role matrix; no privilege escalation; last-admin protection.
- **API keys:** shown once, stored as HMAC; scoped; forbidden scopes rejected; rotation; revocation; expiry; malformed keys.
- **Platform:** multiple tenants provisioned; tenant users blocked from platform endpoints; platform admin blocked from tenant data; suspension blocks existing tokens; audit log append-only for app role; production refuses default secrets.

## Bug found by the tests

`system_scope()` originally switched the RLS bypass off before SQLAlchemy flushed pending changes (`autoflush=False`), so updates silently matched zero rows. Fixed by flushing inside the scope; covered by MFA/lockout tests.

## Not yet tested

Load, concurrency races (e.g. simultaneous refresh), external penetration testing, Docker images. Planned for Phase 9.
