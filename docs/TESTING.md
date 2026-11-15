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

## Phase 7 results (actually executed, 15 Nov 2026)

| Check | Result |
|---|---|
| `pytest` (Phases 1–7) | **208 passed**, 4 skipped (live checks), 95% coverage |
| `ruff` / `mypy` | clean / no issues (67 files) |
| GitHub CI run 43686712754 (commit `c7c9b76`) | **all green: 212 passed**, 2 skipped (the live website tests, which need a running site), incl. live RSS, Commons and Gemini |
| Migration `0006` up → down → up, `alembic check` | clean, no drift |
| **Live end-to-end** (`tests/test_live_cms.py`) against the real JanakiTelevision code (`pnpm dev`, migration-only database, real integration and API key), run twice | **2 passed both times**: draft created with photo; status draft, AI-labelled, no byline, not public; sources and claim statuses in internal notes; licence on the photo; the integration was refused publish, edit, delete and create-as-published; re-delivery made no duplicate; an administrator published and the newsroom's sync saw `published` |
| Found by the live run | integrations could not read their own record (`/api/integrations/me` → 403; fixed on the website); a repeated headline caused a website slug clash (fixed: slug gets a 6-character code from the article id) |
| Website suite on the branch | 115 integration tests passed; unit tests 211 passed, 3 pre-existing `backup.test.ts` failures that also fail on unmodified `main` in this environment |

The live end-to-end test needs a running website and is **not** part of GitHub CI. Run it with `CMS_E2E_URL`, `CMS_E2E_KEY` and `CMS_E2E_ADMIN_TOKEN` (local or staging site only; see the test's docstring).

Phase 7 coverage (in CI, with an in-memory fake CMS): address rules (https, no paths, credentials, IPs or odd ports; private hosts only with the dev flag; production refuses the flag); internal addresses blocked at connection time; Lexical structure; delivery content and limits; section mapping by slug or left empty; idempotency; recovery after a lost response without a duplicate; CMS rejection recorded and not retried; wrong key; rejected articles never delivered; no connection → 409; status sync incl. published and removed; connection API admin/human-only, key never returned and encrypted at rest, unsafe address refused; tenant isolation; automatic delivery only when switched on.

## Phase 5 results (actually executed, 14 Nov 2026)

| Check | Result |
|---|---|
| `pytest` (Phases 1–5) | **186 passed**, 4 skipped (live checks, run in CI), 96% coverage |
| `ruff` / `mypy` | clean / no issues (62 files) |
| Migration `0005` up → down → up, `alembic check` | clean, no drift |
| S3 storage | tested against `moto` (simulated S3); not yet against a real bucket |
| GitHub CI run 43617344609 (commit `cbeb661`) | **all green: 190 passed** incl. live RSS fetch, live Wikimedia Commons search + download (8/8 results usable, CC BY-SA 4.0) and live Gemini extraction + writing |
| Found by the live check (run 43617037421) | Commons now serves renditions from `thumb.wikimedia.org`; the approved list is now `wikimedia.org` (subdomains) |
| Live Gemini draft with the new checks | "Saptari Floods Displace 2,000 Families as Province Announces Relief" — flagged `single_source_claim` and `unsupported_causal_link`, as intended |

Phase 5 coverage: 10 licence cases; Commons parsing, attribution and non-image skipping; provenance on candidates; no duplicate candidates; non-publishable refused by API and by DB constraints; selection downloads, keeps the source, makes WebP derivatives without EXIF/GPS, tenant-prefixed keys, path traversal refused; corrupt files and decompression bombs refused; no upscaling; same-story rule; human-only and role permissions; tenant isolation (API, files, DB); charts only from verified same-unit figures with escaped SVG; AI illustrations: not configured, photo-first, label, safe prompt, caption label, daily limit, DB label constraint; local and S3 storage.

## Phase 4 results (actually executed, 14 Nov 2026)

| Check | Result |
|---|---|
| `pytest` (Phases 1–4) | **162 passed**, 3 skipped (live checks, run in CI), 96% coverage |
| `ruff` / `mypy` | clean / no issues (53 files) |
| Migration `0004` up → down → up, `alembic check` | clean, no drift |
| GitHub CI run 43615729736 (commit `1784189`) | **all green: 165 passed** incl. live RSS fetch, live Gemini extraction and live Gemini writing |
| Live Gemini draft (gemini-flash-lite-latest, 515 in / 460 out tokens) | Headline "Saptari Floods Displace 2,000 Families"; both paragraphs cite claims; SEO within limits; one `single_source_claim` flag. Observed: the model stated the single-source relief claim without "according to" and the summary implied a causal link ("prompting") not in the claims — both are why human review stays mandatory |

Phase 4 coverage: two distinct angles with citations and limits; no B without distinct evidence; B discarded when repeating A; plan rejected when B reuses A's claims; fabrication flags (invented death toll, headline figure, uncited paragraph, unknown claim ID, invented quote); conflicting-claim flag; eligibility gate; no AI / quota failure / retry / idempotency / already-written; unique slugs; versions immutable in the DB; API: view, edit with re-check and history, unknown claim IDs rejected, regeneration limit, reject, role permissions, API keys blocked as non-human, tenant isolation, eligibility on manual write; worker and hourly schedule.

## Phase 3 results (actually executed, 14 Nov 2026)

| Check | Result |
|---|---|
| `pytest` (Phases 1–3), fresh virtualenv | **148 passed**, 1 skipped (live fetch, runs in CI), 96% coverage |
| `ruff` / `mypy` | clean / no issues (49 files) |
| Migration `0003` up → down → up, `alembic check` | clean, no drift |
| GitHub CI run 43608469560 (commit `7286df4`) | **all steps green, 149 passed, 0 skipped** (incl. live RSS fetch), 96% coverage |
| Real AI provider call (Gemini) | **verified** in CI run 43613492295 with the `GEMINI_API_KEY` secret: model `gemini-flash-lite-latest`, 387 input / 179 output tokens, 2 grounded claims kept (2,000 families displaced; NPR 50 million relief). The model's relief figure was dropped because it was not written that way in the quoted sentence — the grounding check working as designed |

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
