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

## Continuous integration (GitHub Actions)

`.github/workflows/ci.yml` runs on every push to `main` and every pull request: clean install, ruff, mypy, `alembic upgrade` + `alembic check`, and the full test suite against PostgreSQL 16 and Redis 7, with `LIVE_FETCH=1` so one test fetches a real public RSS feed through `SafeFetcher`.

**Stage 2 sign-off — CI run 43607339635 (commit `e5db466`, 14 Nov 2026): all steps green, 110 passed, 0 skipped, 96% coverage**, including the live RSS fetch.

The first CI run (commit `5bcc45a`) failed and exposed two real defects the sandbox could not: the package was not installable (`pip install .`, also used by the Dockerfile), and a lint auto-fix had unregistered the discovery models from Alembic's metadata. Both fixed in `e5db466`; `tests/test_metadata.py` now guards the registry.

## Phase 3 results (actually executed, 14 Nov 2026)

| Check | Result |
|---|---|
| `pytest` (Phases 1–3), fresh virtualenv | **148 passed**, 1 skipped (live fetch, runs in CI), 96% coverage |
| `ruff` / `mypy` | clean / no issues (49 files) |
| Migration `0003` up → down → up, `alembic check` | clean, no drift |
| GitHub CI run 43608469560 (commit `7286df4`) | **all steps green, 149 passed, 0 skipped** (incl. live RSS fetch), 96% coverage |
| Real AI provider calls | **not verified** — no API key configured yet. Adapters tested against recorded request/response shapes (Gemini, OpenAI-compatible) |

Phase 3 coverage: main-text extraction; robots.txt (disallow, 404, 503, unreachable); grounded validation (invented excerpts, numbers absent from excerpts, quote/whitespace normalisation, bad types, duplicates, limits); claim matching; numeric conflicts incl. unit plurals; syndication-aware independence; every status rule; end-to-end: corroboration, contradiction, single source, syndicated copies, hostile page + compromised model, no AI configured, quota interruption and resume without double spending, idempotency, re-runs without duplicates, robots respected, daily cap and prioritisation, worker and scheduler; API: inspection, review rules (note required, reporter blocked, API key blocked as non-human), tenant isolation, manual research, usage report.

## Phase 2 results (actually executed, 14 Nov 2026)

| Check | Result |
|---|---|
| `pytest` (Phases 1 + 2) | **108 passed**, 0 failed, ~26 s |
| Coverage (`app/`) | **96%** |
| `ruff` / `mypy` | clean / no issues (41 files) |
| Migration `0002` up → down → up, `alembic check` | clean, no drift |
| Real Celery worker + Redis + dev DB | task received, ran, per-source error recorded, retry scheduled under the same job |
| Fetching a real public RSS feed | Not possible in the sandbox (no internet); **verified in GitHub CI** (see above) |
| `docker compose config` (now with `worker`, `beat`) | valid; `docker compose up` not run (no daemon) |

Phase 2 coverage: SSRF (scheme/port/credential/IP-literal/domain checks, 14 IP classes, internal and mixed DNS answers, pinned connection to a real local server, redirects to foreign hosts and cloud metadata, redirect loops, size cap, content type, HTTP errors); URL canonicalisation; clustering; RSS/Atom parsing incl. double-encoded HTML; ingestion with cross-publisher clustering and preserved source items; idempotent keys; retry reusing the job; partial failures; quota; pause; disabled sources; search approved-publisher filter; tenant isolation of discovery data and APIs; worker execution and hourly scheduler.

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
