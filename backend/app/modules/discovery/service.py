"""News discovery: approved sources, ingestion, de-duplication, clustering, quotas, jobs."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core import security
from app.core.config import get_settings
from app.core.errors import AppError, Conflict, NotFound
from app.core.principal import Principal
from app.modules.audit import service as audit
from app.modules.discovery import text
from app.modules.discovery.adapters import Lead, SearchProvider, parse_feed
from app.modules.discovery.models import BackgroundJob, DiscoveredItem, NewsEvent, NewsSource
from app.modules.discovery.safe_fetch import (
    FetchError,
    SafeFetcher,
    host_allowed,
    normalise_domain,
    validate_url,
)
from app.modules.tenancy.models import Tenant

_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](-?[a-z0-9])*\.)+[a-z]{2,63}$")
SOURCE_FIELDS = (
    "name",
    "feed_url",
    "search_query",
    "allowed_domains",
    "language",
    "country",
    "region",
    "category",
    "priority",
    "credibility",
    "credibility_notes",
    "is_enabled",
)


# --- sources ------------------------------------------------------------------------------


def _validate_source(kind: str, data: dict[str, Any]) -> None:
    domains = [normalise_domain(d) for d in data.get("allowed_domains") or []]
    if not domains or len(domains) > 20 or not all(_DOMAIN_RE.match(d) for d in domains):
        raise AppError(
            "allowed_domains must contain 1 to 20 valid domain names.",
            code="invalid_source",
            status_code=422,
        )
    data["allowed_domains"] = sorted(set(domains))
    if kind == "rss":
        url = data.get("feed_url")
        if not url:
            raise AppError("RSS sources need a feed_url.", code="invalid_source", status_code=422)
        try:
            validate_url(url, data["allowed_domains"])
        except FetchError as exc:
            raise AppError(
                f"feed_url rejected: {exc.message}", code="invalid_source", status_code=422
            ) from exc
    elif not data.get("search_query"):
        raise AppError(
            "Search sources need a search_query.", code="invalid_source", status_code=422
        )


def create_source(db: Session, principal: Principal, data: dict[str, Any]) -> NewsSource:
    assert principal.tenant_id
    kind = data.pop("kind", "rss")
    _validate_source(kind, data)
    src = NewsSource(
        tenant_id=principal.tenant_id,
        kind=kind,
        **{k: v for k, v in data.items() if k in SOURCE_FIELDS},
    )
    db.add(src)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError as exc:
        raise Conflict("This feed is already registered.") from exc
    audit.record(
        db,
        principal=principal,
        action="source.created",
        tenant_id=principal.tenant_id,
        target_type="news_source",
        target_id=src.id,
        details={"kind": kind, "domains": src.allowed_domains},
    )
    return src


def get_source(db: Session, principal: Principal, source_id: uuid.UUID) -> NewsSource:
    src = db.scalar(
        select(NewsSource).where(
            NewsSource.id == source_id, NewsSource.tenant_id == principal.tenant_id
        )
    )
    if src is None:
        raise NotFound("Source not found.")
    return src


def update_source(
    db: Session, principal: Principal, source_id: uuid.UUID, changes: dict[str, Any]
) -> NewsSource:
    src = get_source(db, principal, source_id)
    merged = {k: getattr(src, k) for k in SOURCE_FIELDS} | changes
    _validate_source(src.kind, merged)
    for k in changes:
        setattr(src, k, merged[k])
    if changes.get("is_enabled"):
        src.consecutive_failures = 0
    db.flush()
    audit.record(
        db,
        principal=principal,
        action="source.updated",
        tenant_id=principal.tenant_id,
        target_type="news_source",
        target_id=src.id,
        details={"fields": sorted(changes)},
    )
    return src


def list_sources(db: Session, tenant_id: uuid.UUID) -> list[NewsSource]:
    return list(
        db.scalars(
            select(NewsSource)
            .where(NewsSource.tenant_id == tenant_id)
            .order_by(NewsSource.priority.desc(), NewsSource.name)
        )
    )


# --- tenant discovery settings --------------------------------------------------------------


def discovery_settings(tenant: Tenant) -> dict[str, Any]:
    d = dict(tenant.settings.get("discovery") or {})
    d.setdefault("daily_item_quota", 100)
    d.setdefault("paused", False)
    d.setdefault("interval_minutes", 60)
    return d


def set_paused(db: Session, principal: Principal, paused: bool) -> Tenant:
    tenant = db.get(Tenant, principal.tenant_id)
    if tenant is None:
        raise NotFound("Tenant not found.")
    settings = dict(tenant.settings)
    settings["discovery"] = {**discovery_settings(tenant), "paused": paused}
    tenant.settings = settings
    flag_modified(tenant, "settings")
    db.flush()
    audit.record(
        db,
        principal=principal,
        action="discovery.paused" if paused else "discovery.resumed",
        tenant_id=tenant.id,
    )
    return tenant


def tenant_day_start(tenant: Tenant, now: datetime) -> datetime:
    tz = ZoneInfo(tenant.settings.get("timezone") or "Asia/Kathmandu")
    local = now.astimezone(tz)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def items_today(db: Session, tenant: Tenant, now: datetime) -> int:
    start = tenant_day_start(tenant, now)
    return int(
        db.scalar(
            select(func.count())
            .select_from(DiscoveredItem)
            .where(DiscoveredItem.tenant_id == tenant.id, DiscoveredItem.retrieved_at >= start)
        )
        or 0
    )


def next_scheduled_run(now: datetime) -> datetime:
    """Beat runs at minute 5 of every hour (app/worker.py)."""
    candidate = now.replace(minute=5, second=0, microsecond=0)
    return candidate if candidate > now else candidate + timedelta(hours=1)


def scheduled_key(tenant_id: uuid.UUID, now: datetime) -> str:
    return f"discovery:{tenant_id}:{now.strftime('%Y-%m-%dT%H')}"


# --- the discovery run ---------------------------------------------------------------------


@dataclass
class _Cluster:
    event: NewsEvent
    domains: set[str] = field(default_factory=set)


def _claim_job(db: Session, tenant_id: uuid.UUID, key: str, trigger: str) -> BackgroundJob | None:
    """Return the job to run, or None if this key already ran (idempotency)."""
    db.execute(
        pg_insert(BackgroundJob)
        .values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            job_type="discovery",
            idempotency_key=key,
            trigger=trigger,
            status="queued",
            attempts=0,
            result={},
        )
        .on_conflict_do_nothing(constraint="uq_background_jobs_tenant_key")
    )
    job = db.scalar(
        select(BackgroundJob)
        .where(BackgroundJob.tenant_id == tenant_id, BackgroundJob.idempotency_key == key)
        .with_for_update()
    )
    assert job is not None
    if job.status in ("succeeded", "partial", "skipped", "running"):
        return None
    return job


def _load_recent_clusters(db: Session, tenant_id: uuid.UUID, now: datetime) -> list[_Cluster]:
    since = now - timedelta(hours=get_settings().discovery_cluster_window_hours)
    events = db.scalars(
        select(NewsEvent).where(NewsEvent.tenant_id == tenant_id, NewsEvent.last_seen_at >= since)
    )
    clusters = []
    for ev in events:
        domains = set(
            db.scalars(
                select(DiscoveredItem.publisher_domain)
                .where(DiscoveredItem.event_id == ev.id)
                .distinct()
            )
        )
        clusters.append(_Cluster(ev, domains))
    return clusters


def _ingest(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    source: NewsSource,
    lead: Lead,
    job: BackgroundJob,
    clusters: list[_Cluster],
    stats: dict[str, int],
    now: datetime,
) -> bool:
    """Store one lead. Returns True if a new item was stored."""
    canon = text.canonical_url(lead.url)
    url_hash = text.sha256(canon)
    exists = db.scalar(
        select(DiscoveredItem.id).where(
            DiscoveredItem.tenant_id == tenant_id, DiscoveredItem.url_hash == url_hash
        )
    )
    if exists:
        stats["duplicates"] += 1
        return False
    kw = text.keywords(lead.title)
    shash = text.simhash64(text.tokens(lead.title))
    domain = text.domain_of(lead.url)

    match = next(
        (
            c
            for c in clusters
            if c.event.language == source.language
            and text.same_event(kw, shash, list(c.event.keywords), c.event.title_simhash)
        ),
        None,
    )
    if match is None:
        ev = NewsEvent(
            tenant_id=tenant_id,
            title=lead.title,
            keywords=kw,
            title_simhash=shash,
            language=source.language,
            category=source.category,
            region=source.region,
            first_seen_at=now,
            last_seen_at=now,
            item_count=0,
            publisher_count=0,
        )
        db.add(ev)
        db.flush()
        match = _Cluster(ev)
        clusters.append(match)
        stats["events_new"] += 1
    else:
        stats["events_updated"] += 1

    item = DiscoveredItem(
        tenant_id=tenant_id,
        source_id=source.id,
        event_id=match.event.id,
        job_id=job.id,
        url=lead.url,
        canonical_url=canon,
        url_hash=url_hash,
        publisher_domain=domain,
        title=lead.title,
        description=lead.description or None,
        author=lead.author,
        language=source.language,
        category=source.category,
        region=source.region,
        published_at=lead.published_at,
        retrieved_at=now,
        content_fingerprint=text.sha256(f"{lead.title}\n{lead.description}"),
        title_simhash=shash,
    )
    try:
        with db.begin_nested():
            db.add(item)
            db.flush()
    except IntegrityError:  # concurrent insert of the same URL
        stats["duplicates"] += 1
        return False
    match.domains.add(domain)
    match.event.item_count += 1
    match.event.publisher_count = len(match.domains)
    match.event.last_seen_at = now
    stats["items_new"] += 1
    return True


def _leads_for(
    source: NewsSource, fetcher: SafeFetcher, search: SearchProvider | None
) -> list[Lead]:
    if source.kind == "rss":
        assert source.feed_url
        res = fetcher.fetch(source.feed_url, source.allowed_domains)
        return parse_feed(res.body)
    if search is None:
        raise RuntimeError("No search provider configured")
    leads = search.search(source.search_query or "", language=source.language, limit=20)
    # Search results are kept only when the publisher is on the source's approved list.
    return [
        lead for lead in leads if host_allowed(text.domain_of(lead.url), source.allowed_domains)
    ]


def run_discovery(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    idempotency_key: str,
    trigger: str,
    fetcher: SafeFetcher,
    search: SearchProvider | None = None,
    now: datetime | None = None,
) -> BackgroundJob | None:
    """Run discovery for one tenant. Caller must have set the tenant context.

    Returns the job, or None when this idempotency key has already completed.
    """
    now = now or security.utcnow()
    job = _claim_job(db, tenant_id, idempotency_key, trigger)
    if job is None:
        return None
    tenant = db.get(Tenant, tenant_id)
    assert tenant is not None
    job.attempts += 1
    job.started_at = now
    job.status = "running"
    job.error = None
    db.flush()

    cfg = discovery_settings(tenant)
    if tenant.status != "active" or cfg["paused"]:
        return _finish(job, "skipped", {"reason": "paused" if cfg["paused"] else "suspended"})
    remaining = int(cfg["daily_item_quota"]) - items_today(db, tenant, now)
    if remaining <= 0:
        return _finish(job, "skipped", {"reason": "daily_quota_exhausted", "quota_remaining": 0})

    sources = list(
        db.scalars(
            select(NewsSource)
            .where(NewsSource.tenant_id == tenant_id, NewsSource.is_enabled.is_(True))
            .order_by(NewsSource.priority.desc(), NewsSource.created_at)
        )
    )
    clusters = _load_recent_clusters(db, tenant_id, now)
    stats = {"items_new": 0, "duplicates": 0, "events_new": 0, "events_updated": 0}
    errors: list[dict[str, str]] = []
    ok = 0
    for source in sources:
        if remaining <= 0:
            break
        try:
            leads = _leads_for(source, fetcher, search)
        except (FetchError, ValueError, RuntimeError) as exc:
            code = getattr(exc, "code", type(exc).__name__)
            source.last_error = f"{code}: {exc}"[:500]
            source.consecutive_failures += 1
            source.last_fetched_at = now
            errors.append({"source_id": str(source.id), "error": source.last_error})
            continue
        ok += 1
        source.last_error = None
        source.consecutive_failures = 0
        source.last_fetched_at = now
        for lead in sorted(leads, key=lambda le: le.published_at or now, reverse=True):
            if remaining <= 0:
                break
            if _ingest(
                db,
                tenant_id=tenant_id,
                source=source,
                lead=lead,
                job=job,
                clusters=clusters,
                stats=stats,
                now=now,
            ):
                remaining -= 1
    db.flush()

    result: dict[str, Any] = {
        **stats,
        "sources_ok": ok,
        "sources_failed": len(errors),
        "quota_remaining": max(remaining, 0),
        "errors": errors[:20],
    }
    if errors and ok == 0:
        status = "failed"
    elif errors:
        status = "partial"
    else:
        status = "succeeded"
    _finish(job, status, result)
    if status == "failed":
        job.error = "All sources failed"
    return job


def _finish(job: BackgroundJob, status: str, result: dict[str, Any]) -> BackgroundJob:
    job.status = status
    job.result = result
    job.finished_at = security.utcnow()
    return job


# --- read models ---------------------------------------------------------------------------


def status_summary(db: Session, tenant: Tenant, now: datetime | None = None) -> dict[str, Any]:
    now = now or security.utcnow()
    cfg = discovery_settings(tenant)
    used = items_today(db, tenant, now)
    last = db.scalar(
        select(BackgroundJob)
        .where(BackgroundJob.tenant_id == tenant.id)
        .order_by(BackgroundJob.created_at.desc())
        .limit(1)
    )
    return {
        "paused": cfg["paused"],
        "daily_item_quota": cfg["daily_item_quota"],
        "items_today": used,
        "quota_remaining": max(int(cfg["daily_item_quota"]) - used, 0),
        "next_scheduled_run": None if cfg["paused"] else next_scheduled_run(now),
        "last_job_status": last.status if last else None,
        "last_job_at": last.created_at if last else None,
    }
