"""Visuals pipeline: licensed photo candidates, selection (download + derivatives), charts,
AI illustrations. Editors choose; nothing is attached to an article automatically."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import get_settings
from app.core.errors import AppError, Conflict, NotFound
from app.core.principal import Principal
from app.modules.audit import service as audit
from app.modules.discovery.models import NewsEvent
from app.modules.discovery.safe_fetch import FetchError, SafeFetcher
from app.modules.editorial.models import Article
from app.modules.research.models import Claim, Evidence
from app.modules.visuals import charts, commons, licences
from app.modules.visuals.illustrations import LABEL, ImageGenerator, build_prompt
from app.modules.visuals.models import MediaAsset
from app.modules.visuals.processing import ImageRejected, process
from app.modules.visuals.storage import Storage, media_key


def _event(db: Session, principal: Principal, event_id: uuid.UUID) -> NewsEvent:
    ev = db.scalar(
        select(NewsEvent).where(
            NewsEvent.id == event_id, NewsEvent.tenant_id == principal.tenant_id
        )
    )
    if ev is None:
        raise NotFound("Event not found.")
    return ev


def get_asset(db: Session, principal: Principal, asset_id: uuid.UUID) -> MediaAsset:
    a = db.scalar(
        select(MediaAsset).where(
            MediaAsset.id == asset_id, MediaAsset.tenant_id == principal.tenant_id
        )
    )
    if a is None:
        raise NotFound("Media not found.")
    return a


def _require_human(principal: Principal) -> None:
    if principal.kind != "user" or principal.is_service:
        raise AppError("Only a person can do this.", code="human_only", status_code=403)


def search_query(event: NewsEvent) -> str:
    """Place and topic words from the headline; Commons search works best with few terms."""
    words = [w for w in event.keywords if len(w) > 3][:4]
    if event.region:
        words.insert(0, event.region)
    return " ".join(dict.fromkeys(words))[:120] or event.title[:80]


# --- photo candidates -------------------------------------------------------------------------


def find_photos(
    db: Session,
    principal: Principal,
    event_id: uuid.UUID,
    fetcher: SafeFetcher,
    query: str | None = None,
    now: datetime | None = None,
) -> list[MediaAsset]:
    now = now or security.utcnow()
    ev = _event(db, principal, event_id)
    q = (query or search_query(ev)).strip()
    try:
        results = commons.search(fetcher, q)
    except (FetchError, ValueError) as exc:
        raise AppError(
            "Image search is unavailable right now.", code="image_search_failed", status_code=502
        ) from exc
    created = []
    for r in results:
        if db.scalar(
            select(MediaAsset.id).where(
                MediaAsset.event_id == ev.id, MediaAsset.original_url == r.original_url
            )
        ):
            continue
        ok = licences.publishable(r.licence, r.attribution_text)
        a = MediaAsset(
            tenant_id=ev.tenant_id,
            event_id=ev.id,
            kind="photo",
            status="candidate",
            provider="wikimedia_commons",
            source_page_url=r.page_url,
            original_url=r.original_url,
            title=r.title,
            description=r.description,
            creator=r.creator,
            credit=r.credit,
            retrieved_at=now,
            licence_name=r.licence.name,
            licence_url=r.licence.url,
            attribution_required=r.licence.attribution_required,
            attribution_text=r.attribution_text,
            commercial_use=r.licence.commercial_use,
            modification_allowed=r.licence.modification_allowed,
            restrictions=r.restrictions,
            publishable=ok,
            licence_notes=r.licence.note,
            mime=r.mime,
            width=r.width,
            height=r.height,
            processing_history=[
                {
                    "at": now.isoformat(),
                    "step": "found",
                    "detail": f"Commons search: {q}",
                    "download_url": r.download_url,
                }
            ],
        )
        db.add(a)
        created.append(a)
    db.flush()
    audit.record(
        db,
        principal=principal,
        action="media.search",
        tenant_id=ev.tenant_id,
        target_type="news_event",
        target_id=ev.id,
        details={"query": q, "found": len(results), "new": len(created)},
    )
    return created


def _download_and_store(
    db: Session, a: MediaAsset, fetcher: SafeFetcher, storage: Storage, now: datetime
) -> None:
    url = str(
        next(
            (h["download_url"] for h in a.processing_history if h.get("download_url")),
            a.original_url,
        )
    )
    try:
        res = fetcher.fetch(
            url,
            commons.DOMAINS,
            content_types=commons.IMAGE_MIMES,
            max_bytes=get_settings().media_max_download_bytes,
        )
        p = process(res.body)
    except FetchError as exc:
        raise AppError(
            f"Could not download the image ({exc.code}).", code="download_failed", status_code=502
        ) from exc
    except ImageRejected as exc:
        raise AppError(
            f"The file was rejected: {exc}.", code="image_rejected", status_code=422
        ) from exc
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[p.mime]
    source_key = media_key(a.tenant_id, a.id, f"source.{ext}")
    storage.put(source_key, res.body, p.mime)
    derivs = []
    for name, data, info in p.derivatives:
        key = media_key(a.tenant_id, a.id, name)
        storage.put(key, data, info["mime"])
        derivs.append({"name": name, "key": key, **info, "bytes": len(data)})
    a.storage_key, a.derivatives, a.sha256 = source_key, derivs, p.sha256
    a.mime, a.width, a.height = p.mime, p.width, p.height
    a.processing_history = [
        *a.processing_history,
        {"at": now.isoformat(), "step": "downloaded", "detail": url},
        {
            "at": now.isoformat(),
            "step": "derivatives",
            "detail": "proportional resize to "
            + ", ".join(d["name"] for d in derivs)
            + "; metadata stripped; no crop or colour change",
        },
    ]


def select_asset(
    db: Session,
    principal: Principal,
    asset_id: uuid.UUID,
    *,
    article_id: uuid.UUID | None,
    role: str,
    caption: str | None,
    fetcher: SafeFetcher,
    storage: Storage,
) -> MediaAsset:
    _require_human(principal)
    a = get_asset(db, principal, asset_id)
    if not a.publishable:
        raise Conflict(
            "This image cannot be used: " + (a.licence_notes or "licence not established") + "."
        )
    if article_id is not None:
        art = db.scalar(
            select(Article).where(
                Article.id == article_id, Article.tenant_id == principal.tenant_id
            )
        )
        if art is None or art.event_id != a.event_id:
            raise AppError(
                "The article must belong to the same story.", code="wrong_article", status_code=422
            )
    now = security.utcnow()
    if a.kind == "photo" and a.storage_key is None:
        _download_and_store(db, a, fetcher, storage, now)
    a.status, a.article_id, a.role = "selected", article_id, role
    credit = a.attribution_text or a.credit
    base_caption = (caption or a.caption or a.title).strip()
    if a.ai_generated and LABEL not in base_caption:
        base_caption = f"{base_caption} ({LABEL})"
    a.caption = (
        f"{base_caption} — {credit}" if credit and credit not in base_caption else base_caption
    )[:500]
    a.selected_by, a.selected_at = principal.user_id, now
    db.flush()
    audit.record(
        db,
        principal=principal,
        action="media.selected",
        tenant_id=a.tenant_id,
        target_type="media_asset",
        target_id=a.id,
        details={"article_id": str(article_id) if article_id else None, "licence": a.licence_name},
    )
    return a


def reject_asset(db: Session, principal: Principal, asset_id: uuid.UUID) -> MediaAsset:
    _require_human(principal)
    a = get_asset(db, principal, asset_id)
    a.status, a.article_id, a.role = "rejected", None, None
    db.flush()
    audit.record(
        db,
        principal=principal,
        action="media.rejected",
        tenant_id=a.tenant_id,
        target_type="media_asset",
        target_id=a.id,
    )
    return a


# --- charts -----------------------------------------------------------------------------------


def make_chart(
    db: Session, principal: Principal, event_id: uuid.UUID, storage: Storage
) -> MediaAsset:
    ev = _event(db, principal, event_id)
    claims = []
    for c in db.scalars(select(Claim).where(Claim.event_id == ev.id)):
        pubs = sorted(
            set(
                db.scalars(
                    select(Evidence.publisher_domain).where(
                        Evidence.claim_id == c.id, Evidence.relationship == "supports"
                    )
                )
            )
        )
        claims.append(
            {
                "id": str(c.id),
                "text": c.text,
                "status": c.status,
                "numbers": list(c.numbers),
                "publishers": pubs,
            }
        )
    now = security.utcnow()
    spec, reason = charts.chart_spec(claims, title=ev.title, as_of=now)
    if spec is None:
        raise AppError(reason, code="no_chart_data", status_code=422)
    svg = charts.render_svg(spec)
    a = MediaAsset(
        tenant_id=ev.tenant_id,
        event_id=ev.id,
        kind="chart",
        status="candidate",
        provider="newsroom_chart",
        original_url=f"chart:{ev.id}:{now.isoformat()}",
        title=f"Chart: {ev.title}"[:500],
        creator="Janaki AI Newsroom",
        retrieved_at=now,
        licence_name="Own work",
        attribution_required=False,
        commercial_use=True,
        modification_allowed=True,
        restrictions=[],
        publishable=True,
        chart_spec=spec,
        mime="image/svg+xml",
        caption=f"Source: {', '.join(spec['sources'])}; as of {spec['as_of']}",
        processing_history=[
            {
                "at": now.isoformat(),
                "step": "chart",
                "detail": f"bar chart from {len(spec['data'])} verified figures",
            }
        ],
    )
    db.add(a)
    db.flush()
    a.storage_key = media_key(a.tenant_id, a.id, "chart.svg")
    storage.put(a.storage_key, svg, "image/svg+xml")
    db.flush()
    return a


# --- AI illustrations -------------------------------------------------------------------------


def illustrations_today(db: Session, tenant_id: uuid.UUID, now: datetime) -> int:
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(
        db.scalar(
            select(func.count())
            .select_from(MediaAsset)
            .where(
                MediaAsset.tenant_id == tenant_id,
                MediaAsset.ai_generated.is_(True),
                MediaAsset.created_at >= start,
            )
        )
        or 0
    )


def make_illustration(
    db: Session,
    principal: Principal,
    event_id: uuid.UUID,
    generator: ImageGenerator | None,
    storage: Storage,
    daily_limit: int,
) -> MediaAsset:
    _require_human(principal)
    ev = _event(db, principal, event_id)
    if generator is None:
        raise AppError(
            "No image-generation provider is configured.", code="ai_not_configured", status_code=503
        )
    now = security.utcnow()
    if illustrations_today(db, ev.tenant_id, now) >= daily_limit:
        raise AppError(
            f"Daily AI illustration limit reached ({daily_limit}).",
            code="illustration_limit",
            status_code=429,
        )
    usable_photo = db.scalar(
        select(MediaAsset.id).where(
            MediaAsset.event_id == ev.id,
            MediaAsset.kind == "photo",
            MediaAsset.publishable.is_(True),
            MediaAsset.status != "rejected",
        )
    )
    if usable_photo:
        raise Conflict(
            "A licensed photo is available for this story; review it first. "
            "Reject it if unsuitable, then an illustration can be generated."
        )
    # Place and section only: headline words can contain people's names.
    prompt = build_prompt(category=ev.category, location=ev.region, topic_keywords=[])
    data = generator.generate(prompt)
    p = process(data)
    a = MediaAsset(
        tenant_id=ev.tenant_id,
        event_id=ev.id,
        kind="illustration",
        status="candidate",
        provider="ai_image",
        original_url=f"ai:{uuid.uuid4()}",
        title=f"Illustration: {ev.title}"[:500],
        creator=f"AI ({generator.name}/{generator.model})",
        retrieved_at=now,
        licence_name="AI-generated (provider terms)",
        attribution_required=False,
        commercial_use=True,
        modification_allowed=True,
        restrictions=[],
        publishable=True,
        ai_generated=True,
        label=LABEL,
        caption=LABEL,
        mime=p.mime,
        width=p.width,
        height=p.height,
        sha256=p.sha256,
        processing_history=[{"at": now.isoformat(), "step": "generated", "detail": prompt}],
    )
    db.add(a)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError as exc:  # pragma: no cover - guarded by the DB constraint
        raise AppError("Illustration failed policy checks.", code="policy") from exc
    derivs = []
    for name, blob, info in p.derivatives:
        key = media_key(a.tenant_id, a.id, name)
        storage.put(key, blob, info["mime"])
        derivs.append({"name": name, "key": key, **info, "bytes": len(blob)})
    a.derivatives = derivs
    a.storage_key = derivs[0]["key"]
    db.flush()
    audit.record(
        db,
        principal=principal,
        action="media.illustration_generated",
        tenant_id=ev.tenant_id,
        target_type="media_asset",
        target_id=a.id,
    )
    return a


def media_for_event(db: Session, principal: Principal, event_id: uuid.UUID) -> list[MediaAsset]:
    ev = _event(db, principal, event_id)
    return list(
        db.scalars(
            select(MediaAsset)
            .where(MediaAsset.event_id == ev.id)
            .order_by(MediaAsset.publishable.desc(), MediaAsset.created_at)
        )
    )
