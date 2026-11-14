from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
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


class NewsSource(UUIDPk, Timestamps, Base):
    """An approved source. Only fetched URLs on ``allowed_domains`` are ever requested."""

    __tablename__ = "news_sources"
    __table_args__ = (
        UniqueConstraint("tenant_id", "feed_url", name="uq_news_sources_tenant_feed"),
        CheckConstraint("kind IN ('rss', 'search')", name="kind"),
        CheckConstraint("credibility IN ('high', 'medium', 'low', 'unknown')", name="credibility"),
        CheckConstraint("language IN ('ne', 'en')", name="language"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False, default="rss")
    feed_url: Mapped[str | None] = mapped_column(String(2000))
    search_query: Mapped[str | None] = mapped_column(String(300))
    allowed_domains: Mapped[list[str]] = mapped_column(ARRAY(String(253)), nullable=False)
    language: Mapped[str] = mapped_column(String(5), nullable=False, default="en")
    country: Mapped[str | None] = mapped_column(String(2))  # ISO 3166-1 alpha-2
    region: Mapped[str | None] = mapped_column(String(100))  # e.g. "Madhesh Province"
    category: Mapped[str | None] = mapped_column(String(50))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    credibility: Mapped[str] = mapped_column(String(10), nullable=False, default="unknown")
    credibility_notes: Mapped[str | None] = mapped_column(Text)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class NewsEvent(UUIDPk, Timestamps, Base):
    """A real-world event; several discovered items from different publishers may map to it."""

    __tablename__ = "news_events"
    __table_args__ = (
        Index("ix_news_events_tenant_last_seen", "tenant_id", "last_seen_at"),
        CheckConstraint(
            "status IN ('discovered', 'researching', 'evidence_assessment', 'generating', "
            "'draft', 'archived', 'failed')",
            name="status",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    keywords: Mapped[list[str]] = mapped_column(ARRAY(String(100)), nullable=False)
    title_simhash: Mapped[int] = mapped_column(BigInteger, nullable=False)
    language: Mapped[str] = mapped_column(String(5), nullable=False)
    category: Mapped[str | None] = mapped_column(String(50))
    region: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="discovered")
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    publisher_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DiscoveredItem(UUIDPk, Base):
    __tablename__ = "discovered_items"
    __table_args__ = (
        UniqueConstraint("tenant_id", "url_hash", name="uq_discovered_items_tenant_url"),
        CheckConstraint("status IN ('clustered', 'skipped')", name="status"),
        Index("ix_discovered_items_tenant_retrieved", "tenant_id", "retrieved_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("news_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("news_events.id", ondelete="SET NULL"), index=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("background_jobs.id", ondelete="SET NULL")
    )
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    publisher_domain: Mapped[str] = mapped_column(String(253), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(200))
    language: Mapped[str] = mapped_column(String(5), nullable=False)
    category: Mapped[str | None] = mapped_column(String(50))
    region: Mapped[str | None] = mapped_column(String(100))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    title_simhash: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="clustered")


class BackgroundJob(UUIDPk, Base):
    __tablename__ = "background_jobs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_background_jobs_tenant_key"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'partial', 'failed', 'skipped')",
            name="status",
        ),
        Index("ix_background_jobs_tenant_created", "tenant_id", "created_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    trigger: Mapped[str] = mapped_column(String(20), nullable=False, default="schedule")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(1000))
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
