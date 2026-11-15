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

**With the JanakiTelevision website (Phase 7):** review, approval and publication happen in the website CMS, not here. The newsroom delivers a draft (newsroom status becomes `delivered`), the website keeps it as an unpublished *Draft* marked *AI suggestion used*, and a Janaki editor checks the internal notes (flags, facts and sources), adds byline and section, and publishes. The newsroom only reads the result back (`remote_status`). Rejected articles are never delivered.

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

## How drafts are written (Phase 4, English)

1. A story is written only after research, and only if at least one claim is **corroborated** or **editor-verified**.
2. The AI receives only the numbered checked claims and must cite them in every paragraph. Single-source claims must be attributed; conflicting claims must be presented as disputed.
3. **Article A** (straight report) is always written. **Article B** (context/impact) is written only if there is evidence A does not use, and is discarded if it turns out too similar to A. The reason is recorded either way.
4. Automatic checks flag, for the editor: paragraphs with no claim, numbers not found in the cited claims (also in headline/summary), quotes not found in any source, and reliance on conflicting or single-source claims. Any warning puts the draft in **Needs review**.
5. Editors can edit (each save is a new version), regenerate (limited, default 3 times) or reject. Old versions can always be viewed and never change.
6. Approval and publication happen in the Janaki Television website CMS, after delivery.

## Claim categories shown to editors

Confirmed fact · Reported claim · Official statement · Allegation · Opinion · Estimate · Unverified. Each sentence in a draft links to the claims it relies on; sentences without evidence are highlighted.
