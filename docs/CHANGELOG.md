# Changelog

## [0.8.0] — 2026-11-15 — Phase 6: newsroom dashboard
- `frontend/`: Next.js 16 + TypeScript + Tailwind 4 dashboard, English and Nepali interface, desktop and phone.
- Screens: dashboard, news inbox, story research (facts, evidence, editor verification, photos), drafts, draft review (flags, cited facts with sources, edit → new version, regenerate, reject, send to website, photo licence, SEO/social, revision history, language tabs), jobs (failed jobs, run/pause discovery), sources, usage, website CMS, users, settings, two-factor enrolment.
- Security: server-side session (httpOnly cookies, no token in the browser), same-origin BFF with path allow-list, CSRF origin check, CSP.
- API: `GET /dashboard/summary`, `GET /dashboard/notifications`, status filters on events and jobs.
- Tests: 5 backend dashboard tests; 10 frontend unit tests; 14 browser tests against the real API and a seeded database (also in CI).
- Bugs found by the browser tests and fixed: redirects pointed at the server's internal host name; the phone menu stayed open after navigating; long unbroken text widened the page; buttons could be pressed before they worked.

## [0.7.0] — 2026-11-15 — Phase 7: delivery to the JanakiTelevision CMS
- `cms_connections` and `cms_deliveries` (migration `0006`, RLS); API key encrypted at rest, never returned.
- Payload REST client behind the SSRF guard (public https only, pinned DNS, no redirects, size cap); private hosts only with `CMS_ALLOW_PRIVATE_HOSTS` (refused in staging/production).
- Draft delivery: Lexical body, SEO/social/tags within the website's limits, section mapping, licensed hero photo upload, internal notes with flags, facts, claim statuses and source links; idempotent via `jn-<article id>`; temporary failures retried, rejections recorded.
- Status sync back (draft → published / removed); hourly tasks (delivery off by default, sync on).
- API: `GET/PUT /cms/connection`, `POST /cms/connection/check`, `POST /articles/{id}/deliver`, `GET /articles/{id}/delivery`, `POST /cms/sync`. Bootstrap: `cms-connect`.
- Website change (JanakiTelevision PR #1): draft-only API-key integration, tested there (115 integration tests) and end to end.
- 208 tests passing (+2 live end-to-end tests, run against the real website code locally).

## [0.5.0] — 2026-11-14 — Phase 5: visuals
- Writing checks tightened after the first live draft: unattributed single-source claims are warnings; cause-and-effect wording not present in sources is flagged (`unsupported_causal_link`).
- `media_assets` table (migration `0005`, RLS) with CHECK constraints: unlicensed images cannot be publishable or selected; AI images must carry the label.
- Wikimedia Commons adapter with licence classifier (CC0/PD/CC BY/CC BY-SA allowed; NC, ND, GFDL-only and unknown refused) and full provenance and attribution.
- Safe image download (approved hosts, size cap, image MIME types), Pillow validation (decompression bombs, formats), source copy plus WebP derivatives without metadata.
- Storage: local and S3-compatible backends with tenant-prefixed keys; authenticated file endpoint.
- Charts: bar charts from verified same-unit figures with source, date and methodology; escaped SVG.
- AI illustration interface: safe prompt builder, label, daily limit, photo-first rule (no provider configured yet).
- Editor API: search, list, select (download + derivatives), reject, chart, illustration, files.
- 186 tests passing; live Wikimedia Commons check added to CI.


## [0.4.0] — 2026-11-14 — Phase 4: English writing
- Approved source list (`deploy/feeds/approved.json`, 12 English sources) — weekly GitHub check now targets it.
- Tables `articles`, `article_versions` (migration `0004`, RLS; versions insert-only).
- Writing engine: eligibility gate, angle planner (A always, B only with distinct evidence), evidence-only prompts with numbered claims, paragraph-level claim citations, B discarded if too similar to A.
- Rule-based flags: uncited paragraph, unsupported number (body, headline, summary), unverified quote, conflicting claim, single-source claim. SEO/social limits match the website (70/170/280).
- Editor API: list/view, version history, edit (new version, re-checked), regenerate (limited), reject; human-only; `POST /events/{id}/write`.
- Hourly writing schedule (minute 40); usage recorded as `ai.angle_planning` / `ai.writing`; `AI_MODEL_WRITING` setting.
- Live Gemini writing test added to CI. 162 tests passing locally.


## [0.3.1] — 2026-11-14 — Decisions, live Gemini, proposed sources
- Live Gemini extraction verified in CI (free-tier key in the owner's account, stored as a GitHub secret).
- Decision: drafts will be delivered to the existing JanakiTelevision Payload CMS instead of building a new CMS (Phase 7 rescoped); field mapping documented in DEVELOPMENT_ROADMAP.md.
- Proposed English source list (`deploy/feeds/proposed_feeds.json`), feed checker (`scripts/check_feeds.py`) and weekly GitHub workflow; `bootstrap sources` import command (skips existing feeds).


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
