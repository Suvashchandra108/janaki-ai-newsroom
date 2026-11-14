"""Research & evidence data model.

A *claim* is a checkable statement about an event. *Evidence* links a claim to a specific
publisher's article, with a short verbatim excerpt and whether it supports or contradicts the
claim. A claim's verification status is computed from its evidence by fixed rules (see
``research.rules``) — never from a model's self-reported confidence.
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
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk

CLAIM_TYPES = ("fact", "reported", "official", "allegation", "opinion", "estimate")
CLAIM_STATUSES = (
    "unreviewed",
    "researching",
    "corroborated",
    "conflicting",
    "insufficient",
    "editor_verified",
)


class SourceDocument(UUIDPk, Base):
    """Text of one discovered article, fetched for research only (never republished)."""

    __tablename__ = "source_documents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "item_id", name="uq_source_documents_tenant_item"),
        CheckConstraint(
            "status IN ('fetched', 'failed', 'blocked_by_robots', 'not_allowed', 'empty')",
            name="status",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("discovered_items.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    final_url: Mapped[str | None] = mapped_column(String(2000))
    text: Mapped[str | None] = mapped_column(Text)
    text_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    error: Mapped[str | None] = mapped_column(String(500))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claims_extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Claim(UUIDPk, Timestamps, Base):
    __tablename__ = "claims"
    __table_args__ = (
        UniqueConstraint("tenant_id", "event_id", "fingerprint", name="uq_claims_event_fp"),
        CheckConstraint(f"claim_type IN {CLAIM_TYPES}", name="claim_type"),
        CheckConstraint(f"status IN {CLAIM_STATUSES}", name="status"),
        Index("ix_claims_tenant_event", "tenant_id", "event_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("news_events.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(String(1000), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    claim_type: Mapped[str] = mapped_column(String(20), nullable=False)
    keywords: Mapped[list[str]] = mapped_column(ARRAY(String(100)), nullable=False)
    entities: Mapped[list[str]] = mapped_column(ARRAY(String(200)), nullable=False)
    numbers: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    dates: Mapped[list[str]] = mapped_column(ARRAY(String(100)), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="unreviewed")
    status_reason: Mapped[str | None] = mapped_column(String(300))
    independent_sources: Mapped[int] = mapped_column(nullable=False, default=0)
    editor_note: Mapped[str | None] = mapped_column(String(2000))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Evidence(UUIDPk, Base):
    __tablename__ = "evidence"
    __table_args__ = (
        UniqueConstraint("claim_id", "item_id", "relationship", name="uq_evidence_claim_item_rel"),
        CheckConstraint(
            "relationship IN ('supports', 'contradicts', 'context')", name="relationship"
        ),
        CheckConstraint(
            "evidence_type IN ('news_report', 'official_statement', 'editor_note')",
            name="evidence_type",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    claim_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("discovered_items.id", ondelete="SET NULL")
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("source_documents.id", ondelete="SET NULL")
    )
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    publisher_domain: Mapped[str] = mapped_column(String(253), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    excerpt: Mapped[str] = mapped_column(String(600), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(30), nullable=False, default="news_report")
    relationship: Mapped[str] = mapped_column(String(20), nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
