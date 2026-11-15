"""Phase 2 API: approved sources, discovery control, jobs, events and discovered items."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require
from app.core.errors import AppError, NotFound
from app.core.permissions import P
from app.core.principal import Principal
from app.db.session import get_db
from app.modules.audit import service as audit
from app.modules.discovery import service as discovery
from app.modules.discovery.models import BackgroundJob, DiscoveredItem, NewsEvent
from app.modules.tenancy.models import Tenant

sources = APIRouter(prefix="/sources", tags=["discovery"])
disc = APIRouter(prefix="/discovery", tags=["discovery"])
events = APIRouter(prefix="/events", tags=["discovery"])

Credibility = Literal["high", "medium", "low", "unknown"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SourceIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    kind: Literal["rss", "search"] = "rss"
    feed_url: str | None = Field(default=None, max_length=2000)
    search_query: str | None = Field(default=None, max_length=300)
    allowed_domains: list[str] = Field(min_length=1, max_length=20)
    language: Literal["en", "ne"] = "en"
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    region: str | None = Field(default=None, max_length=100)
    category: str | None = Field(default=None, max_length=50)
    priority: int = Field(default=50, ge=0, le=100)
    credibility: Credibility = "unknown"
    credibility_notes: str | None = Field(default=None, max_length=2000)
    is_enabled: bool = True


class SourceUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    feed_url: str | None = Field(default=None, max_length=2000)
    search_query: str | None = Field(default=None, max_length=300)
    allowed_domains: list[str] | None = Field(default=None, min_length=1, max_length=20)
    language: Literal["en", "ne"] | None = None
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    region: str | None = Field(default=None, max_length=100)
    category: str | None = Field(default=None, max_length=50)
    priority: int | None = Field(default=None, ge=0, le=100)
    credibility: Credibility | None = None
    credibility_notes: str | None = Field(default=None, max_length=2000)
    is_enabled: bool | None = None


class SourceOut(ORM):
    id: uuid.UUID
    name: str
    kind: str
    feed_url: str | None
    search_query: str | None
    allowed_domains: list[str]
    language: str
    country: str | None
    region: str | None
    category: str | None
    priority: int
    credibility: str
    credibility_notes: str | None
    is_enabled: bool
    last_fetched_at: datetime | None
    last_error: str | None
    consecutive_failures: int
    created_at: datetime


class JobOut(ORM):
    id: uuid.UUID
    job_type: str
    idempotency_key: str
    trigger: str
    status: str
    attempts: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    result: dict[str, Any]


class StatusOut(BaseModel):
    paused: bool
    daily_item_quota: int
    items_today: int
    quota_remaining: int
    next_scheduled_run: datetime | None
    last_job_status: str | None
    last_job_at: datetime | None


class RunOut(BaseModel):
    idempotency_key: str
    status: str = "queued"


class ItemOut(ORM):
    id: uuid.UUID
    source_id: uuid.UUID
    event_id: uuid.UUID | None
    url: str
    canonical_url: str
    publisher_domain: str
    title: str
    description: str | None
    author: str | None
    language: str
    category: str | None
    region: str | None
    published_at: datetime | None
    retrieved_at: datetime


class EventOut(ORM):
    id: uuid.UUID
    title: str
    language: str
    category: str | None
    region: str | None
    status: str
    item_count: int
    publisher_count: int
    first_seen_at: datetime
    last_seen_at: datetime


class EventDetailOut(EventOut):
    keywords: list[str]
    items: list[ItemOut] = []


# --- sources ------------------------------------------------------------------------------


@sources.get("", response_model=list[SourceOut])
def list_sources(
    db: Session = Depends(get_db), principal: Principal = Depends(require(P.EVENTS_READ))
) -> list[SourceOut]:
    assert principal.tenant_id
    return [SourceOut.model_validate(s) for s in discovery.list_sources(db, principal.tenant_id)]


@sources.post("", response_model=SourceOut, status_code=status.HTTP_201_CREATED)
def create_source(
    body: SourceIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.SOURCES_MANAGE)),
) -> SourceOut:
    return SourceOut.model_validate(discovery.create_source(db, principal, body.model_dump()))


@sources.get("/{source_id}", response_model=SourceOut)
def get_source(
    source_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.EVENTS_READ)),
) -> SourceOut:
    return SourceOut.model_validate(discovery.get_source(db, principal, source_id))


@sources.patch("/{source_id}", response_model=SourceOut)
def update_source(
    source_id: uuid.UUID,
    body: SourceUpdateIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.SOURCES_MANAGE)),
) -> SourceOut:
    changes = body.model_dump(exclude_unset=True)
    return SourceOut.model_validate(discovery.update_source(db, principal, source_id, changes))


# --- discovery control --------------------------------------------------------------------


def _tenant(db: Session, principal: Principal) -> Tenant:
    tenant = db.get(Tenant, principal.tenant_id)
    if tenant is None:
        raise NotFound("Tenant not found.")
    return tenant


@disc.get("/status", response_model=StatusOut)
def discovery_status(
    db: Session = Depends(get_db), principal: Principal = Depends(require(P.EVENTS_READ))
) -> StatusOut:
    return StatusOut(**discovery.status_summary(db, _tenant(db, principal)))


@disc.post("/run", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED)
def run_now(
    db: Session = Depends(get_db), principal: Principal = Depends(require(P.DISCOVERY_RUN))
) -> RunOut:
    from app import worker  # local import keeps the API importable without a broker

    assert principal.tenant_id
    if discovery.discovery_settings(_tenant(db, principal))["paused"]:
        raise AppError(
            "Discovery is paused. Resume it first.", code="discovery_paused", status_code=409
        )
    try:
        key = worker.enqueue_manual_run(principal.tenant_id)
    except Exception as exc:
        raise AppError(
            "The job queue is unavailable. Try again shortly.",
            code="queue_unavailable",
            status_code=503,
        ) from exc
    audit.record(
        db,
        principal=principal,
        action="discovery.run_requested",
        tenant_id=principal.tenant_id,
        details={"idempotency_key": key},
    )
    return RunOut(idempotency_key=key)


@disc.post("/pause", response_model=StatusOut)
def pause(
    db: Session = Depends(get_db), principal: Principal = Depends(require(P.DISCOVERY_RUN))
) -> StatusOut:
    return StatusOut(**discovery.status_summary(db, discovery.set_paused(db, principal, True)))


@disc.post("/resume", response_model=StatusOut)
def resume(
    db: Session = Depends(get_db), principal: Principal = Depends(require(P.DISCOVERY_RUN))
) -> StatusOut:
    return StatusOut(**discovery.status_summary(db, discovery.set_paused(db, principal, False)))


@disc.get("/jobs", response_model=list[JobOut])
def list_jobs(
    job_status: str | None = Query(default=None, alias="status", max_length=20),
    job_type: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.EVENTS_READ)),
) -> list[JobOut]:
    rows = db.scalars(
        select(BackgroundJob)
        .where(
            BackgroundJob.tenant_id == principal.tenant_id,
            *([BackgroundJob.status == job_status] if job_status else []),
            *([BackgroundJob.job_type == job_type] if job_type else []),
        )
        .order_by(BackgroundJob.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [JobOut.model_validate(j) for j in rows]


@disc.get("/items", response_model=list[ItemOut])
def list_items(
    source_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.EVENTS_READ)),
) -> list[ItemOut]:
    q = select(DiscoveredItem).where(DiscoveredItem.tenant_id == principal.tenant_id)
    if source_id:
        q = q.where(DiscoveredItem.source_id == source_id)
    rows = db.scalars(q.order_by(DiscoveredItem.retrieved_at.desc()).limit(limit).offset(offset))
    return [ItemOut.model_validate(i) for i in rows]


# --- events -------------------------------------------------------------------------------


@events.get("", response_model=list[EventOut])
def list_events(
    min_publishers: int = Query(default=1, ge=1),
    event_status: str | None = Query(default=None, alias="status", max_length=30),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.EVENTS_READ)),
) -> list[EventOut]:
    rows = db.scalars(
        select(NewsEvent)
        .where(
            NewsEvent.tenant_id == principal.tenant_id,
            NewsEvent.publisher_count >= min_publishers,
            *([NewsEvent.status == event_status] if event_status else []),
        )
        .order_by(NewsEvent.last_seen_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [EventOut.model_validate(e) for e in rows]


@events.get("/{event_id}", response_model=EventDetailOut)
def get_event(
    event_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.EVENTS_READ)),
) -> EventDetailOut:
    ev = db.scalar(
        select(NewsEvent).where(
            NewsEvent.id == event_id, NewsEvent.tenant_id == principal.tenant_id
        )
    )
    if ev is None:
        raise NotFound("Event not found.")
    out = EventDetailOut.model_validate(ev)
    items = db.scalars(
        select(DiscoveredItem)
        .where(DiscoveredItem.event_id == ev.id)
        .order_by(DiscoveredItem.published_at.desc().nulls_last())
    )
    out.items = [ItemOut.model_validate(i) for i in items]
    return out


ALL_DISCOVERY_ROUTERS = [sources, disc, events]
