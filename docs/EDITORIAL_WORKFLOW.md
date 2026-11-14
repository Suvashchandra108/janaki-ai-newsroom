# Editorial Workflow

## Principle

The system assists journalists; it never replaces editorial responsibility. **No AI process, service account or API key can approve or publish an article.** This is enforced in the permission resolver (Phase 1) and will be enforced again by the workflow state machine (Phase 4/7).

## States

```mermaid
stateDiagram-v2
    [*] --> Discovered
    Discovered --> Researching
    Researching --> EvidenceAssessment
    EvidenceAssessment --> Generating: eligible + within daily cap
    EvidenceAssessment --> Archived: insufficient evidence / not newsworthy
    Generating --> Draft
    Generating --> Failed
    Draft --> NeedsReview
    NeedsReview --> Approved: human editor only
    NeedsReview --> NeedsCorrection
    NeedsReview --> Rejected
    NeedsCorrection --> NeedsReview
    Approved --> Published: human editor only
    Published --> NeedsCorrection: correction issued
    Published --> Archived
    Failed --> Generating: retry (limited)
```

Transitions marked *human editor only* require a human user holding `articles.approve` / `articles.publish`.

## Who can do what (system roles)

| Action | Tenant admin | Editor | Reviewer | Reporter | Service account / API key |
|---|---|---|---|---|---|
| Read events & evidence | ✓ | ✓ | ✓ | ✓ | scoped |
| Mark evidence editor-verified | ✓ | ✓ | ✓ | – | – |
| Create / edit drafts | ✓ | ✓ | – | ✓ | create only (scoped) |
| Reject / request correction | ✓ | ✓ | ✓ | – | – |
| Approve | ✓ | ✓ | – | – | **never** |
| Publish | ✓ | ✓ | – | – | **never** |
| Manage users, API keys | ✓ | – | – | – | **never** |

## Language

English only at launch (2 drafts per eligible event). When a tenant enables Nepali, each angle also gets a Nepali version and a fact/number consistency check between languages.

## Two-angle rule

For each eligible event the system proposes Article A (straight report) and Article B (context/impact). B is produced only if it cites evidence not used by A and passes a similarity threshold; otherwise one article is produced with the reason recorded on the event.

## How claims are verified (Phase 3)

1. The newsroom fetches each publisher's article (approved sites only, robots.txt respected).
2. The AI lists the key claims, and **must quote the sentence each claim comes from**. Claims whose quote is not in the article are discarded, as are numbers not in the quote.
3. Claims from different publishers are matched. Each publisher's article becomes evidence that **supports** or **contradicts** the claim (e.g. 2,000 vs 3,000 families).
4. Status is set by fixed rules, never by the AI:
   - **Corroborated** — 2 or more independent publishers support it, none contradict (copies of the same wire text count once);
   - **Conflicting evidence** — at least one publisher contradicts it;
   - **Insufficient evidence** — only one publisher;
   - **Editor verified** — a person confirmed it and wrote how (required note). Only people can do this, never API keys or service accounts.

## Claim categories shown to editors

Confirmed fact · Reported claim · Official statement · Allegation · Opinion · Estimate · Unverified. Each sentence in a draft links to the claims it relies on; sentences without evidence are highlighted.
