"""Numbers for the newsroom dashboard.

Every figure is a direct count over the same tables the rest of the API reads, so the dashboard
cannot drift from the records. Nothing is estimated: spending is reported as AI calls and tokens
(no price table is configured), and an unconfigured search provider is reported as such.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import security
from app.modules.ai_gateway.models import UsageRecord
from app.modules.audit.models import AuditLog
from app.modules.cms.models import CmsConnection, CmsDelivery
from app.modules.discovery import service as discovery
from app.modules.discovery.adapters import NullSearchProvider, get_search_provider
from app.modules.discovery.models import BackgroundJob, NewsEvent
from app.modules.editorial.models import Article
from app.modules.research import service as research
from app.modules.research.models import Claim
from app.modules.tenancy.models import Tenant
from app.modules.visuals.models import MediaAsset

AWAITING = ("draft", "needs_review")
STRONG = ("corroborated", "editor_verified")


def _count(db: Session, stmt: Any) -> int:
    return int(db.scalar(stmt) or 0)


def summary(db: Session, tenant: Tenant, now: datetime | None = None) -> dict[str, Any]:
    now = now or security.utcnow()
    tid = tenant.id
    day = discovery.tenant_day_start(tenant, now)
    month = day.replace(day=1)
    status = discovery.status_summary(db, tenant, now)

    def events(*statuses: str) -> int:
        return _count(
            db,
            select(func.count())
            .select_from(NewsEvent)
            .where(NewsEvent.tenant_id == tid, NewsEvent.status.in_(statuses)),
        )

    verified = _count(
        db,
        select(func.count(func.distinct(NewsEvent.id)))
        .select_from(NewsEvent)
        .join(Claim, Claim.event_id == NewsEvent.id)
        .where(
            NewsEvent.tenant_id == tid,
            NewsEvent.status == "evidence_assessment",
            Claim.status.in_(STRONG),
        ),
    )
    usage = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(UsageRecord.input_tokens), 0),
            func.coalesce(func.sum(UsageRecord.output_tokens), 0),
        ).where(UsageRecord.tenant_id == tid, UsageRecord.created_at >= day)
    ).one()
    usage_month = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(UsageRecord.input_tokens + UsageRecord.output_tokens), 0),
        ).where(UsageRecord.tenant_id == tid, UsageRecord.created_at >= month)
    ).one()
    conn = db.scalar(select(CmsConnection).where(CmsConnection.tenant_id == tid))
    search = get_search_provider()
    cap = research.daily_event_cap(tenant)
    researched = research.researched_today(db, tenant, now)
    illus_limit = int((tenant.settings.get("generation") or {}).get("max_illustrations_per_day", 3))
    return {
        "as_of": now,
        "day_start": day,
        "discovery": {
            "items_today": status["items_today"],
            "daily_item_quota": status["daily_item_quota"],
            "quota_remaining": status["quota_remaining"],
            "paused": status["paused"],
            "next_scheduled_run": status["next_scheduled_run"],
            "events_today": _count(
                db,
                select(func.count())
                .select_from(NewsEvent)
                .where(NewsEvent.tenant_id == tid, NewsEvent.first_seen_at >= day),
            ),
        },
        "pipeline": {
            "discovered": events("discovered"),
            "researching": events("researching"),
            "verified_candidates": verified,
            "generating": events("generating"),
            "research_cap": cap,
            "research_remaining": max(cap - researched, 0),
        },
        "articles": {
            "generated_today": _count(
                db,
                select(func.count())
                .select_from(Article)
                .where(Article.tenant_id == tid, Article.created_at >= day),
            ),
            "awaiting_review": _count(
                db,
                select(func.count())
                .select_from(Article)
                .where(Article.tenant_id == tid, Article.status.in_(AWAITING)),
            ),
            "needs_review": _count(
                db,
                select(func.count())
                .select_from(Article)
                .where(Article.tenant_id == tid, Article.status == "needs_review"),
            ),
            "rejected": _count(
                db,
                select(func.count())
                .select_from(Article)
                .where(Article.tenant_id == tid, Article.status == "rejected"),
            ),
            "sent_to_website": _count(
                db,
                select(func.count())
                .select_from(CmsDelivery)
                .where(
                    CmsDelivery.tenant_id == tid,
                    CmsDelivery.status == "delivered",
                    CmsDelivery.remote_status.is_distinct_from("published"),
                ),
            ),
            "published": _count(
                db,
                select(func.count())
                .select_from(CmsDelivery)
                .where(CmsDelivery.tenant_id == tid, CmsDelivery.remote_status == "published"),
            ),
        },
        "failures": {
            "jobs_24h": _count(
                db,
                select(func.count())
                .select_from(BackgroundJob)
                .where(
                    BackgroundJob.tenant_id == tid,
                    BackgroundJob.status == "failed",
                    BackgroundJob.created_at >= now - timedelta(hours=24),
                ),
            ),
            "deliveries": _count(
                db,
                select(func.count())
                .select_from(CmsDelivery)
                .where(CmsDelivery.tenant_id == tid, CmsDelivery.status == "failed"),
            ),
        },
        "usage": {
            "ai_calls_today": int(usage[0]),
            "ai_input_tokens_today": int(usage[1]),
            "ai_output_tokens_today": int(usage[2]),
            "ai_calls_month": int(usage_month[0]),
            "ai_tokens_month": int(usage_month[1]),
            "ai_cost_known": False,  # no price table is configured; tokens are reported instead
            "search_provider": None
            if isinstance(search, NullSearchProvider)
            else getattr(search, "name", "configured"),
            "images_selected_month": _count(
                db,
                select(func.count())
                .select_from(MediaAsset)
                .where(
                    MediaAsset.tenant_id == tid,
                    MediaAsset.status == "selected",
                    MediaAsset.selected_at >= month,
                ),
            ),
            "illustrations_today": _count(
                db,
                select(func.count())
                .select_from(MediaAsset)
                .where(
                    MediaAsset.tenant_id == tid,
                    MediaAsset.ai_generated.is_(True),
                    MediaAsset.created_at >= day,
                ),
            ),
            "illustrations_limit": illus_limit,
        },
        "cms": {
            "connected": conn is not None and conn.enabled,
            "base_url": conn.base_url if conn else None,
            "auto_deliver": bool(conn and conn.auto_deliver),
            "last_error": conn.last_error if conn else None,
        },
    }


# --- notifications ---------------------------------------------------------------------------

NOTIFY_ACTIONS = ("cms.draft_delivered", "cms.delivery_failed", "cms.status_changed")


def notifications(
    db: Session, tenant: Tenant, *, limit: int = 30, now: datetime | None = None
) -> list[dict[str, Any]]:
    """What changed recently, newest first: failed jobs, new drafts, website deliveries and
    website status changes. Derived from existing records; nothing is stored separately."""
    now = now or security.utcnow()
    since = now - timedelta(days=7)
    out: list[dict[str, Any]] = []
    for j in db.scalars(
        select(BackgroundJob)
        .where(
            BackgroundJob.tenant_id == tenant.id,
            BackgroundJob.status == "failed",
            BackgroundJob.created_at >= since,
        )
        .order_by(BackgroundJob.created_at.desc())
        .limit(limit)
    ):
        out.append(
            {
                "kind": "job_failed",
                "severity": "error",
                "at": j.finished_at or j.created_at,
                "target_type": "job",
                "target_id": str(j.id),
                "data": {"job_type": j.job_type, "error": (j.error or "")[:200]},
            }
        )
    for a in db.scalars(
        select(Article)
        .where(Article.tenant_id == tenant.id, Article.created_at >= since)
        .order_by(Article.created_at.desc())
        .limit(limit)
    ):
        out.append(
            {
                "kind": "draft_ready",
                "severity": "warning" if a.status == "needs_review" else "info",
                "at": a.created_at,
                "target_type": "article",
                "target_id": str(a.id),
                "data": {"slug": a.slug, "status": a.status, "angle": a.angle},
            }
        )
    for log in db.scalars(
        select(AuditLog)
        .where(
            AuditLog.tenant_id == tenant.id,
            AuditLog.action.in_(NOTIFY_ACTIONS),
            AuditLog.created_at >= since,
        )
        .order_by(AuditLog.id.desc())
        .limit(limit)
    ):
        kind = {
            "cms.draft_delivered": "sent_to_website",
            "cms.delivery_failed": "delivery_failed",
            "cms.status_changed": "website_status",
        }[log.action]
        out.append(
            {
                "kind": kind,
                "severity": "error" if kind == "delivery_failed" else "info",
                "at": log.created_at,
                "target_type": log.target_type,
                "target_id": log.target_id,
                "data": {
                    k: v
                    for k, v in (log.details or {}).items()
                    if k in ("to", "from", "error", "retryable", "remote_id")
                },
            }
        )
    out.sort(key=lambda n: n["at"], reverse=True)
    return out[:limit]
