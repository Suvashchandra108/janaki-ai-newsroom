from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound
from app.core.principal import Principal
from app.db.session import system_scope
from app.modules.audit import service as audit
from app.modules.identity import service as identity
from app.modules.identity.models import User
from app.modules.tenancy.models import Tenant

# English-first launch (decision 2026-11-14): new tenants publish in their default language
# only. Nepali is enabled later by adding "ne" to "languages"; the schema already supports it.
DEFAULT_TENANT_SETTINGS = {
    "languages": ["en"],
    "timezone": "Asia/Kathmandu",
    "discovery": {"interval_minutes": 60, "daily_item_quota": 100, "paused": False},
    "generation": {"daily_event_cap": 10, "max_regenerations": 3},
    "attribution": {"ai_assisted_label": True},
}


def provision_tenant(
    db: Session,
    principal: Principal | None,
    *,
    slug: str,
    name: str,
    default_language: str,
    admin_email: str,
    admin_full_name: str,
    admin_password: str,
) -> tuple[Tenant, User]:
    """Create a tenant and its first tenant admin. Platform-admin or bootstrap only."""
    identity.validate_password(admin_password)
    with system_scope(db):
        tenant = Tenant(
            slug=slug.strip().lower(),
            name=name.strip(),
            default_language=default_language,
            settings={**DEFAULT_TENANT_SETTINGS, "languages": [default_language]},
        )
        db.add(tenant)
        try:
            with db.begin_nested():
                db.flush()
        except IntegrityError as exc:
            raise Conflict("A tenant with this slug already exists.") from exc
        admin = identity.create_user(
            db,
            tenant_id=tenant.id,
            email=admin_email,
            full_name=admin_full_name,
            password=admin_password,
            roles=["tenant_admin"],
        )
        audit.record(
            db,
            principal=principal,
            action="tenant.provisioned",
            tenant_id=tenant.id,
            actor_type=None if principal else "system",
            target_type="tenant",
            target_id=tenant.id,
            details={"slug": tenant.slug},
        )
        # Platform-level copy of the event (tenant_id NULL) for the SaaS operator's log.
        audit.record(
            db,
            principal=principal,
            action="tenant.provisioned",
            tenant_id=None,
            actor_type=None if principal else "system",
            target_type="tenant",
            target_id=tenant.id,
            details={"slug": tenant.slug},
        )
    return tenant, admin


def list_tenants(db: Session) -> list[Tenant]:
    with system_scope(db):
        return list(db.scalars(select(Tenant).order_by(Tenant.created_at)))


def platform_update_tenant(
    db: Session, principal: Principal, tenant_id: uuid.UUID, *, name: str | None, status: str | None
) -> Tenant:
    with system_scope(db):
        tenant = db.get(Tenant, tenant_id)
        if tenant is None:
            raise NotFound("Tenant not found.")
        if name is not None:
            tenant.name = name.strip()
        if status is not None and status != tenant.status:
            tenant.status = status
        db.flush()
        audit.record(
            db,
            principal=principal,
            action="tenant.platform_updated",
            tenant_id=None,
            target_type="tenant",
            target_id=tenant.id,
            details={"status": tenant.status, "name_changed": name is not None},
        )
        return tenant


def get_current(db: Session, principal: Principal) -> Tenant:
    tenant = db.get(Tenant, principal.tenant_id)
    if tenant is None:
        raise NotFound("Tenant not found.")
    return tenant


def update_current(
    db: Session, principal: Principal, *, name: str | None, default_language: str | None
) -> Tenant:
    tenant = get_current(db, principal)
    if name is not None:
        tenant.name = name.strip()
    if default_language is not None:
        tenant.default_language = default_language
    db.flush()
    audit.record(
        db,
        principal=principal,
        action="tenant.updated",
        tenant_id=tenant.id,
        target_type="tenant",
        target_id=tenant.id,
    )
    return tenant
