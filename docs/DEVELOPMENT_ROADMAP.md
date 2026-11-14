# Development Roadmap

Each phase ends at a checkpoint: tests actually run, acceptance criteria reviewed, docs updated, CHANGELOG entry written. A phase does not start until the previous one has been accepted.

| Phase | Scope | Status |
|---|---|---|
| 0 | Repository audit, architecture, schema, threat model, roadmap, cost model | **Done (14 Nov 2026)** |
| 1 | SaaS foundation: tenants, users, RBAC, auth, sessions, MFA, API keys, RLS, audit, config | **Done (14 Nov 2026)** |
| 2 | Discovery: source registry, safe fetch (SSRF), RSS + search adapter interface, dedupe, clustering, hourly scheduler, quotas, job history | **Done — verified in CI (14 Nov 2026)** |
| 3 | Research & evidence: article retrieval (robots.txt), grounded claim extraction, corroboration, conflict detection, rule-based statuses, evidence review API, usage ledger | **Done — verified in CI (14 Nov 2026), awaiting review** |
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

## Phase 4 tasks (next) — English writing

1. Writing model settings (`AI_MODEL_WRITING`), same gateway; blind editor test of 2–3 free models on 5 real stories before choosing.
2. Eligibility gate: only events whose key claims are corroborated or editor-verified are written; conflicting claims must be presented as conflicting.
3. Angle planner: Article A (straight report) always; Article B (context/impact) only if it can cite evidence A does not use; otherwise record why not.
4. Drafts cite claim IDs per paragraph; sentences without a claim are flagged for the editor.
5. Headline, alternative headline, slug, summary, caption, SEO title/description, keywords, social captions.
6. `articles`, `article_versions` tables; AI can create drafts only (human-only approve/publish already enforced).
7. Regeneration limit and usage accounting per article.

## Decision needed before Phase 7

The existing **JanakiTelevision** repository already contains a tested Next.js + Payload CMS website with an editorial workflow (not yet deployed). Recommended: the newsroom delivers English drafts into that CMS as unpublished drafts via an API, instead of building a second CMS. Awaiting product-owner decision.

## Phase 3 notes

- Claims must quote the article verbatim; ungrounded claims and numbers are discarded before storage.
- Verification status is computed by fixed rules from evidence (2+ independent publishers ⇒ corroborated; any contradiction ⇒ conflicting; otherwise insufficient). Syndicated copies count once.
- Claim matching across publishers is keyword-based (v1); claims phrased very differently may appear as separate claims. Embedding-based matching can follow.
- Article text is stored for internal research only; a retention/purge job is still to be added (Phase 9).
- Real AI calls are not yet verified: no API key has been configured. Adapters are tested against recorded response shapes.

## Phase 2 notes

- Search: provider interface and approved-publisher filtering are built; **no concrete search provider is wired yet**. Free-tier providers will be evaluated before Phase 3 research needs them.
- Clustering v1 is keyword + SimHash with light stemming, English-tuned. Embedding-based clustering comes with the AI gateway.
- Category/region come from the source's settings; AI classification arrives with the gateway.

## Open questions for Janaki Television (not blocking Phase 3)

- List of approved English RSS sources (Nepal, Madhesh, India, international) and preferred search provider.
- Access to the current website/CMS for the Phase 7 migration audit.
- Attribution policy for AI-assisted articles (byline wording in ne/en).
