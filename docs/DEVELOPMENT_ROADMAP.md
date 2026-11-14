# Development Roadmap

Each phase ends at a checkpoint: tests actually run, acceptance criteria reviewed, docs updated, CHANGELOG entry written. A phase does not start until the previous one has been accepted.

| Phase | Scope | Status |
|---|---|---|
| 0 | Repository audit, architecture, schema, threat model, roadmap, cost model | **Done (14 Nov 2026)** |
| 1 | SaaS foundation: tenants, users, RBAC, auth, sessions, MFA, API keys, RLS, audit, config | **Done — awaiting review** |
| 2 | Discovery: source registry, safe fetch (SSRF), RSS + search adapters, dedupe, clustering, hourly scheduler, quotas, job history | Next |
| 3 | Research & evidence: claims, evidence, corroboration, conflict detection, rule-based statuses, evidence review API | |
| 4 | AI gateway (OpenAI, Anthropic), two-angle bilingual generation, consistency checks, SEO/social fields, versioning, usage accounting | |
| 5 | Visuals: licensed image adapters, licence records, storage, optimisation, AI illustrations, charts | |
| 6 | Newsroom dashboard (Next.js, ne/en UI) | |
| 7 | CMS + public site, workflow, scheduling, idempotent publishing, Janaki TV migration plan (staging first) | |
| 8 | SaaS commercial: onboarding, plans, metering, quota enforcement, billing adapter, rate limiting | |
| 9 | Production deployment, backups + restore test, monitoring, security & load testing | |

## Changes from the master prompt (with reasons)

1. **Daily generation cap added (Phase 2/4).** The cost model shows full processing of ~100 items/day exceeds the budget. Discovery volume is unchanged; generation is capped (default 10 events/day, configurable). See COST_MODEL.md.
2. **Human-only permissions enforced in Phase 1**, not only in the UI. The "AI cannot approve/publish" rule is a security property, so it lives in the permission resolver from day one.
3. **Rate limiting split.** Per-account lockout ships in Phase 1; IP/token-bucket limiting ships with quota enforcement in Phase 8 (shared Redis infrastructure).
4. **Celery chosen over Dramatiq** for its built-in beat scheduler and wider operational tooling.

## Phase 2 tasks (next)

1. `news_sources` model + admin API (approved domains; no arbitrary URLs from non-admins).
2. `safe_fetch` service: DNS resolution, IP block-list (RFC1918, loopback, link-local, CGNAT, metadata, IPv6 equivalents), pinned connection, redirect re-validation (max 3), 10 s timeout, 2 MB cap, content-type allow-list. Unit tests with fake resolvers.
3. RSS adapter (feedparser) and one search adapter behind an interface; recorded fixtures for tests.
4. Ingestion + canonical URL normalisation + fingerprints; idempotent upsert.
5. Event clustering v1 (title SimHash + entity overlap + time window); pgvector embeddings as v2.
6. Celery app, beat schedule, per-tenant idempotency keys, retries with backoff, `background_jobs` history, pause/resume.
7. Daily discovery quota per tenant.

## Open questions for Janaki Television (not blocking Phase 2)

- List of approved RSS sources and preferred search provider.
- Access to the current website/CMS for the Phase 7 migration audit.
- Attribution policy for AI-assisted articles (byline wording in ne/en).
