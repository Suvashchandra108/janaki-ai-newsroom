"""Phase 4 API: English drafts, version history, editor edits, regeneration, rejection."""

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
from app.modules.ai_gateway.gateway import get_writing_provider
from app.modules.audit import service as audit
from app.modules.discovery.models import NewsEvent
from app.modules.editorial import service as editorial
from app.modules.editorial.models import Article, ArticleVersion
from app.modules.tenancy.models import Tenant

router = APIRouter(tags=["editorial"])


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class VersionOut(ORM):
    version: int
    headline: str
    alt_headline: str | None
    summary: str
    paragraphs: list[dict[str, Any]]
    image_caption: str | None
    seo_title: str
    seo_description: str
    keywords: list[str]
    category: str | None
    location: str | None
    social: dict[str, str]
    flags: list[dict[str, Any]]
    attribution: str
    created_by_kind: str
    created_by_user: uuid.UUID | None
    model: str | None
    note: str | None
    created_at: datetime


class ArticleSummaryOut(ORM):
    id: uuid.UUID
    event_id: uuid.UUID
    angle: str
    language: str
    slug: str
    status: str
    current_version: int
    regenerations: int
    rejection_reason: str | None
    updated_at: datetime
    headline: str = ""
    flag_count: int = 0


class ArticleOut(ArticleSummaryOut):
    current: VersionOut
    versions: list[int] = []


class ParagraphIn(BaseModel):
    text: str = Field(min_length=1, max_length=3000)
    claim_ids: list[str] = Field(default_factory=list, max_length=20)


class EditIn(BaseModel):
    headline: str | None = Field(default=None, min_length=5, max_length=120)
    alt_headline: str | None = Field(default=None, max_length=120)
    summary: str | None = Field(default=None, min_length=5, max_length=400)
    paragraphs: list[ParagraphIn] | None = Field(default=None, min_length=1, max_length=30)
    image_caption: str | None = Field(default=None, max_length=300)
    seo_title: str | None = Field(default=None, min_length=5, max_length=70)
    seo_description: str | None = Field(default=None, min_length=5, max_length=170)
    keywords: list[str] | None = Field(default=None, max_length=15)
    category: str | None = Field(default=None, max_length=50)
    location: str | None = Field(default=None, max_length=200)
    social: dict[Literal["facebook", "instagram", "x"], str] | None = None
    note: str | None = Field(default=None, max_length=1000)


class RejectIn(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class RunOut(BaseModel):
    idempotency_key: str
    status: str = "queued"


def _summary(db: Session, art: Article) -> ArticleSummaryOut:
    out = ArticleSummaryOut.model_validate(art)
    v = editorial.current_version(db, art)
    out.headline = v.headline
    out.flag_count = sum(1 for f in v.flags if f.get("severity") == "warning")
    return out


def _full(db: Session, art: Article) -> ArticleOut:
    v = editorial.current_version(db, art)
    versions = list(
        db.scalars(
            select(ArticleVersion.version)
            .where(ArticleVersion.article_id == art.id)
            .order_by(ArticleVersion.version)
        )
    )
    return ArticleOut(
        **_summary(db, art).model_dump(), current=VersionOut.model_validate(v), versions=versions
    )


@router.get("/articles", response_model=list[ArticleSummaryOut])
def list_articles(
    article_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.ARTICLES_READ)),
) -> list[ArticleSummaryOut]:
    q = select(Article).where(Article.tenant_id == principal.tenant_id)
    if article_status:
        q = q.where(Article.status == article_status)
    rows = db.scalars(q.order_by(Article.updated_at.desc()).limit(limit).offset(offset))
    return [_summary(db, a) for a in rows]


@router.get("/articles/{article_id}", response_model=ArticleOut)
def get_article(
    article_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.ARTICLES_READ)),
) -> ArticleOut:
    return _full(db, editorial.get_article(db, principal, article_id))


@router.get("/articles/{article_id}/versions/{version}", response_model=VersionOut)
def get_version(
    article_id: uuid.UUID,
    version: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.ARTICLES_READ)),
) -> VersionOut:
    art = editorial.get_article(db, principal, article_id)
    v = db.scalar(
        select(ArticleVersion).where(
            ArticleVersion.article_id == art.id, ArticleVersion.version == version
        )
    )
    if v is None:
        raise NotFound("Version not found.")
    return VersionOut.model_validate(v)


@router.patch("/articles/{article_id}", response_model=ArticleOut)
def edit_article(
    article_id: uuid.UUID,
    body: EditIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.ARTICLES_EDIT)),
) -> ArticleOut:
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise AppError("Nothing to change.", code="no_changes", status_code=422)
    editorial.edit_article(db, principal, article_id, changes)
    return _full(db, editorial.get_article(db, principal, article_id))


@router.post("/articles/{article_id}/regenerate", response_model=ArticleOut)
def regenerate(
    article_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.ARTICLES_EDIT)),
) -> ArticleOut:
    tenant = db.get(Tenant, principal.tenant_id)
    assert tenant is not None
    limit = int((tenant.settings.get("generation") or {}).get("max_regenerations", 3))
    editorial.regenerate(db, principal, article_id, get_writing_provider(), limit)
    return _full(db, editorial.get_article(db, principal, article_id))


@router.post("/articles/{article_id}/reject", response_model=ArticleOut)
def reject(
    article_id: uuid.UUID,
    body: RejectIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.ARTICLES_REJECT)),
) -> ArticleOut:
    return _full(db, editorial.reject(db, principal, article_id, body.reason))


@router.get("/events/{event_id}/articles", response_model=list[ArticleSummaryOut])
def event_articles(
    event_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.ARTICLES_READ)),
) -> list[ArticleSummaryOut]:
    ev = db.scalar(
        select(NewsEvent).where(
            NewsEvent.id == event_id, NewsEvent.tenant_id == principal.tenant_id
        )
    )
    if ev is None:
        raise NotFound("Event not found.")
    rows = db.scalars(select(Article).where(Article.event_id == ev.id).order_by(Article.angle))
    return [_summary(db, a) for a in rows]


@router.post(
    "/events/{event_id}/write", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED
)
def write_now(
    event_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.ARTICLES_CREATE)),
) -> RunOut:
    from app import worker  # local import keeps the API importable without a broker

    ev = db.scalar(
        select(NewsEvent).where(
            NewsEvent.id == event_id, NewsEvent.tenant_id == principal.tenant_id
        )
    )
    if ev is None:
        raise NotFound("Event not found.")
    ok, reason = editorial.eligibility(db, ev)
    if not ok:
        raise AppError(f"Not ready to write: {reason}.", code="not_eligible", status_code=409)
    assert principal.tenant_id
    try:
        key = worker.enqueue_writing(principal.tenant_id, ev.id)
    except Exception as exc:
        raise AppError(
            "The job queue is unavailable. Try again shortly.",
            code="queue_unavailable",
            status_code=503,
        ) from exc
    audit.record(
        db,
        principal=principal,
        action="writing.run_requested",
        tenant_id=principal.tenant_id,
        target_type="news_event",
        target_id=ev.id,
    )
    return RunOut(idempotency_key=key)
