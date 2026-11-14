"""Research & evidence pipeline for one event.

documents → grounded claims (AI) → cross-publisher matching (rules) → statuses (rules)
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import get_settings
from app.core.errors import AppError, NotFound
from app.core.principal import Principal
from app.modules.ai_gateway.gateway import AIError, LLMProvider, record_usage
from app.modules.audit import service as audit
from app.modules.discovery import service as discovery
from app.modules.discovery import text as dtext
from app.modules.discovery.models import BackgroundJob, DiscoveredItem, NewsEvent, NewsSource
from app.modules.discovery.safe_fetch import SafeFetcher
from app.modules.research import rules
from app.modules.research.claims import ExtractedClaim, extract_claims
from app.modules.research.documents import RobotsCache, get_or_fetch_document
from app.modules.research.models import Claim, Evidence, SourceDocument
from app.modules.tenancy.models import Tenant

CREDIBILITY_ORDER = {"high": 0, "medium": 1, "unknown": 2, "low": 3}


# --- selection & caps ---------------------------------------------------------------------


def daily_event_cap(tenant: Tenant) -> int:
    return int((tenant.settings.get("generation") or {}).get("daily_event_cap", 10))


def researched_today(db: Session, tenant: Tenant, now: datetime) -> int:
    start = discovery.tenant_day_start(tenant, now)
    return int(
        db.scalar(
            select(func.count())
            .select_from(BackgroundJob)
            .where(
                BackgroundJob.tenant_id == tenant.id,
                BackgroundJob.job_type == "research",
                BackgroundJob.created_at >= start,
                BackgroundJob.status.in_(("running", "succeeded", "partial", "failed")),
            )
        )
        or 0
    )


def events_due(db: Session, tenant: Tenant, now: datetime) -> list[NewsEvent]:
    """Most-reported recent events not yet researched, within today's remaining cap.

    Multi-publisher events come first: they are the ones that can be corroborated.
    """
    remaining = daily_event_cap(tenant) - researched_today(db, tenant, now)
    if remaining <= 0:
        return []
    since = now - timedelta(hours=get_settings().discovery_cluster_window_hours)
    return list(
        db.scalars(
            select(NewsEvent)
            .where(
                NewsEvent.tenant_id == tenant.id,
                NewsEvent.status == "discovered",
                NewsEvent.last_seen_at >= since,
            )
            .order_by(NewsEvent.publisher_count.desc(), NewsEvent.last_seen_at.desc())
            .limit(remaining)
        )
    )


# --- claim merging --------------------------------------------------------------------------


def _merge_claim(
    db: Session,
    *,
    event: NewsEvent,
    existing: list[Claim],
    extracted: ExtractedClaim,
    item: DiscoveredItem,
    doc: SourceDocument,
    now: datetime,
    stats: Counter[str],
) -> None:
    kw = rules.claim_keywords(extracted.text)
    match = next((c for c in existing if rules.same_claim(kw, c.keywords)), None)
    relationship = "supports"
    if match is None:
        match = Claim(
            tenant_id=event.tenant_id,
            event_id=event.id,
            text=extracted.text[:1000],
            fingerprint=dtext.sha256(" ".join(kw) or extracted.text.lower()),
            claim_type=extracted.claim_type,
            keywords=kw,
            entities=extracted.entities,
            numbers=extracted.numbers,
            dates=extracted.dates,
            status="researching",
        )
        db.add(match)
        db.flush()
        existing.append(match)
        stats["claims_new"] += 1
    elif rules.numbers_conflict(list(match.numbers), extracted.numbers):
        relationship = "contradicts"
        stats["conflicts_found"] += 1
    already = db.scalar(
        select(Evidence.id).where(
            Evidence.claim_id == match.id,
            Evidence.item_id == item.id,
            Evidence.relationship == relationship,
        )
    )
    if already:
        return
    db.add(
        Evidence(
            tenant_id=event.tenant_id,
            claim_id=match.id,
            item_id=item.id,
            document_id=doc.id,
            url=item.url,
            publisher_domain=item.publisher_domain,
            published_at=item.published_at,
            retrieved_at=doc.fetched_at,
            excerpt=extracted.excerpt[:600],
            evidence_type="official_statement"
            if extracted.claim_type == "official"
            else "news_report",
            relationship=relationship,
            content_hash=doc.text_hash,
        )
    )
    db.flush()
    stats["evidence_added"] += 1


def recompute_statuses(db: Session, event_id: uuid.UUID) -> dict[str, int]:
    db.flush()  # autoflush is off: pending evidence must be visible to the queries below
    counts: Counter[str] = Counter()
    for claim in db.scalars(select(Claim).where(Claim.event_id == event_id)):
        ev = [
            rules.EvidenceView(e.relationship, e.publisher_domain, e.content_hash)
            for e in db.scalars(select(Evidence).where(Evidence.claim_id == claim.id))
        ]
        claim.status, claim.status_reason, claim.independent_sources = rules.compute_status(
            claim.status, ev
        )
        counts[claim.status] += 1
    db.flush()
    return dict(counts)


# --- the research run ----------------------------------------------------------------------


def run_research(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    idempotency_key: str,
    trigger: str,
    fetcher: SafeFetcher,
    llm: LLMProvider | None,
    now: datetime | None = None,
) -> BackgroundJob | None:
    """Research one event. Caller sets the tenant context and commits."""
    now = now or security.utcnow()
    s = get_settings()
    job = discovery.claim_job(db, tenant_id, idempotency_key, trigger, job_type="research")
    if job is None:
        return None
    job.attempts += 1
    job.started_at = now
    job.status = "running"
    job.error = None
    event = db.scalar(
        select(NewsEvent).where(NewsEvent.id == event_id, NewsEvent.tenant_id == tenant_id)
    )
    if event is None:
        return discovery.finish_job(
            job, "skipped", {"reason": "event_not_found", "event_id": str(event_id)}
        )
    event.status = "researching"
    db.flush()

    rows = list(
        db.execute(
            select(DiscoveredItem, NewsSource)
            .join(NewsSource, NewsSource.id == DiscoveredItem.source_id)
            .where(DiscoveredItem.event_id == event.id)
        ).all()
    )
    # One article per publisher first (independence), most credible sources first.
    rows.sort(key=lambda r: (CREDIBILITY_ORDER.get(r[1].credibility, 2), -r[1].priority))
    chosen, seen_domains = [], set()
    for item, source in rows:
        if item.publisher_domain not in seen_domains:
            chosen.append((item, source))
            seen_domains.add(item.publisher_domain)
    chosen = chosen[: s.research_max_documents_per_event]

    robots = RobotsCache(fetcher)
    existing = list(db.scalars(select(Claim).where(Claim.event_id == event.id)))
    stats: Counter[str] = Counter()
    documents: list[dict[str, Any]] = []
    ai_error: AIError | None = None
    for item, source in chosen:
        doc = get_or_fetch_document(
            db, item=item, source=source, fetcher=fetcher, robots=robots, now=now
        )
        documents.append(
            {
                "item_id": str(item.id),
                "domain": item.publisher_domain,
                "status": doc.status,
                "error": doc.error,
            }
        )
        stats[f"documents_{doc.status}"] += 1
        if doc.status != "fetched" or doc.claims_extracted_at is not None or ai_error:
            continue
        if llm is None:
            stats["documents_awaiting_ai"] += 1
            continue
        try:
            extracted, result = extract_claims(
                llm,
                headline=event.title,
                article=doc.text or "",
                max_claims=s.research_max_claims_per_document,
            )
        except AIError as exc:
            ai_error = exc
            continue
        record_usage(
            db, tenant_id=tenant_id, kind="ai.claim_extraction", result=result, job_id=job.id
        )
        stats["ai_calls"] += 1
        stats["input_tokens"] += result.input_tokens
        stats["output_tokens"] += result.output_tokens
        doc.claims_extracted_at = now
        for c in extracted:
            _merge_claim(
                db,
                event=event,
                existing=existing,
                extracted=c,
                item=item,
                doc=doc,
                now=now,
                stats=stats,
            )

    status_counts = recompute_statuses(db, event.id)
    result_data: dict[str, Any] = {
        "event_id": str(event.id),
        **stats,
        "claim_statuses": status_counts,
        "documents": documents[:20],
    }
    if ai_error is not None:
        result_data["ai_error"] = ai_error.code
        job.error = ai_error.message
        # Retryable (quota/network): "failed" lets the same job resume later; documents already
        # processed are skipped, so no quota is spent twice. Permanent errors stay partial.
        status = "failed" if ai_error.retryable or not stats["ai_calls"] else "partial"
    elif llm is None and stats["documents_awaiting_ai"]:
        result_data["ai_error"] = "not_configured"
        job.error = "No AI provider configured; documents fetched but claims not extracted"
        status = "partial"
    elif stats["documents_fetched"] == 0:
        status = "failed"
        job.error = "No article could be retrieved"
    else:
        status = "succeeded"
    event.status = "evidence_assessment" if status in ("succeeded", "partial") else "discovered"
    return discovery.finish_job(job, status, result_data)


def research_key(event_id: uuid.UUID, now: datetime) -> str:
    return f"research:{event_id}:{now.strftime('%Y-%m-%d')}"


# --- editor review --------------------------------------------------------------------------


def get_claim(db: Session, principal: Principal, claim_id: uuid.UUID) -> Claim:
    claim = db.scalar(
        select(Claim).where(Claim.id == claim_id, Claim.tenant_id == principal.tenant_id)
    )
    if claim is None:
        raise NotFound("Claim not found.")
    return claim


def review_claim(
    db: Session, principal: Principal, claim_id: uuid.UUID, *, verified: bool, note: str | None
) -> Claim:
    if principal.kind != "user" or principal.is_service:
        raise AppError("Only a person can verify a claim.", code="human_only", status_code=403)
    claim = get_claim(db, principal, claim_id)
    if verified and not (note and note.strip()):
        raise AppError(
            "Explain how you verified this claim (note is required).",
            code="note_required",
            status_code=422,
        )
    claim.status = "editor_verified" if verified else "researching"
    claim.editor_note = note.strip()[:2000] if note else None
    claim.reviewed_by = principal.user_id
    claim.reviewed_at = security.utcnow()
    db.flush()
    recompute_statuses(db, claim.event_id)
    audit.record(
        db,
        principal=principal,
        action="claim.verified" if verified else "claim.verification_removed",
        tenant_id=principal.tenant_id,
        target_type="claim",
        target_id=claim.id,
    )
    return claim
