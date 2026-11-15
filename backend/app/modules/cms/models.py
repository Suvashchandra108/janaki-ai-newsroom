"""Website CMS connection and draft deliveries (Phase 7).

The newsroom never approves or publishes. It delivers *drafts* into the tenant's own CMS, where
people review and publish them, and then follows their status there.
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
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk

DELIVERY_STATUSES = ("pending", "delivered", "failed")
# Mirrors the website's article statuses, plus "removed" when the draft was deleted there.
REMOTE_STATUSES = ("draft", "inReview", "approved", "scheduled", "published", "archived", "removed")


class CmsConnection(UUIDPk, Timestamps, Base):
    __tablename__ = "cms_connections"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_cms_connections_tenant"),
        CheckConstraint("kind IN ('payload')", name="kind"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="payload")
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    # Encrypted at rest (Fernet); never returned by the API.
    api_key_encrypted: Mapped[str] = mapped_column(String(1000), nullable=False)
    api_key_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    auto_deliver: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Newsroom category -> CMS category id. Unmapped categories are matched by slug, else left
    # empty for the editor.
    category_map: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))


class CmsDelivery(UUIDPk, Timestamps, Base):
    __tablename__ = "cms_deliveries"
    __table_args__ = (
        # One delivery per article: the CMS integration cannot edit, so a draft is sent once.
        UniqueConstraint("tenant_id", "article_id", name="uq_cms_deliveries_article"),
        UniqueConstraint("newsroom_ref", name="uq_cms_deliveries_ref"),
        CheckConstraint(f"status IN {DELIVERY_STATUSES}", name="status"),
        CheckConstraint(
            f"remote_status IS NULL OR remote_status IN {REMOTE_STATUSES}", name="remote_status"
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    article_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("articles.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    newsroom_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500))
    # True when the last failure was temporary (network, CMS down) and will be retried.
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    remote_id: Mapped[str | None] = mapped_column(String(64))
    remote_media_id: Mapped[str | None] = mapped_column(String(64))
    remote_status: Mapped[str | None] = mapped_column(String(15))
    remote_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
