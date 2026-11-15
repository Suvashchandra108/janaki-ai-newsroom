"""Phase 6 API: dashboard summary and notifications."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require
from app.core.errors import NotFound
from app.core.permissions import P
from app.core.principal import Principal
from app.db.session import get_db
from app.modules.dashboard import service as dashboard
from app.modules.tenancy.models import Tenant

router = APIRouter(tags=["dashboard"])


class NotificationOut(BaseModel):
    kind: str  # job_failed | draft_ready | sent_to_website | delivery_failed | website_status
    severity: str  # info | warning | error
    at: datetime
    target_type: str | None
    target_id: str | None
    data: dict[str, Any]


def _tenant(db: Session, principal: Principal) -> Tenant:
    t = db.get(Tenant, principal.tenant_id)
    if t is None:
        raise NotFound("Organisation not found.")
    return t


@router.get("/dashboard/summary")
def get_summary(
    db: Session = Depends(get_db), principal: Principal = Depends(require(P.EVENTS_READ))
) -> dict[str, Any]:
    """Counts for the dashboard, computed from the same records as the other endpoints."""
    return dashboard.summary(db, _tenant(db, principal))


@router.get("/dashboard/notifications", response_model=list[NotificationOut])
def get_notifications(
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.EVENTS_READ)),
) -> list[NotificationOut]:
    return [
        NotificationOut(**n)
        for n in dashboard.notifications(db, _tenant(db, principal), limit=limit)
    ]
