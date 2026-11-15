"""Phase 7 API: website CMS connection, draft delivery and status."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import require
from app.core.errors import AppError, NotFound
from app.core.permissions import P
from app.core.principal import Principal
from app.db.session import get_db
from app.modules.cms import service as cms
from app.modules.cms.models import CmsConnection, CmsDelivery
from app.modules.cms.payload import CmsError
from app.modules.visuals.storage import Storage, get_storage

router = APIRouter(tags=["cms"])


def storage_dep() -> Storage:
    return get_storage()


def client_factory_dep() -> cms.ClientFactory:
    return cms.default_client


def _human(principal: Principal) -> None:
    if principal.kind != "user" or principal.is_service:
        raise AppError(
            "Only a person can change the CMS connection.", code="human_only", status_code=403
        )


class ConnectionIn(BaseModel):
    base_url: str = Field(max_length=500, examples=["https://janakitelevision.com"])
    # Write-only. Omit to keep the stored key.
    api_key: str | None = Field(default=None, max_length=500)
    enabled: bool = True
    auto_deliver: bool = False
    category_map: dict[str, int | str] | None = None


class ConnectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    base_url: str
    kind: str
    enabled: bool
    auto_deliver: bool
    category_map: dict[str, Any]
    api_key_last4: str
    last_ok_at: datetime | None
    last_error: str | None


class ConnectionStatusOut(BaseModel):
    connection: ConnectionOut
    ok: bool
    detail: str


class DeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    article_id: uuid.UUID
    version: int
    newsroom_ref: str
    status: str
    attempts: int
    retryable: bool
    last_error: str | None
    remote_id: str | None
    remote_media_id: str | None
    remote_status: str | None
    remote_published_at: datetime | None
    delivered_at: datetime | None
    synced_at: datetime | None


def _check(conn: CmsConnection, factory: cms.ClientFactory) -> tuple[bool, str]:
    try:
        who = cms.check_connection(factory(conn))
    except CmsError as exc:
        conn.last_error = f"{exc.code}: {exc.message}"[:500]
        return False, exc.message
    conn.last_error = None
    return True, f"Connected as integration “{who['integration']}”"


@router.get("/cms/connection", response_model=ConnectionOut)
def get_connection(
    db: Session = Depends(get_db), principal: Principal = Depends(require(P.CMS_MANAGE))
) -> ConnectionOut:
    assert principal.tenant_id is not None
    conn = cms.get_connection(db, principal.tenant_id)
    if conn is None:
        raise NotFound("No CMS connection yet.")
    return ConnectionOut.model_validate(conn)


@router.put("/cms/connection", response_model=ConnectionStatusOut)
def put_connection(
    body: ConnectionIn,
    db: Session = Depends(get_db),
    factory: cms.ClientFactory = Depends(client_factory_dep),
    principal: Principal = Depends(require(P.CMS_MANAGE)),
) -> ConnectionStatusOut:
    _human(principal)
    assert principal.tenant_id is not None
    try:
        conn = cms.configure(
            db,
            tenant_id=principal.tenant_id,
            base_url=body.base_url,
            api_key=body.api_key,
            enabled=body.enabled,
            auto_deliver=body.auto_deliver,
            category_map=body.category_map,
            principal=principal,
        )
    except CmsError as exc:
        raise AppError(exc.message, code=exc.code, status_code=422) from exc
    ok, detail = _check(conn, factory)
    return ConnectionStatusOut(connection=ConnectionOut.model_validate(conn), ok=ok, detail=detail)


@router.post("/cms/connection/check", response_model=ConnectionStatusOut)
def check_connection(
    db: Session = Depends(get_db),
    factory: cms.ClientFactory = Depends(client_factory_dep),
    principal: Principal = Depends(require(P.CMS_MANAGE)),
) -> ConnectionStatusOut:
    assert principal.tenant_id is not None
    conn = cms.get_connection(db, principal.tenant_id)
    if conn is None:
        raise NotFound("No CMS connection yet.")
    ok, detail = _check(conn, factory)
    return ConnectionStatusOut(connection=ConnectionOut.model_validate(conn), ok=ok, detail=detail)


@router.post("/articles/{article_id}/deliver", response_model=DeliveryOut)
def deliver_article(
    article_id: uuid.UUID,
    db: Session = Depends(get_db),
    storage: Storage = Depends(storage_dep),
    factory: cms.ClientFactory = Depends(client_factory_dep),
    principal: Principal = Depends(require(P.ARTICLES_EDIT)),
) -> DeliveryOut:
    """Send the article to the website CMS as an unpublished draft (people publish there)."""
    assert principal.tenant_id is not None
    d: CmsDelivery = cms.deliver(
        db,
        tenant_id=principal.tenant_id,
        article_id=article_id,
        storage=storage,
        client_factory=factory,
        principal=principal,
    )
    return DeliveryOut.model_validate(d)


@router.get("/articles/{article_id}/delivery", response_model=DeliveryOut)
def get_delivery(
    article_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.ARTICLES_READ)),
) -> DeliveryOut:
    assert principal.tenant_id is not None
    d = cms.get_delivery(db, principal.tenant_id, article_id)
    if d is None:
        raise NotFound("This article has not been sent to the CMS.")
    return DeliveryOut.model_validate(d)


@router.post("/cms/sync")
def sync_now(
    db: Session = Depends(get_db),
    factory: cms.ClientFactory = Depends(client_factory_dep),
    principal: Principal = Depends(require(P.CMS_MANAGE)),
) -> dict[str, int]:
    assert principal.tenant_id is not None
    return cms.sync(db, tenant_id=principal.tenant_id, client_factory=factory)
