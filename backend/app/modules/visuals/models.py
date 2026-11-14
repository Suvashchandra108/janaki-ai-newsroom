"""Media assets: licensed photos, AI illustrations and data charts.

Licensing rules from docs/IMAGE_LICENSING_POLICY.md are enforced by CHECK constraints, so no
code path can mark an unlicensed image publishable or store an unlabelled AI image.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
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
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk

AI_LABEL = "AI-generated illustration"


class MediaAsset(UUIDPk, Timestamps, Base):
    __tablename__ = "media_assets"
    __table_args__ = (
        CheckConstraint("kind IN ('photo', 'illustration', 'chart')", name="kind"),
        CheckConstraint("status IN ('candidate', 'selected', 'rejected')", name="status"),
        CheckConstraint("role IS NULL OR role IN ('hero', 'inline')", name="role"),
        # Policy §2: an outside image is publishable only with a licence URL, commercial use and
        # attribution text when required. Own work (newsroom charts, AI illustrations) is exempt.
        CheckConstraint(
            "NOT publishable OR provider IN ('newsroom_chart', 'ai_image') "
            "OR (licence_url IS NOT NULL AND commercial_use "
            "AND (NOT attribution_required OR attribution_text IS NOT NULL))",
            name="publishable_requires_licence",
        ),
        CheckConstraint("(provider = 'ai_image') = ai_generated", name="ai_provider_matches_flag"),
        # Policy §5: AI images always carry the label, and are never photos.
        CheckConstraint(
            "NOT ai_generated OR (kind = 'illustration' AND label IS NOT NULL "
            f"AND position('{AI_LABEL}' in label) > 0)",
            name="ai_label_required",
        ),
        # Only publishable assets can be selected for an article.
        CheckConstraint(
            "status <> 'selected' OR publishable", name="selected_requires_publishable"
        ),
        UniqueConstraint("tenant_id", "event_id", "original_url", name="uq_media_event_url"),
        Index("ix_media_assets_tenant_event", "tenant_id", "event_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("news_events.id", ondelete="CASCADE")
    )
    article_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("articles.id", ondelete="SET NULL"), index=True
    )
    role: Mapped[str | None] = mapped_column(String(10))
    kind: Mapped[str] = mapped_column(String(15), nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="candidate")

    # Provenance
    provider: Mapped[str] = mapped_column(String(50), nullable=False)  # wikimedia_commons, ...
    source_page_url: Mapped[str | None] = mapped_column(String(2000))
    original_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    creator: Mapped[str | None] = mapped_column(String(500))
    credit: Mapped[str | None] = mapped_column(String(500))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Licence
    licence_name: Mapped[str | None] = mapped_column(String(100))
    licence_url: Mapped[str | None] = mapped_column(String(500))
    attribution_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    attribution_text: Mapped[str | None] = mapped_column(String(1000))
    commercial_use: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    modification_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    restrictions: Mapped[list[str]] = mapped_column(ARRAY(String(100)), nullable=False)
    publishable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    licence_notes: Mapped[str | None] = mapped_column(String(500))

    # AI and charts
    ai_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    label: Mapped[str | None] = mapped_column(String(200))
    chart_spec: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # File and processing
    mime: Mapped[str | None] = mapped_column(String(50))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64))
    storage_key: Mapped[str | None] = mapped_column(String(500))
    derivatives: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    processing_history: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    caption: Mapped[str | None] = mapped_column(String(500))
    selected_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    selected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
