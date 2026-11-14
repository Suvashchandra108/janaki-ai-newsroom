from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.principal import Principal, RequestMeta
from app.modules.audit.models import AuditLog


def record(
    db: Session,
    *,
    action: str,
    tenant_id: uuid.UUID | None,
    principal: Principal | None = None,
    meta: RequestMeta | None = None,
    actor_type: str | None = None,
    actor_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: str | uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    meta = meta or (principal.meta if principal else RequestMeta())
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_type=actor_type or (principal.kind if principal else "anon"),
            actor_id=actor_id or (principal.actor_id if principal else None),
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            ip=meta.ip,
            user_agent=(meta.user_agent or "")[:400] or None,
            request_id=meta.request_id,
            details=details or {},
        )
    )
    db.flush()


def list_logs(
    db: Session, *, tenant_id: uuid.UUID, action: str | None, limit: int, offset: int
) -> list[AuditLog]:
    q = select(AuditLog).where(AuditLog.tenant_id == tenant_id)
    if action:
        q = q.where(AuditLog.action == action)
    q = q.order_by(AuditLog.id.desc()).limit(limit).offset(offset)
    return list(db.scalars(q))
