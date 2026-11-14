"""Articles and their versions.

An *article* is one editorial angle on one event (A = straight report, B = context/impact).
Every edit — AI generation, regeneration or editor change — creates a new *version*; versions
are never modified. Approval and publication happen in the website CMS (Phase 7), never here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk

ARTICLE_STATUSES = ("draft", "needs_review", "rejected", "delivered")


class Article(UUIDPk, Timestamps, Base):
    __tablename__ = "articles"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "event_id", "angle", "language", name="uq_articles_event_angle_lang"
        ),
        UniqueConstraint("tenant_id", "slug", name="uq_articles_tenant_slug"),
        CheckConstraint("angle IN ('straight', 'context')", name="angle"),
        CheckConstraint(f"status IN {ARTICLE_STATUSES}", name="status"),
        CheckConstraint("language IN ('en', 'ne')", name="language"),
        Index("ix_articles_tenant_status", "tenant_id", "status"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("news_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    angle: Mapped[str] = mapped_column(String(20), nullable=False)
    language: Mapped[str] = mapped_column(String(5), nullable=False, default="en")
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    regenerations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejection_reason: Mapped[str | None] = mapped_column(String(1000))


class ArticleVersion(UUIDPk, Base):
    __tablename__ = "article_versions"
    __table_args__ = (
        UniqueConstraint("article_id", "version", name="uq_article_versions_article_version"),
        CheckConstraint("created_by_kind IN ('ai', 'user')", name="created_by_kind"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    article_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("articles.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    headline: Mapped[str] = mapped_column(String(300), nullable=False)
    alt_headline: Mapped[str | None] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(String(1000), nullable=False)
    # [{"text": "...", "claim_ids": ["uuid", ...]}]
    paragraphs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    image_caption: Mapped[str | None] = mapped_column(String(500))
    seo_title: Mapped[str] = mapped_column(String(70), nullable=False)
    seo_description: Mapped[str] = mapped_column(String(170), nullable=False)
    keywords: Mapped[list[str]] = mapped_column(ARRAY(String(60)), nullable=False)
    category: Mapped[str | None] = mapped_column(String(50))
    location: Mapped[str | None] = mapped_column(String(200))
    social: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict)
    # Validation findings shown to editors, e.g. uncited paragraph, unsupported number.
    flags: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    attribution: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    created_by_user: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    model: Mapped[str | None] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
