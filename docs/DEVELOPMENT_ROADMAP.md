# Development Roadmap

Each phase ends at a checkpoint: tests actually run, acceptance criteria reviewed, docs updated, CHANGELOG entry written. A phase does not start until the previous one has been accepted.

| Phase | Scope | Status |
|---|---|---|
| 0 | Repository audit, architecture, schema, threat model, roadmap, cost model | **Done (14 Nov 2026)** |
| 1 | SaaS foundation: tenants, users, RBAC, auth, sessions, MFA, API keys, RLS, audit, config | **Done (14 Nov 2026)** |
| 2 | Discovery: source registry, safe fetch (SSRF), RSS + search adapter interface, dedupe, clustering, hourly scheduler, quotas, job history | **Done — verified in CI (14 Nov 2026)** |
| 3 | Research & evidence: article retrieval (robots.txt), grounded claim extraction, corroboration, conflict detection, rule-based statuses, evidence review API, usage ledger | **Done — verified in CI (14 Nov 2026), awaiting review** |
| 4 | Two-angle **English** writing from checked claims, paragraph citations, fabrication flags, SEO/social fields, immutable versions, editor edit/regenerate/reject, usage accounting. Nepali + consistency checks when enabled | **Done — awaiting review** |
| 5 | Visuals: Wikimedia Commons (licence-first), licence classifier, DB-enforced publishable rules, safe download, Pillow derivatives, local/S3 storage, charts from verified figures, AI-illustration interface with mandatory label, editor selection | **Done — awaiting review** |
| 6 | Newsroom dashboard (Next.js, ne/en UI) | **Done — browser-tested against the real API (15 Nov 2026)** |
| 7 | **CMS connector** to the existing JanakiTelevision website (Payload CMS): deliver English drafts as unpublished `draft` articles through a draft-only API-key integration; idempotent delivery; status sync back (decision 14 Nov 2026 — replaces building a new CMS) | **Done — verified end to end against the real website code (15 Nov 2026); website change awaiting review (JanakiTelevision PR #1)** |
| 8 | SaaS commercial: onboarding, plans, metering, quota enforcement, billing adapter, rate limiting | |
| 9 | Production deployment, backups + restore test, monitoring, security & load testing | |

## Changes from the master prompt (with reasons)

0. **English-first launch (decision by product owner, 14 Nov 2026).** Articles are generated in English only: 2 drafts per eligible event (Article A + Article B) instead of 4. Nepali stays in the data model and is enabled per tenant later (`settings.languages`). Reason: free AI tiers can cover 10–15 stories/day in English, while free-model Nepali quality is unproven.

1. **Daily generation cap added (Phase 2/4).** The cost model shows full processing of ~100 items/day exceeds the budget. Discovery volume is unchanged; generation is capped (default 10 events/day, configurable). See COST_MODEL.md.
2. **Human-only permissions enforced in Phase 1**, not only in the UI. The "AI cannot approve/publish" rule is a security property, so it lives in the permission resolver from day one.
3. **Rate limiting split.** Per-account lockout ships in Phase 1; IP/token-bucket limiting ships with quota enforcement in Phase 8 (shared Redis infrastructure).
4. **Celery chosen over Dramatiq** for its built-in beat scheduler and wider operational tooling.

## Next steps (status 16 Nov 2026)

**Go-live of website delivery — in progress.**

- Done: JanakiTelevision PR #1 merged (15 Nov) and **live** on janakitelevision.com (`/api/integrations/me` answers). The website runs on AWS EC2 `janaki-tv-1`, Mumbai (35.154.72.14, 2 GB — too small to share); DNS at Namecheap.
- Done: newsroom production kit in `deploy/` (install, connect-website, update, backup), proven by CI job `deploy-smoke`.
- Hetzner abandoned: its sign-up looped on the bot check. **Decision 16 Nov: newsroom on its own AWS EC2 server in Mumbai.**
- Next session:
  1. Owner signs in to the AWS console.
  2. Launch EC2 `janaki-newsroom`: Ubuntu 24.04, t3.small, 25 GB gp3, security group 22/80/443. Owner confirms AWS's price first.
  3. Run `deploy/install.sh` through EC2 Instance Connect. Owner types the Gemini key and the admin password. The private repo is cloned with a read-only deploy key.
  4. Namecheap A record `newsroom` → the instance's public IP. Elastic IP recommended, so the address survives restarts.
  5. Owner creates the website integration "AI newsroom" (key kept private), then runs `bash deploy/connect-website.sh`. Automatic hourly delivery is on (owner's choice).
  6. Check that the first draft arrives in the website's English drafts.
- Later: Phase 8 or 9, pin the Gemini model id.

## Phase 6 notes

- Approve/publish buttons are deliberately absent: approval and publication happen in the website CMS (decision 14 Nov 2026). The review screen has **Send to website as draft** instead, and says so.
- Language tabs: English is active; the Nepali tab is shown disabled until Nepali drafts are enabled.
- Spending: tokens and calls are exact; money is not shown because no price list is configured (no invented figures).
- Notifications are an activity feed derived from existing records (no notification table, no email/push yet).
- Theme: `tenants.settings.theme.primary` / `.accent` (hex only).
- Not built yet: infographics editor, categories screen, API-key management screen, billing.

## Phase 7 notes

- Website side (JanakiTelevision, branch `newsroom-bot-drafts`): an `integrations` collection — API key only, not staff, created inactive. It may create **draft** articles (forced `aiAssisted`, unique `newsroomRef`, no byline/sponsorship/publication fields) and upload photos; it cannot edit, delete, publish or list anything else. Enforced in the website's collection access and hooks, not in the newsroom.
- Newsroom side: `cms_connections` (encrypted key, one per tenant) and `cms_deliveries` (migration `0006`, RLS). Delivery is idempotent: reference `jn-<article id>` is looked up in the CMS before creating, so a retry after a timeout cannot make a duplicate. One delivery per article (the integration cannot edit, so revised versions are not re-sent; the editor edits in the CMS).
- What is sent: headline, summary, body (Lexical), language, tags, SEO and social text, slug (newsroom slug + 6-character code from the article id, so it does not clash with existing website stories), section (connection mapping, else matched by slug, else left for the editor), the selected licensed hero photo (largest WebP derivative, licence in the photo's internal usage notes) and **internal notes**: warning flags to resolve, alternative headline, every fact used with its claim status and source links, photo licence. Byline is never sent.
- Articles with status `draft` or `needs_review` can be delivered; `rejected` never. Automatic hourly delivery (:50) is **off by default** per tenant; status sync runs hourly (:55) for 30 days after delivery (draft → … → published, or removed).
- The CMS address goes through the SSRF guard (public addresses only, https, no redirects); private addresses only with `CMS_ALLOW_PRIVATE_HOSTS`, refused in staging/production.
- The live end-to-end test found two real problems that fakes could not: the integration could not read its own record (`/api/integrations/me`), and repeated headlines produced a slug clash. Both fixed.

## Phase 5 notes

- Licence-first: Wikimedia Commons only for now. Commercial stock providers need accounts and contracts (decision for the owner).
- Publishable = recognised licence + commercial use + modification (resizing) allowed + licence URL + attribution text when required. Enforced again by database CHECK constraints; selection requires publishable (also a constraint).
- Download happens only when an editor selects an image; the ~1600px rendition is fetched, never the full original. Source copy kept; WebP derivatives are proportional resizes with metadata stripped.
- Charts: bar charts only, from ≥2 corroborated/editor-verified figures in the same unit, with sources, date and methodology on the image; SVG labels escaped.
- AI illustrations: interface, prompt rules (place and section only, no people, no text) and labelling are built and DB-enforced; **no image-generation provider is configured** (API returns 503). Daily limit default 3; only after licensed photos have been reviewed.
- Restrictions from Commons (e.g. personality rights) are shown to editors but do not block use.

## Phase 4 notes

- Eligibility: an event is written only after research, and only if at least one claim is corroborated or editor-verified. Single-source claims may be used only with attribution; conflicting claims must be presented as disputed.
- Three AI calls per event (plan, Article A, optional Article B). B is written only if the plan gives it claims A does not use (overlap < 70%) and is discarded if its text overlaps A by more than 60%.
- Every paragraph cites claim IDs. Rule-based flags: uncited paragraph, unsupported number (incl. headline/summary), unverified quote, conflicting claim, single-source claim (info). Warnings set status `needs_review`.
- Versions are immutable (DB grant: INSERT/SELECT only). Editor edits and regenerations create new versions; regeneration limited per tenant (default 3). Only people can edit/regenerate/reject.
- Approval and publishing are not done here: they happen in the website CMS after delivery (Phase 7).

## Decisions (14 Nov 2026, product owner)

1. **No second CMS.** Drafts go into the existing **JanakiTelevision** website (Next.js + Payload CMS, separate repository), where Janaki editors review, approve and publish with their existing workflow. The newsroom keeps its own records (events, claims, evidence, article versions) and delivers each draft once.
2. **Starting source list:** Claude proposes English RSS sources (`deploy/feeds/proposed_feeds.json`), checked automatically from GitHub (`.github/workflows/feeds.yml`); the owner approves the final list before import.

### Planned draft → website field mapping (Payload `articles` collection)

| Newsroom (Phase 4) | Website field | Limit / rule |
|---|---|---|
| headline | `title` | |
| slug | `slug` | + `-<6 chars of article id>` (website slugs are unique) |
| summary | `summary` | needed to publish |
| body paragraphs | `body` (Lexical rich text) | converted at delivery |
| language `en` | `language` | |
| category slug | `categories` | website section slugs (politics, news, business, international, sports, health …) |
| keywords | `tags` | max 15 |
| SEO title / description | `seo.title` / `seo.description` | ≤ 70 / ≤ 170 chars |
| social headline / summary | `distribution.socialHeadline` / `socialSummary` | ≤ 120 / ≤ 280 chars |
| — | `aiAssisted` | always `true` |
| — | `status` | always `draft`; the newsroom never sets inReview/approved/published |
| sources, claim statuses, alternative headline, angle | `editorialNotes` | internal only, never published |

Implemented in Phase 7 with one change: instead of a reporter-role user, the website has a separate **integration** account type with narrower rights (drafts and photos only), and the slug gets a short suffix. See Phase 7 notes.

## Phase 3 notes

- Claims must quote the article verbatim; ungrounded claims and numbers are discarded before storage.
- Verification status is computed by fixed rules from evidence (2+ independent publishers ⇒ corroborated; any contradiction ⇒ conflicting; otherwise insufficient). Syndicated copies count once.
- Claim matching across publishers is keyword-based (v1); claims phrased very differently may appear as separate claims. Embedding-based matching can follow.
- Article text is stored for internal research only; a retention/purge job is still to be added (Phase 9).
- Real Gemini call verified in CI (14 Nov 2026, free-tier key in the owner's account). Before production, pin a specific model id (`AI_MODEL_EXTRACTION` / CI variable `GEMINI_MODEL`) instead of the `-latest` alias, so behaviour does not change silently.

## Phase 2 notes

- Search: provider interface and approved-publisher filtering are built; **no concrete search provider is wired yet**. Free-tier providers will be evaluated before Phase 3 research needs them.
- Clustering v1 is keyword + SimHash with light stemming, English-tuned. Embedding-based clustering comes with the AI gateway.
- Category/region come from the source's settings; AI classification arrives with the gateway.

## Open questions for Janaki Television (not blocking Phase 3)

- List of approved English RSS sources (Nepal, Madhesh, India, international) and preferred search provider.
- Access to the current website/CMS for the Phase 7 migration audit.
- Attribution policy for AI-assisted articles (byline wording in ne/en).
