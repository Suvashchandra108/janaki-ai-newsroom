from __future__ import annotations

from typing import Any

from sqlalchemy import CheckConstraint, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk


class Tenant(UUIDPk, Timestamps, Base):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'suspended')", name="status"),
        CheckConstraint("default_language IN ('ne', 'en')", name="default_language"),
        CheckConstraint("slug ~ '^[a-z0-9](-?[a-z0-9])*$'", name="slug_format"),
    )

    slug: Mapped[str] = mapped_column(String(63), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    default_language: Mapped[str] = mapped_column(String(5), nullable=False, default="en")
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
