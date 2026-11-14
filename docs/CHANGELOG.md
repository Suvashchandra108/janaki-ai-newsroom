# Changelog

## [0.3.0] — 2026-11-14 — Phase 3: research and evidence
- Tables: `source_documents`, `claims`, `evidence`, `usage_records` (migration `0003`, RLS; usage ledger append-only).
- Article retrieval through `SafeFetcher`, approved domains only, robots.txt honoured (4xx ⇒ allowed, 5xx/unreachable ⇒ retry later); main-text extraction.
- AI gateway: Gemini and OpenAI-compatible (Groq, OpenRouter, OpenAI) adapters; models set by configuration only; HTTPS-only endpoints; errors classified as retryable or not.
- Grounded claim extraction: excerpt must appear verbatim in the article, numbers must appear in the excerpt; untrusted-data prompt; delimiter spoofing neutralised; strict schema.
- Rule-based verification: cross-publisher claim matching, numeric conflict detection (2% tolerance, unit-normalised), independent-publisher counting with syndication collapsed, statuses corroborated / conflicting / insufficient / editor_verified.
- Research jobs: hourly schedule (minute 20) within the tenant's daily event cap, multi-publisher events first, idempotent per event per day, quota interruptions resume without re-sending processed articles.
- API: `/events/{id}/claims`, `/events/{id}/research` (GET/POST), `/claims/{id}`, `/claims/{id}/review` (human only, note required), `/usage/ai`.
- 148 tests passing (96% coverage).

### Fixed during Phase 3
- New evidence was not flushed before status recomputation, so the latest article could be ignored.
- Research scheduler read event IDs after closing its session.
- Unit normalisation treated "families" and "family" as different units.
- `httpx` was only a test dependency although the gateway needs it at runtime.


## [0.2.1] — 2026-11-14 — Stage 2 verified in CI
- Repository published privately at github.com/Suvashchandra108/janaki-ai-newsroom.
- GitHub Actions CI added (install, lint, types, migration drift, tests incl. live RSS fetch).
- Fixed: package not installable (missing build-system / package discovery config).
- Fixed: discovery models dropped from Alembic metadata by a lint auto-fix; guard test added.
- CI run on `e5db466`: all green, 110 passed.


## [0.2.0] — 2026-11-14 — English-first decision and Phase 2

### Decision
- English-only launch: new tenants default to `languages: ["en"]`, `default_language: en`; Nepali remains supported in the schema and is enabled per tenant later. Cost model updated for free-tier-first AI.

### Phase 2 — news discovery
- Tables: `news_sources`, `discovered_items`, `news_events`, `background_jobs` (migration `0002`, RLS on all four; sources cannot be deleted, only disabled).
- `SafeFetcher`: approved-domain allow-list re-checked on every redirect, DNS resolved once with all addresses required to be public, connection pinned to the validated IP, size/time/content-type limits.
- RSS/Atom adapter (feedparser on bytes only); search-provider interface with approved-publisher filtering (no concrete provider yet).
- Canonical URLs (tracking parameters, `www`, fragments, trailing slashes removed) for duplicate detection; per-tenant uniqueness.
- Event clustering v1: headline keywords with light stemming + 64-bit SimHash, 48-hour window; every source item kept and linked to its event.
- Celery worker and hourly beat (minute 5); one job per tenant per hour keyed `discovery:<tenant>:<hour>`; retries reuse the same job; per-source errors recorded without stopping other sources.
- Daily item quota in the tenant's timezone (default Asia/Kathmandu, 100/day), pause/resume, manual run, job history, status endpoint.
- API: `/sources`, `/discovery/{status,run,pause,resume,jobs,items}`, `/events`.
- 108 tests passing (96% coverage); docker-compose gains `worker` and `beat`.

### Fixed
- Feed descriptions with double-encoded HTML left tags in the text.
- Test hygiene: sessions always closed; cleanup uses a lock timeout so a failing test cannot hang the suite.


## [0.1.0] — 2026-11-14 — Phase 0 and Phase 1

### Phase 0 — audit and plan
- Audit: no existing repository, starter ZIPs or schema found; greenfield build.
- Architecture (modular monolith + workers), database design and ERD, STRIDE threat model, roadmap, testing and deployment strategy, initial cost model.
- Plan change: daily generation cap (default 10 events/day) because the cost model shows full processing of ~100 items/day exceeds the ₹5–8k budget.

### Phase 1 — SaaS foundation
- Tenants, users (human/service, platform admins), system roles and permission catalogue.
- Login with tenant slug, Argon2id passwords, account lockout, 15-min JWT access tokens, rotating refresh tokens with reuse detection, logout / logout everywhere, password change.
- TOTP MFA, mandatory for tenant and platform admins, with replay protection and encrypted secrets.
- Human-only permissions (`articles.approve`, `articles.publish`) enforced for service accounts and API keys.
- API keys: HMAC-hashed, scoped, expiring, rotatable, revocable.
- PostgreSQL row-level security on all tenant tables; separate owner and non-bypass app roles.
- Append-only audit log at the database-grant level.
- Alembic migration `0001`, bootstrap scripts, Dockerfile, docker-compose, `.env.example`, OpenAPI export.
- 51 tests against PostgreSQL (97% coverage); ruff and mypy clean.

### Fixed
- RLS bypass scope was closed before pending ORM writes were flushed, silently dropping updates.
