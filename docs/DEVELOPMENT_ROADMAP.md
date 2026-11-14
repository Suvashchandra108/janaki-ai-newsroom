# Development Roadmap

Each phase ends at a checkpoint: tests actually run, acceptance criteria reviewed, docs updated, CHANGELOG entry written. A phase does not start until the previous one has been accepted.

| Phase | Scope | Status |
|---|---|---|
| 0 | Repository audit, architecture, schema, threat model, roadmap, cost model | **Done (14 Nov 2026)** |
| 1 | SaaS foundation: tenants, users, RBAC, auth, sessions, MFA, API keys, RLS, audit, config | **Done (14 Nov 2026)** |
| 2 | Discovery: source registry, safe fetch (SSRF), RSS + search adapter interface, dedupe, clustering, hourly scheduler, quotas, job history | **Done — verified in CI (14 Nov 2026)** |
| 3 | Research & evidence: claims, evidence, corroboration, conflict detection, rule-based statuses, evidence review API | In progress |
| 4 | AI gateway (free-tier first: Gemini, Groq, OpenRouter; plus OpenAI, Anthropic), two-angle **English** generation, SEO/social fields, versioning, usage accounting. Nepali + consistency checks when enabled | |
| 5 | Visuals: licensed image adapters, licence records, storage, optimisation, AI illustrations, charts | |
| 6 | Newsroom dashboard (Next.js, ne/en UI) | |
| 7 | CMS + public site, workflow, scheduling, idempotent publishing, Janaki TV migration plan (staging first) | |
| 8 | SaaS commercial: onboarding, plans, metering, quota enforcement, billing adapter, rate limiting | |
| 9 | Production deployment, backups + restore test, monitoring, security & load testing | |

## Changes from the master prompt (with reasons)

0. **English-first launch (decision by product owner, 14 Nov 2026).** Articles are generated in English only: 2 drafts per eligible event (Article A + Article B) instead of 4. Nepali stays in the data model and is enabled per tenant later (`settings.languages`). Reason: free AI tiers can cover 10–15 stories/day in English, while free-model Nepali quality is unproven.

1. **Daily generation cap added (Phase 2/4).** The cost model shows full processing of ~100 items/day exceeds the budget. Discovery volume is unchanged; generation is capped (default 10 events/day, configurable). See COST_MODEL.md.
2. **Human-only permissions enforced in Phase 1**, not only in the UI. The "AI cannot approve/publish" rule is a security property, so it lives in the permission resolver from day one.
3. **Rate limiting split.** Per-account lockout ships in Phase 1; IP/token-bucket limiting ships with quota enforcement in Phase 8 (shared Redis infrastructure).
4. **Celery chosen over Dramatiq** for its built-in beat scheduler and wider operational tooling.

## Phase 3 tasks (next)

1. `claims`, `evidence`, `claim_evidence` tables (tenant-scoped, RLS).
2. Article-page fetching through `SafeFetcher` (publisher domain must be approved) and main-text extraction.
3. Claim extraction behind a small AI-gateway interface (free-tier model, strict JSON schema, output validation). The full gateway arrives in Phase 4; Phase 3 uses the same interface.
4. Corroboration: match claims across items in the same event from *independent* publishers; flag conflicting numbers/dates/names.
5. Rule-based verification status (never model confidence) and claim types (fact, reported, official, allegation, opinion, estimate, unverified).
6. Evidence review API for editors (mark editor-verified, add notes), with audit.
7. Prompt-injection defences: source text passed as delimited data; no tools; schema validation.

## Phase 2 notes

- Search: provider interface and approved-publisher filtering are built; **no concrete search provider is wired yet**. Free-tier providers will be evaluated before Phase 3 research needs them.
- Clustering v1 is keyword + SimHash with light stemming, English-tuned. Embedding-based clustering comes with the AI gateway.
- Category/region come from the source's settings; AI classification arrives with the gateway.

## Open questions for Janaki Television (not blocking Phase 3)

- List of approved English RSS sources (Nepal, Madhesh, India, international) and preferred search provider.
- Access to the current website/CMS for the Phase 7 migration audit.
- Attribution policy for AI-assisted articles (byline wording in ne/en).
