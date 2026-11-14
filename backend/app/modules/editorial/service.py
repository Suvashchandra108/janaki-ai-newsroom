"""Editorial pipeline: eligible event → angle plan → English drafts (A, optional B) → versions.

AI creates drafts only. Editors edit (new version), regenerate (limited) or reject here;
approval and publication happen in the website CMS after delivery (Phase 7).
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import security
from app.core.errors import AppError, Conflict, NotFound
from app.core.principal import Principal
from app.modules.ai_gateway.gateway import AIError, LLMProvider, record_usage
from app.modules.audit import service as audit
from app.modules.discovery import service as discovery
from app.modules.discovery.models import BackgroundJob, NewsEvent
from app.modules.editorial import writer
from app.modules.editorial.models import Article, ArticleVersion
from app.modules.research.models import Claim, Evidence
from app.modules.tenancy.models import Tenant

USABLE_FOR_FACT = ("corroborated", "editor_verified")


def claim_refs(db: Session, event_id: uuid.UUID) -> list[writer.ClaimRef]:
    refs: list[writer.ClaimRef] = []
    claims = db.scalars(
        select(Claim)
        .where(Claim.event_id == event_id)
        .order_by(Claim.independent_sources.desc(), Claim.created_at)
    )
    for i, c in enumerate(claims, start=1):
        ev = list(db.scalars(select(Evidence).where(Evidence.claim_id == c.id)))
        refs.append(
            writer.ClaimRef(
                ref=f"C{i}",
                claim_id=str(c.id),
                text=c.text,
                status=c.status,
                claim_type=c.claim_type,
                publishers=sorted({e.publisher_domain for e in ev if e.relationship == "supports"}),
                excerpts=[e.excerpt for e in ev][:4],
                numbers=list(c.numbers),
            )
        )
    return refs


def eligibility(db: Session, event: NewsEvent) -> tuple[bool, str]:
    if event.status == "draft":
        return False, "already written"
    if event.status != "evidence_assessment":
        return False, f"event is '{event.status}', not yet researched"
    strong = db.scalar(
        select(func.count())
        .select_from(Claim)
        .where(Claim.event_id == event.id, Claim.status.in_(USABLE_FOR_FACT))
    )
    if not strong:
        return False, (
            "no corroborated or editor-verified claim yet; an editor can verify "
            "claims to make this story eligible"
        )
    return True, "eligible"


def _attribution(tenant: Tenant, claims: list[writer.ClaimRef]) -> str:
    pubs = sorted({p for c in claims for p in c.publishers})[:6]
    label = (
        "AI-assisted draft"
        if (tenant.settings.get("attribution") or {}).get("ai_assisted_label", True)
        else "Draft"
    )
    return f"{label} based on reporting by {', '.join(pubs) or 'cited sources'}"[:200]


def _unique_slug(db: Session, tenant_id: uuid.UUID, headline: str) -> str:
    base = writer.slugify(headline)
    slug, n = base, 2
    while db.scalar(select(Article.id).where(Article.tenant_id == tenant_id, Article.slug == slug)):
        slug = f"{base[:74]}-{n}"
        n += 1
    return slug


def _status_for(flags: list[dict[str, Any]]) -> str:
    return "needs_review" if any(f.get("severity") == "warning" for f in flags) else "draft"


def _add_version(
    db: Session,
    article: Article,
    draft: writer.Draft,
    *,
    category: str | None,
    attribution: str,
    kind: str,
    model: str | None,
    user_id: uuid.UUID | None,
    note: str | None,
) -> ArticleVersion:
    version_no = (
        db.scalar(
            select(func.max(ArticleVersion.version)).where(ArticleVersion.article_id == article.id)
        )
        or 0
    ) + 1
    v = ArticleVersion(
        tenant_id=article.tenant_id,
        article_id=article.id,
        version=version_no,
        headline=draft.headline,
        alt_headline=draft.alt_headline,
        summary=draft.summary,
        paragraphs=draft.paragraphs,
        image_caption=draft.image_caption,
        seo_title=draft.seo_title,
        seo_description=draft.seo_description,
        keywords=draft.keywords,
        category=category,
        location=draft.location,
        social=draft.social,
        flags=draft.flags,
        attribution=attribution,
        created_by_kind=kind,
        created_by_user=user_id,
        model=model,
        note=note,
    )
    db.add(v)
    article.current_version = version_no
    if article.status != "rejected":
        article.status = _status_for(draft.flags)
    db.flush()
    return v


def run_writing(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    idempotency_key: str,
    trigger: str,
    llm: LLMProvider | None,
    now: datetime | None = None,
) -> BackgroundJob | None:
    now = now or security.utcnow()
    job = discovery.claim_job(db, tenant_id, idempotency_key, trigger, job_type="writing")
    if job is None:
        return None
    job.attempts += 1
    job.started_at, job.status, job.error = now, "running", None
    event = db.scalar(
        select(NewsEvent).where(NewsEvent.id == event_id, NewsEvent.tenant_id == tenant_id)
    )
    base: dict[str, Any] = {"event_id": str(event_id)}
    if event is None:
        return discovery.finish_job(job, "skipped", {**base, "reason": "event_not_found"})
    ok, reason = eligibility(db, event)
    if not ok:
        return discovery.finish_job(job, "skipped", {**base, "reason": reason})
    if llm is None:
        job.error = "No AI provider configured"
        return discovery.finish_job(job, "failed", {**base, "ai_error": "not_configured"})
    existing = {a.angle for a in db.scalars(select(Article).where(Article.event_id == event.id))}
    if "straight" in existing:
        return discovery.finish_job(job, "skipped", {**base, "reason": "already written"})

    tenant = db.get(Tenant, tenant_id)
    assert tenant is not None
    refs = claim_refs(db, event.id)
    by_ref = {c.ref: c for c in refs}
    stats: Counter[str] = Counter()
    try:
        plan, res = writer.plan_angles(llm, headline=event.title, claims=refs)
        record_usage(db, tenant_id=tenant_id, kind="ai.angle_planning", result=res, job_id=job.id)
        stats["ai_calls"] += 1
        written: dict[str, writer.Draft] = {}
        for angle, refs_used, focus in (
            ("straight", plan.a_refs, None),
            ("context", plan.b_refs, plan.b_focus),
        ):
            if refs_used is None:
                continue
            draft, res = writer.write_article(
                llm,
                headline=event.title,
                angle=angle,
                focus=focus,
                claims=[by_ref[r] for r in refs_used],
            )
            record_usage(db, tenant_id=tenant_id, kind="ai.writing", result=res, job_id=job.id)
            stats["ai_calls"] += 1
            written[angle] = draft
    except AIError as exc:
        job.error = exc.message
        return discovery.finish_job(job, "failed", {**base, **stats, "ai_error": exc.code})

    b_reason = plan.b_reason
    if "context" in written:
        sim = writer.similarity(written["straight"].paragraphs, written["context"].paragraphs)
        if sim > 0.6:
            del written["context"]
            b_reason = f"Article B discarded: too similar to Article A ({sim:.0%} word overlap)"
    used = refs if not plan.a_refs else [by_ref[r] for r in plan.a_refs]
    created = []
    for angle, draft in written.items():
        art = Article(
            tenant_id=tenant_id,
            event_id=event.id,
            angle=angle,
            language="en",
            slug=_unique_slug(db, tenant_id, draft.headline),
            status="draft",
        )
        db.add(art)
        db.flush()
        note = "Generated by AI" + ("" if angle == "context" else f". Article B: {b_reason}")
        _add_version(
            db,
            art,
            draft,
            category=event.category,
            attribution=_attribution(tenant, used),
            kind="ai",
            model=getattr(llm, "model", None),
            user_id=None,
            note=note,
        )
        created.append(
            {
                "article_id": str(art.id),
                "angle": angle,
                "status": art.status,
                "flags": len(draft.flags),
            }
        )
    event.status = "draft"
    return discovery.finish_job(
        job, "succeeded", {**base, **stats, "articles": created, "article_b": b_reason}
    )


def writing_key(event_id: uuid.UUID, now: datetime) -> str:
    return f"writing:{event_id}:{now.strftime('%Y-%m-%d')}"


def events_ready(db: Session, tenant: Tenant) -> list[uuid.UUID]:
    rows = db.scalars(
        select(NewsEvent).where(
            NewsEvent.tenant_id == tenant.id, NewsEvent.status == "evidence_assessment"
        )
    )
    return [e.id for e in rows if eligibility(db, e)[0]]


# --- editor actions ---------------------------------------------------------------------------


def get_article(db: Session, principal: Principal, article_id: uuid.UUID) -> Article:
    art = db.scalar(
        select(Article).where(Article.id == article_id, Article.tenant_id == principal.tenant_id)
    )
    if art is None:
        raise NotFound("Article not found.")
    return art


def current_version(db: Session, art: Article) -> ArticleVersion:
    v = db.scalar(
        select(ArticleVersion).where(
            ArticleVersion.article_id == art.id, ArticleVersion.version == art.current_version
        )
    )
    assert v is not None
    return v


def _require_human(principal: Principal) -> None:
    if principal.kind != "user" or principal.is_service:
        raise AppError("Only a person can do this.", code="human_only", status_code=403)


def edit_article(
    db: Session, principal: Principal, article_id: uuid.UUID, changes: dict[str, Any]
) -> ArticleVersion:
    _require_human(principal)
    art = get_article(db, principal, article_id)
    if art.status in ("rejected", "delivered"):
        raise Conflict(f"A {art.status} article cannot be edited here.")
    cur = current_version(db, art)
    paragraphs = changes.get("paragraphs", cur.paragraphs)
    draft = writer.Draft(
        headline=changes.get("headline", cur.headline),
        alt_headline=changes.get("alt_headline", cur.alt_headline),
        summary=changes.get("summary", cur.summary),
        paragraphs=paragraphs,
        image_caption=changes.get("image_caption", cur.image_caption),
        seo_title=changes.get("seo_title", cur.seo_title),
        seo_description=changes.get("seo_description", cur.seo_description),
        keywords=changes.get("keywords", list(cur.keywords)),
        location=changes.get("location", cur.location),
        social=changes.get("social", dict(cur.social)),
    )
    by_id = {c.claim_id: c for c in claim_refs(db, art.event_id)}
    unknown = {cid for p in paragraphs for cid in p.get("claim_ids", [])} - set(by_id)
    if unknown:
        raise AppError(
            "Paragraphs cite claims that do not belong to this event.",
            code="unknown_claim",
            status_code=422,
        )
    draft.flags = writer.check_text(
        paragraphs, by_id, {"headline": draft.headline, "summary": draft.summary}
    )
    v = _add_version(
        db,
        art,
        draft,
        category=changes.get("category", cur.category),
        attribution=cur.attribution,
        kind="user",
        model=None,
        user_id=principal.user_id,
        note=changes.get("note"),
    )
    audit.record(
        db,
        principal=principal,
        action="article.edited",
        tenant_id=principal.tenant_id,
        target_type="article",
        target_id=art.id,
        details={"version": v.version, "fields": sorted(changes)},
    )
    return v


def regenerate(
    db: Session,
    principal: Principal,
    article_id: uuid.UUID,
    llm: LLMProvider | None,
    max_regenerations: int,
) -> ArticleVersion:
    _require_human(principal)
    art = get_article(db, principal, article_id)
    if art.status in ("rejected", "delivered"):
        raise Conflict(f"A {art.status} article cannot be regenerated.")
    if art.regenerations >= max_regenerations:
        raise AppError(
            f"Regeneration limit reached ({max_regenerations}). Edit the draft instead.",
            code="regeneration_limit",
            status_code=429,
        )
    if llm is None:
        raise AppError("No AI provider configured.", code="ai_not_configured", status_code=503)
    event = db.get(NewsEvent, art.event_id)
    assert event is not None
    refs = claim_refs(db, art.event_id)
    try:
        draft, res = writer.write_article(
            llm, headline=event.title, angle=art.angle, focus=None, claims=refs
        )
    except AIError as exc:
        raise AppError(
            f"AI provider error: {exc.code}",
            code="ai_error",
            status_code=503 if exc.retryable else 502,
        ) from exc
    assert principal.tenant_id
    record_usage(db, tenant_id=principal.tenant_id, kind="ai.writing", result=res, job_id=None)
    art.regenerations += 1
    tenant = db.get(Tenant, principal.tenant_id)
    assert tenant is not None
    v = _add_version(
        db,
        art,
        draft,
        category=event.category,
        attribution=_attribution(tenant, refs),
        kind="ai",
        model=getattr(llm, "model", None),
        user_id=principal.user_id,
        note=f"Regenerated by request ({art.regenerations}/{max_regenerations})",
    )
    audit.record(
        db,
        principal=principal,
        action="article.regenerated",
        tenant_id=principal.tenant_id,
        target_type="article",
        target_id=art.id,
        details={"version": v.version},
    )
    return v


def reject(db: Session, principal: Principal, article_id: uuid.UUID, reason: str) -> Article:
    _require_human(principal)
    art = get_article(db, principal, article_id)
    if art.status == "delivered":
        raise Conflict("Already delivered to the website; reject it there.")
    art.status = "rejected"
    art.rejection_reason = reason.strip()[:1000]
    db.flush()
    audit.record(
        db,
        principal=principal,
        action="article.rejected",
        tenant_id=principal.tenant_id,
        target_type="article",
        target_id=art.id,
    )
    return art
