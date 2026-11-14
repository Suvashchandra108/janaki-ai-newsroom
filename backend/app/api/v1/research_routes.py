"""Phase 3 API: claims, evidence, research status, editor review, AI usage."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require
from app.core import security
from app.core.errors import AppError, NotFound
from app.core.permissions import P
from app.core.principal import Principal
from app.db.session import get_db
from app.modules.ai_gateway.models import UsageRecord
from app.modules.audit import service as audit
from app.modules.discovery.models import BackgroundJob, DiscoveredItem, NewsEvent
from app.modules.research import service as research
from app.modules.research.models import Claim, Evidence, SourceDocument

router = APIRouter(tags=["research"])


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class EvidenceOut(ORM):
    id: uuid.UUID
    url: str
    publisher_domain: str
    published_at: datetime | None
    retrieved_at: datetime
    excerpt: str
    evidence_type: str
    relationship: str


class ClaimOut(ORM):
    id: uuid.UUID
    event_id: uuid.UUID
    text: str
    claim_type: str
    entities: list[str]
    numbers: list[dict[str, Any]]
    dates: list[str]
    status: str
    status_reason: str | None
    independent_sources: int
    editor_note: str | None
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    evidence: list[EvidenceOut] = []


class DocumentOut(BaseModel):
    item_id: uuid.UUID
    url: str
    publisher_domain: str
    status: str | None
    error: str | None
    claims_extracted: bool


class ResearchOut(BaseModel):
    event_id: uuid.UUID
    event_status: str
    claim_statuses: dict[str, int]
    documents: list[DocumentOut]
    last_job_status: str | None
    last_job_error: str | None


class ReviewIn(BaseModel):
    verified: bool
    note: str | None = Field(default=None, max_length=2000)


class RunOut(BaseModel):
    idempotency_key: str
    status: str = "queued"


class UsageOut(BaseModel):
    days: int
    ai_calls: int
    input_tokens: int
    output_tokens: int
    by_kind: dict[str, int]


def _event(db: Session, principal: Principal, event_id: uuid.UUID) -> NewsEvent:
    ev = db.scalar(
        select(NewsEvent).where(
            NewsEvent.id == event_id, NewsEvent.tenant_id == principal.tenant_id
        )
    )
    if ev is None:
        raise NotFound("Event not found.")
    return ev


def _claim_out(db: Session, claim: Claim) -> ClaimOut:
    out = ClaimOut.model_validate(claim)
    out.evidence = [
        EvidenceOut.model_validate(e)
        for e in db.scalars(
            select(Evidence)
            .where(Evidence.claim_id == claim.id)
            .order_by(Evidence.relationship, Evidence.publisher_domain)
        )
    ]
    return out


@router.get("/events/{event_id}/claims", response_model=list[ClaimOut])
def event_claims(
    event_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.EVENTS_READ)),
) -> list[ClaimOut]:
    ev = _event(db, principal, event_id)
    claims = db.scalars(
        select(Claim)
        .where(Claim.event_id == ev.id)
        .order_by(Claim.independent_sources.desc(), Claim.created_at)
    )
    return [_claim_out(db, c) for c in claims]


@router.get("/events/{event_id}/research", response_model=ResearchOut)
def event_research(
    event_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.EVENTS_READ)),
) -> ResearchOut:
    ev = _event(db, principal, event_id)
    rows = db.execute(
        select(DiscoveredItem, SourceDocument)
        .outerjoin(SourceDocument, SourceDocument.item_id == DiscoveredItem.id)
        .where(DiscoveredItem.event_id == ev.id)
    ).all()
    docs = [
        DocumentOut(
            item_id=i.id,
            url=i.url,
            publisher_domain=i.publisher_domain,
            status=d.status if d else None,
            error=d.error if d else None,
            claims_extracted=bool(d and d.claims_extracted_at),
        )
        for i, d in rows
    ]
    counts = dict(
        db.execute(
            select(Claim.status, func.count()).where(Claim.event_id == ev.id).group_by(Claim.status)
        )
        .tuples()
        .all()
    )
    job = db.scalar(
        select(BackgroundJob)
        .where(
            BackgroundJob.tenant_id == principal.tenant_id,
            BackgroundJob.job_type == "research",
            BackgroundJob.result["event_id"].astext == str(ev.id),
        )
        .order_by(BackgroundJob.created_at.desc())
        .limit(1)
    )
    return ResearchOut(
        event_id=ev.id,
        event_status=ev.status,
        claim_statuses=counts,
        documents=docs,
        last_job_status=job.status if job else None,
        last_job_error=job.error if job else None,
    )


@router.post(
    "/events/{event_id}/research", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED
)
def run_research(
    event_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.DISCOVERY_RUN)),
) -> RunOut:
    from app import worker  # local import keeps the API importable without a broker

    ev = _event(db, principal, event_id)
    assert principal.tenant_id
    try:
        key = worker.enqueue_research(principal.tenant_id, ev.id)
    except Exception as exc:
        raise AppError(
            "The job queue is unavailable. Try again shortly.",
            code="queue_unavailable",
            status_code=503,
        ) from exc
    audit.record(
        db,
        principal=principal,
        action="research.run_requested",
        tenant_id=principal.tenant_id,
        target_type="news_event",
        target_id=ev.id,
    )
    return RunOut(idempotency_key=key)


@router.get("/claims/{claim_id}", response_model=ClaimOut)
def get_claim(
    claim_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.EVENTS_READ)),
) -> ClaimOut:
    return _claim_out(db, research.get_claim(db, principal, claim_id))


@router.post("/claims/{claim_id}/review", response_model=ClaimOut)
def review_claim(
    claim_id: uuid.UUID,
    body: ReviewIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.EVIDENCE_REVIEW)),
) -> ClaimOut:
    claim = research.review_claim(db, principal, claim_id, verified=body.verified, note=body.note)
    return _claim_out(db, claim)


@router.get("/usage/ai", response_model=UsageOut)
def ai_usage(
    days: int = Query(default=30, ge=1, le=366),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.USAGE_READ)),
) -> UsageOut:
    since = security.utcnow() - timedelta(days=days)
    rows = db.execute(
        select(
            UsageRecord.kind,
            func.count(),
            func.sum(UsageRecord.input_tokens),
            func.sum(UsageRecord.output_tokens),
        )
        .where(
            UsageRecord.tenant_id == principal.tenant_id,
            UsageRecord.created_at >= since,
        )
        .group_by(UsageRecord.kind)
    ).all()
    return UsageOut(
        days=days,
        ai_calls=sum(r[1] for r in rows),
        input_tokens=sum(int(r[2] or 0) for r in rows),
        output_tokens=sum(int(r[3] or 0) for r in rows),
        by_kind={r[0]: r[1] for r in rows},
    )
