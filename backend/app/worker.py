"""Celery worker and hourly scheduler.

celery -A app.worker worker --loglevel=info --concurrency=2
celery -A app.worker beat --loglevel=info
"""

from __future__ import annotations

import uuid
from typing import Any

from celery import Celery
from celery.schedules import crontab
from sqlalchemy import select

from app.core import security
from app.core.config import get_settings
from app.db.session import new_session, set_tenant_context, system_scope
from app.modules.ai_gateway.gateway import get_extraction_provider
from app.modules.discovery import service as discovery
from app.modules.discovery.adapters import get_search_provider
from app.modules.discovery.safe_fetch import SafeFetcher
from app.modules.research import service as research
from app.modules.tenancy.models import Tenant

MAX_RETRIES = 3

celery_app = Celery("janaki", broker=get_settings().redis_url)
celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    beat_schedule={
        "discovery-hourly": {"task": "discovery.schedule_all", "schedule": crontab(minute=5)},
        "research-hourly": {"task": "research.schedule_all", "schedule": crontab(minute=20)},
    },
)


def _fetcher() -> SafeFetcher:
    s = get_settings()
    return SafeFetcher(timeout=s.fetch_timeout_seconds, max_bytes=s.fetch_max_bytes)


def due_tenants() -> list[uuid.UUID]:
    db = new_session()
    try:
        with system_scope(db):
            tenants = list(db.scalars(select(Tenant).where(Tenant.status == "active")))
        return [t.id for t in tenants if not discovery.discovery_settings(t)["paused"]]
    finally:
        db.rollback()
        db.close()


@celery_app.task(name="discovery.schedule_all")
def schedule_all() -> int:
    now = security.utcnow()
    tenant_ids = due_tenants()
    for tid in tenant_ids:
        run_tenant.delay(str(tid), discovery.scheduled_key(tid, now), "schedule")
    return len(tenant_ids)


def execute(tenant_id: str, key: str, trigger: str) -> dict[str, Any]:
    """Run one discovery job in its own transaction. Separated from Celery for testing."""
    db = new_session()
    fetcher = _fetcher()
    try:
        tid = uuid.UUID(tenant_id)
        set_tenant_context(db, tid)
        job = discovery.run_discovery(
            db,
            tenant_id=tid,
            idempotency_key=key,
            trigger=trigger,
            fetcher=fetcher,
            search=get_search_provider(),
        )
        out = (
            {"status": "already_done"}
            if job is None
            else {"status": job.status, "job_id": str(job.id)}
        )
        db.commit()
        return out
    except Exception:
        db.rollback()
        raise
    finally:
        fetcher.close()
        db.close()


@celery_app.task(name="discovery.run_tenant", bind=True, max_retries=MAX_RETRIES)
def run_tenant(self: Any, tenant_id: str, key: str, trigger: str = "schedule") -> dict[str, Any]:
    out = execute(tenant_id, key, trigger)
    if out["status"] == "failed" and self.request.retries < MAX_RETRIES:
        # Same idempotency key: the job row is reused and URLs are de-duplicated.
        raise self.retry(countdown=60 * 2**self.request.retries)
    return out


def enqueue_manual_run(tenant_id: uuid.UUID) -> str:
    key = f"discovery:{tenant_id}:manual:{uuid.uuid4().hex[:12]}"
    run_tenant.delay(str(tenant_id), key, "manual")
    return key


# --- research (Phase 3) -------------------------------------------------------------------


@celery_app.task(name="research.schedule_all")
def research_schedule_all() -> int:
    """Queue research for each tenant's most-reported new events, within the daily cap."""
    now = security.utcnow()
    queued = 0
    for tid in due_tenants():
        db = new_session()
        try:
            set_tenant_context(db, tid)
            tenant = db.get(Tenant, tid)
            assert tenant is not None
            event_ids = [ev.id for ev in research.events_due(db, tenant, now)]
        finally:
            db.rollback()
            db.close()
        for eid in event_ids:
            research_event.delay(str(tid), str(eid), research.research_key(eid, now), "schedule")
            queued += 1
    return queued


def execute_research(tenant_id: str, event_id: str, key: str, trigger: str) -> dict[str, Any]:
    db = new_session()
    fetcher = _fetcher()
    try:
        tid = uuid.UUID(tenant_id)
        set_tenant_context(db, tid)
        job = research.run_research(
            db,
            tenant_id=tid,
            event_id=uuid.UUID(event_id),
            idempotency_key=key,
            trigger=trigger,
            fetcher=fetcher,
            llm=get_extraction_provider(),
        )
        out: dict[str, Any] = (
            {"status": "already_done"}
            if job is None
            else {
                "status": job.status,
                "job_id": str(job.id),
                "ai_error": job.result.get("ai_error"),
            }
        )
        db.commit()
        return out
    except Exception:
        db.rollback()
        raise
    finally:
        fetcher.close()
        db.close()


@celery_app.task(name="research.run_event", bind=True, max_retries=MAX_RETRIES)
def research_event(
    self: Any, tenant_id: str, event_id: str, key: str, trigger: str = "schedule"
) -> dict[str, Any]:
    out = execute_research(tenant_id, event_id, key, trigger)
    retryable = out.get("ai_error") in ("rate_limited", "provider_error", "network")
    if out["status"] == "failed" and retryable and self.request.retries < MAX_RETRIES:
        # Free tiers reset over time; wait longer each attempt. Extracted documents are not
        # re-sent to the model (claims_extracted_at), so retries do not double-spend quota.
        raise self.retry(countdown=600 * 2**self.request.retries)
    return out


def enqueue_research(tenant_id: uuid.UUID, event_id: uuid.UUID) -> str:
    key = f"research:{event_id}:manual:{uuid.uuid4().hex[:12]}"
    research_event.delay(str(tenant_id), str(event_id), key, "manual")
    return key
