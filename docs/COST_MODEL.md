# Initial Cost Model — Janaki Television Pilot

## Update 14 Nov 2026 — English-first, free-tier-first

Decision: generate **English only** at launch (2 drafts per event instead of 4). At 10–15 events/day this needs roughly 100–150 AI calls/day, which fits free tiers reported in late 2026 (all to be re-checked at Phase 4, as free limits change without notice):

| Provider | Reported free allowance | Role |
|---|---|---|
| Google Gemini Flash-Lite | ~500 requests/day | extraction / writing candidate |
| Groq (open models) | ~1,000 requests/day | classification, extraction |
| OpenRouter free models | 50/day, 1,000/day after one-time $10 top-up | writing candidates, fallback |

Paid fallback when free quotas run out: a Flash-Lite-class model at roughly ₹3 per fully processed event (English, 2 drafts) ⇒ ~₹1,400/month even if every story were paid.

Revised monthly estimate: VPS ₹2,000–3,000 + storage ₹200–500 + AI ₹0–1,400 + search (TBD, free tier first) ⇒ **≈ ₹2,500–5,000**, inside the ₹5,000–8,000 budget.

Caveats: free tiers may use prompts for provider training (Gemini free tier does); acceptable for public news, not for embargoed material. Model choice for writing will be decided by a blind editor test in Phase 4.

The original bilingual model below is kept for when Nepali is enabled.

---

**All unit prices below are illustrative assumptions, not quotes.** Provider prices change often; the usage ledger (Phase 8) will replace these estimates with measured cost per event. Exchange rate assumed: ₹85 / USD.

## 1. Key finding

At "under 100 discovered items/day", the budget of ₹5,000–₹8,000/month **cannot** fund full research plus four drafts (2 angles × ne/en) for every item. Discovery is cheap; generation is not. The pipeline therefore needs an explicit **eligibility gate** and a daily **generation cap**.

Recommended pilot default: **10 fully processed events/day**, configurable per tenant, with everything else kept as discovered leads that editors can promote manually.

## 2. Pipeline cost per stage (per event)

| Stage | Model tier | Assumed tokens (in / out) | Notes |
|---|---|---|---|
| Classification + dedupe of ~5 items in cluster | economy | 5k / 0.5k | runs on every discovered item |
| Claim extraction | economy | 8k / 2k | |
| Corroboration (3 search queries + reading 3 pages) | economy | 12k / 1.5k | + search API calls |
| Angle planning + distinctness check | standard | 6k / 1k | decides 1 or 2 articles |
| Writing: 2 angles × 2 languages | standard | 4 × 6k / 4 × 1.5k | shared evidence pack is cacheable |
| Consistency check ne↔en | economy | 6k / 0.5k | |

Illustrative prices: economy ≈ $0.25 / $1.25 per M tokens (in/out); standard ≈ $3 / $15 per M tokens.

| | USD | INR |
|---|---|---|
| Economy stages per event | ≈ $0.015 | ≈ ₹1.3 |
| Standard stages per event (no caching) | ≈ $0.12 | ≈ ₹10 |
| **Total AI per fully processed event** | **≈ $0.14** | **≈ ₹12** |
| Classification of a lead that is *not* processed | ≈ $0.002 | ≈ ₹0.2 |

## 3. Monthly estimate (pilot defaults)

| Item | Assumption | ₹/month |
|---|---|---|
| VPS (India region, 4 vCPU / 8 GB) | API + workers + Postgres + Redis on one host | 2,000 – 3,000 |
| Object storage + backups | < 50 GB | 200 – 500 |
| AI — fully processed events | 10/day × 30 × ₹12 | ≈ 3,600 |
| AI — lead classification | 100/day × 30 × ₹0.2 | ≈ 600 |
| Search API | ~4 queries/event × 300 events, ~$5 per 1k queries | ≈ 500 |
| AI illustrations | capped at 3/day | 300 – 800 |
| Licensed photos | Wikimedia Commons first (free, attribution) | 0 (stock subscription extra) |
| **Total** | | **≈ ₹7,200 – ₹9,000** |

This sits at or slightly above the top of the budget. Levers, in order of impact:

1. Lower the daily generation cap (each event ≈ ₹12).
2. Generate the second angle only when the distinctness check passes (estimated 40–60% of events) — the planned default.
3. Prompt caching of the shared evidence pack across the four writing calls.
4. Use the economy tier for English drafts if editors rate quality acceptable (measure first).
5. Self-host Postgres/Redis on the same VPS (already assumed).

## 4. Guard rails built into the product

- Per-tenant monthly hard cap in ₹ (default ₹6,000 for AI + search); jobs that would exceed it are not enqueued and an admin is notified.
- Max regenerations per article (default 3), max illustrations per day (default 3).
- One-click pause of all paid operations.
- Cost per event / per article / per tenant reported on the dashboard from the usage ledger.

## 5. SaaS plan hypotheses (to validate)

Plans of ₹999 / ₹2,499 / ₹4,999 can only be profitable if their quotas are set from measured cost per event. Example: at ≈ ₹12/event, a ₹2,499 plan with 50% target gross margin supports ~100 fully processed events/month. Quotas will be finalised after 4 weeks of pilot data.
