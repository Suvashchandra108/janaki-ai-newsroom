"""Draft delivery to the tenant's website CMS, and status sync back.

Delivery is idempotent: each article has one reference (``jn-<article id>``) that the CMS stores
in a unique field. Before creating anything the CMS is asked whether that reference already
exists, so a retry after a timeout never makes a second draft.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import get_settings
from app.core.errors import AppError, Conflict, NotFound
from app.core.principal import Principal
from app.modules.audit import service as audit
from app.modules.cms import mapping
from app.modules.cms.models import REMOTE_STATUSES, CmsConnection, CmsDelivery
from app.modules.cms.payload import CmsError, PayloadClient, parse_base_url
from app.modules.editorial import service as editorial
from app.modules.editorial.models import Article
from app.modules.research.models import Evidence
from app.modules.visuals.models import MediaAsset
from app.modules.visuals.storage import Storage, key_belongs_to

ClientFactory = Callable[[CmsConnection], PayloadClient]
DELIVERABLE = ("draft", "needs_review")
MAX_ATTEMPTS = 5
SYNC_WINDOW_DAYS = 30


def remote_id(value: str | int | None) -> str | int | None:
    """Payload ids are numbers on PostgreSQL; send them back as numbers."""
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return value


def cms_slug(article: Article) -> str:
    """The newsroom slug plus a short code from the article id: stable across retries and
    unlikely to clash with stories the website already has (its slugs are unique)."""
    return f"{article.slug[:100].rstrip('-')}-{article.id.hex[:6]}"


def newsroom_ref(article: Article) -> str:
    return f"jn-{article.id}"


def default_client(conn: CmsConnection) -> PayloadClient:
    s = get_settings()
    return PayloadClient(
        conn.base_url,
        security.decrypt_secret(conn.api_key_encrypted),
        allow_private=s.cms_allow_private_hosts,
        timeout=s.cms_timeout_seconds,
    )


# --- connection ------------------------------------------------------------------------------


def get_connection(db: Session, tenant_id: uuid.UUID) -> CmsConnection | None:
    return db.scalar(select(CmsConnection).where(CmsConnection.tenant_id == tenant_id))


def check_connection(client: PayloadClient) -> dict[str, Any]:
    """Asks the CMS who we are. The key must belong to an *active* integration."""
    status, data = client._request("GET", "/api/integrations/me")
    user = data.get("user") if status == 200 else None
    if not isinstance(user, dict):
        raise CmsError(
            "unauthorized", "The CMS did not accept the API key", retryable=False, status=status
        )
    if user.get("active") is not True:
        raise CmsError(
            "inactive",
            "The integration exists but is not active in the CMS (tick “Active”)",
            retryable=False,
        )
    return {"integration": user.get("name"), "id": user.get("id")}


def configure(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    base_url: str,
    api_key: str | None,
    enabled: bool = True,
    auto_deliver: bool = False,
    category_map: dict[str, Any] | None = None,
    principal: Principal | None = None,
) -> CmsConnection:
    target = parse_base_url(base_url, allow_private=get_settings().cms_allow_private_hosts)
    conn = get_connection(db, tenant_id)
    if conn is None:
        if not api_key:
            raise AppError("An API key is required.", code="api_key_required", status_code=422)
        conn = CmsConnection(tenant_id=tenant_id, base_url=target.base_url, category_map={})
        db.add(conn)
    conn.base_url = target.base_url
    if api_key:
        key = api_key.strip()
        if len(key) < 16 or any(ch.isspace() for ch in key):
            raise AppError(
                "That does not look like an API key.", code="bad_api_key", status_code=422
            )
        conn.api_key_encrypted = security.encrypt_secret(key)
        conn.api_key_last4 = key[-4:]
    conn.enabled, conn.auto_deliver = enabled, auto_deliver
    if category_map is not None:
        conn.category_map = {str(k)[:50]: v for k, v in category_map.items()}
    conn.last_error = None
    db.flush()
    audit.record(
        db,
        principal=principal,
        actor_type=None if principal else "system",
        action="cms.connection_configured",
        tenant_id=tenant_id,
        target_type="cms_connection",
        target_id=conn.id,
        details={
            "base_url": conn.base_url,
            "enabled": enabled,
            "auto_deliver": auto_deliver,
            "key_changed": bool(api_key),
        },
    )
    return conn


# --- delivery --------------------------------------------------------------------------------


def _hero_photo(db: Session, article: Article) -> MediaAsset | None:
    return db.scalar(
        select(MediaAsset)
        .where(
            MediaAsset.tenant_id == article.tenant_id,
            MediaAsset.article_id == article.id,
            MediaAsset.status == "selected",
            MediaAsset.role == "hero",
            MediaAsset.publishable.is_(True),
        )
        .order_by(MediaAsset.selected_at.desc())
    )


def _photo_file(photo: MediaAsset, storage: Storage) -> tuple[str, bytes, str] | None:
    """The largest web derivative (metadata already stripped), else the stored source."""
    derivs = sorted(photo.derivatives or [], key=lambda d: int(d.get("width") or 0))
    if derivs:
        d = derivs[-1]
        key, name, mime = str(d["key"]), str(d["name"]), str(d.get("mime", "image/webp"))
    elif photo.storage_key:
        key, name, mime = photo.storage_key, photo.storage_key.rsplit("/", 1)[-1], photo.mime or ""
    else:
        return None
    if not key_belongs_to(key, photo.tenant_id):
        return None
    return f"{photo.id.hex[:12]}-{name}", storage.get(key), mime


def _evidence_links(db: Session, claim_ids: set[str]) -> dict[str, list[mapping.EvidenceLink]]:
    out: dict[str, list[mapping.EvidenceLink]] = {}
    if not claim_ids:
        return out
    rows = db.scalars(
        select(Evidence).where(
            Evidence.claim_id.in_([uuid.UUID(c) for c in claim_ids]),
            Evidence.relationship == "supports",
        )
    )
    for e in rows:
        out.setdefault(str(e.claim_id), []).append(mapping.EvidenceLink(e.publisher_domain, e.url))
    return out


def _category_id(conn: CmsConnection, client: PayloadClient, category: str | None) -> Any:
    if not category:
        return None
    mapped = conn.category_map.get(category)
    if mapped is not None:
        return mapped
    return client.find_category_id(category.strip().lower().replace(" ", "-"))


def get_delivery(db: Session, tenant_id: uuid.UUID, article_id: uuid.UUID) -> CmsDelivery | None:
    return db.scalar(
        select(CmsDelivery).where(
            CmsDelivery.tenant_id == tenant_id, CmsDelivery.article_id == article_id
        )
    )


def deliver(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    article_id: uuid.UUID,
    storage: Storage,
    client_factory: ClientFactory | None = None,
    principal: Principal | None = None,
    now: datetime | None = None,
) -> CmsDelivery:
    """Send one article to the CMS as a draft. Never raises for CMS failures: the result is
    recorded on the delivery (``failed`` + ``retryable``) so the caller can commit it."""
    now = now or security.utcnow()
    conn = get_connection(db, tenant_id)
    if conn is None or not conn.enabled:
        raise Conflict("The website CMS is not connected for this organisation.")
    article = db.scalar(
        select(Article).where(Article.id == article_id, Article.tenant_id == tenant_id)
    )
    if article is None:
        raise NotFound("Article not found.")
    delivery = get_delivery(db, tenant_id, article_id)
    if delivery is not None and delivery.status == "delivered":
        return delivery
    if article.status not in DELIVERABLE:
        raise Conflict(f"A '{article.status}' article cannot be delivered.")
    version = editorial.current_version(db, article)
    ref = newsroom_ref(article)
    if delivery is None:
        delivery = CmsDelivery(
            tenant_id=tenant_id,
            article_id=article.id,
            version=version.version,
            newsroom_ref=ref,
            status="pending",
            attempts=0,
            retryable=False,
            requested_by=principal.user_id if principal else None,
        )
        db.add(delivery)
    delivery.version = version.version
    delivery.attempts += 1
    db.flush()

    photo_note: str | None = None
    try:
        client = (client_factory or default_client)(conn)
        existing = client.find_article_by_ref(ref)
        if existing is not None:
            remote = existing
        else:
            photo = _hero_photo(db, article)
            if photo is not None and delivery.remote_media_id is None:
                file = _photo_file(photo, storage)
                if file is None:
                    photo_note = "photo file not available; not sent"
                else:
                    try:
                        media = client.upload_media(
                            filename=file[0],
                            data=file[1],
                            mime=file[2],
                            fields=mapping.media_fields(photo, version),
                        )
                        delivery.remote_media_id = str(media["id"])
                        db.flush()
                    except CmsError as exc:
                        if exc.retryable:
                            raise
                        photo_note = f"photo not accepted by the CMS ({exc.message})"
            claims = editorial.claim_refs(db, article.event_id)
            cited = {cid for p in version.paragraphs for cid in p.get("claim_ids", [])}
            notes = mapping.editorial_notes(
                ref=ref,
                version=version,
                angle=article.angle,
                claims=claims,
                links=_evidence_links(db, cited),
                photo=photo if delivery.remote_media_id else None,
            )
            if photo_note:
                notes += f"\n\nPhoto: {photo_note}."
            payload = mapping.article_payload(
                ref=ref,
                slug=cms_slug(article),
                language=article.language,
                version=version,
                notes=notes,
                category_id=_category_id(conn, client, version.category),
                hero_media_id=remote_id(delivery.remote_media_id),
                photo=photo,
            )
            remote = client.create_article(payload)
    except CmsError as exc:
        delivery.status, delivery.retryable = "failed", exc.retryable
        delivery.last_error = f"{exc.code}: {exc.message}"[:500]
        conn.last_error = delivery.last_error
        db.flush()
        audit.record(
            db,
            principal=principal,
            actor_type=None if principal else "system",
            action="cms.delivery_failed",
            tenant_id=tenant_id,
            target_type="article",
            target_id=article.id,
            details={"error": exc.code, "retryable": exc.retryable, "attempt": delivery.attempts},
        )
        return delivery

    delivery.status, delivery.retryable, delivery.last_error = "delivered", False, photo_note
    delivery.remote_id = str(remote.get("id"))
    delivery.remote_status = _remote_status(remote)
    delivery.delivered_at = delivery.synced_at = now
    article.status = "delivered"
    conn.last_ok_at, conn.last_error = now, None
    db.flush()
    audit.record(
        db,
        principal=principal,
        actor_type=None if principal else "system",
        action="cms.draft_delivered",
        tenant_id=tenant_id,
        target_type="article",
        target_id=article.id,
        details={
            "remote_id": delivery.remote_id,
            "version": delivery.version,
            "photo": delivery.remote_media_id is not None,
            "recovered": existing is not None,
        },
    )
    return delivery


def _remote_status(doc: dict[str, Any]) -> str | None:
    value = doc.get("status")
    return value if value in REMOTE_STATUSES else None


def deliverable_articles(db: Session, tenant_id: uuid.UUID, limit: int = 20) -> list[uuid.UUID]:
    """Articles for automatic delivery: never sent, or failed for a temporary reason."""
    q = (
        select(Article.id)
        .outerjoin(
            CmsDelivery,
            (CmsDelivery.article_id == Article.id) & (CmsDelivery.tenant_id == Article.tenant_id),
        )
        .where(
            Article.tenant_id == tenant_id,
            Article.status.in_(DELIVERABLE),
            or_(
                CmsDelivery.id.is_(None),
                (CmsDelivery.status != "delivered")
                & CmsDelivery.retryable.is_(True)
                & (CmsDelivery.attempts < MAX_ATTEMPTS),
            ),
        )
        .order_by(Article.created_at)
        .limit(limit)
    )
    return list(db.scalars(q))


# --- status sync -----------------------------------------------------------------------------


def sync(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    client_factory: ClientFactory | None = None,
    now: datetime | None = None,
    limit: int = 100,
) -> dict[str, int]:
    """Refresh the CMS status (draft → … → published, or removed) of recent deliveries."""
    now = now or security.utcnow()
    conn = get_connection(db, tenant_id)
    if conn is None or not conn.enabled:
        return {"checked": 0, "changed": 0}
    rows = list(
        db.scalars(
            select(CmsDelivery)
            .where(
                CmsDelivery.tenant_id == tenant_id,
                CmsDelivery.status == "delivered",
                CmsDelivery.remote_id.is_not(None),
                or_(CmsDelivery.remote_status.is_(None), CmsDelivery.remote_status != "removed"),
                CmsDelivery.delivered_at >= now - timedelta(days=SYNC_WINDOW_DAYS),
            )
            .order_by(CmsDelivery.synced_at.nulls_first())
            .limit(limit)
        )
    )
    client = (client_factory or default_client)(conn)
    changed = 0
    for d in rows:
        try:
            doc = client.get_article(str(d.remote_id))
        except CmsError as exc:
            conn.last_error = f"{exc.code}: {exc.message}"[:500]
            break
        new = "removed" if doc is None else _remote_status(doc)
        published = doc.get("publishedAt") if doc else None
        if new != d.remote_status:
            changed += 1
            audit.record(
                db,
                actor_type="system",
                action="cms.status_changed",
                tenant_id=tenant_id,
                target_type="article",
                target_id=d.article_id,
                details={"from": d.remote_status, "to": new},
            )
        d.remote_status = new
        d.remote_published_at = (
            datetime.fromisoformat(published.replace("Z", "+00:00")) if published else None
        )
        d.synced_at = now
    db.flush()
    return {"checked": len(rows), "changed": changed}
