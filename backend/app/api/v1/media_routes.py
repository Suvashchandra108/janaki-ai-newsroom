"""Phase 5 API: licensed photo search, editor selection, charts, AI illustrations, files."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import require
from app.core.config import get_settings
from app.core.errors import NotFound
from app.core.permissions import P
from app.core.principal import Principal
from app.db.session import get_db
from app.modules.discovery.safe_fetch import SafeFetcher
from app.modules.tenancy.models import Tenant
from app.modules.visuals import service as visuals
from app.modules.visuals.illustrations import get_image_generator
from app.modules.visuals.storage import Storage, get_storage, key_belongs_to

router = APIRouter(tags=["media"])


def get_fetcher() -> SafeFetcher:
    s = get_settings()
    # Wikimedia asks automated clients to identify themselves with a contact address.
    return SafeFetcher(
        timeout=s.fetch_timeout_seconds,
        max_bytes=s.media_max_download_bytes,
        user_agent=f"JanakiNewsroomBot/0.1 (media search; contact: {s.media_contact})",
    )


def storage_dep() -> Storage:
    return get_storage()


class MediaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID | None
    article_id: uuid.UUID | None
    role: str | None
    kind: str
    status: str
    provider: str
    source_page_url: str | None
    original_url: str
    title: str
    creator: str | None
    licence_name: str | None
    licence_url: str | None
    attribution_required: bool
    attribution_text: str | None
    commercial_use: bool
    modification_allowed: bool
    restrictions: list[str]
    publishable: bool
    licence_notes: str | None
    ai_generated: bool
    label: str | None
    chart_spec: dict[str, Any] | None
    mime: str | None
    width: int | None
    height: int | None
    derivatives: list[dict[str, Any]]
    processing_history: list[dict[str, Any]]
    caption: str | None
    retrieved_at: datetime
    selected_at: datetime | None


class SearchIn(BaseModel):
    query: str | None = Field(default=None, min_length=2, max_length=120)


class SelectIn(BaseModel):
    article_id: uuid.UUID | None = None
    role: Literal["hero", "inline"] = "hero"
    caption: str | None = Field(default=None, max_length=300)


@router.get("/events/{event_id}/media", response_model=list[MediaOut])
def event_media(
    event_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.ARTICLES_READ)),
) -> list[MediaOut]:
    return [MediaOut.model_validate(a) for a in visuals.media_for_event(db, principal, event_id)]


@router.post(
    "/events/{event_id}/media/search",
    response_model=list[MediaOut],
    status_code=status.HTTP_201_CREATED,
)
def search_photos(
    event_id: uuid.UUID,
    body: SearchIn,
    db: Session = Depends(get_db),
    fetcher: SafeFetcher = Depends(get_fetcher),
    principal: Principal = Depends(require(P.MEDIA_MANAGE)),
) -> list[MediaOut]:
    try:
        found = visuals.find_photos(db, principal, event_id, fetcher, query=body.query)
    finally:
        fetcher.close()
    return [MediaOut.model_validate(a) for a in found]


@router.post(
    "/events/{event_id}/media/chart", response_model=MediaOut, status_code=status.HTTP_201_CREATED
)
def make_chart(
    event_id: uuid.UUID,
    db: Session = Depends(get_db),
    storage: Storage = Depends(storage_dep),
    principal: Principal = Depends(require(P.MEDIA_MANAGE)),
) -> MediaOut:
    return MediaOut.model_validate(visuals.make_chart(db, principal, event_id, storage))


@router.post(
    "/events/{event_id}/media/illustration",
    response_model=MediaOut,
    status_code=status.HTTP_201_CREATED,
)
def make_illustration(
    event_id: uuid.UUID,
    db: Session = Depends(get_db),
    storage: Storage = Depends(storage_dep),
    principal: Principal = Depends(require(P.MEDIA_MANAGE)),
) -> MediaOut:
    tenant = db.get(Tenant, principal.tenant_id)
    assert tenant is not None
    limit = int((tenant.settings.get("generation") or {}).get("max_illustrations_per_day", 3))
    return MediaOut.model_validate(
        visuals.make_illustration(db, principal, event_id, get_image_generator(), storage, limit)
    )


@router.post("/media/{asset_id}/select", response_model=MediaOut)
def select_media(
    asset_id: uuid.UUID,
    body: SelectIn,
    db: Session = Depends(get_db),
    fetcher: SafeFetcher = Depends(get_fetcher),
    storage: Storage = Depends(storage_dep),
    principal: Principal = Depends(require(P.MEDIA_MANAGE)),
) -> MediaOut:
    try:
        a = visuals.select_asset(
            db,
            principal,
            asset_id,
            article_id=body.article_id,
            role=body.role,
            caption=body.caption,
            fetcher=fetcher,
            storage=storage,
        )
    finally:
        fetcher.close()
    return MediaOut.model_validate(a)


@router.post("/media/{asset_id}/reject", response_model=MediaOut)
def reject_media(
    asset_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.MEDIA_MANAGE)),
) -> MediaOut:
    return MediaOut.model_validate(visuals.reject_asset(db, principal, asset_id))


@router.get("/media/{asset_id}/files/{name}")
def media_file(
    asset_id: uuid.UUID,
    name: str,
    db: Session = Depends(get_db),
    storage: Storage = Depends(storage_dep),
    principal: Principal = Depends(require(P.ARTICLES_READ)),
) -> Response:
    a = visuals.get_asset(db, principal, asset_id)
    files = {d["name"]: (d["key"], d["mime"]) for d in a.derivatives}
    if a.storage_key:
        files.setdefault(a.storage_key.rsplit("/", 1)[-1], (a.storage_key, a.mime or ""))
    if name not in files:
        raise NotFound("File not found.")
    key, mime = files[name]
    assert principal.tenant_id
    if not key_belongs_to(key, principal.tenant_id):
        raise NotFound("File not found.")
    headers = {
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
        "Cache-Control": "private, max-age=300",
    }
    return Response(
        storage.get(key), media_type=mime or "application/octet-stream", headers=headers
    )
