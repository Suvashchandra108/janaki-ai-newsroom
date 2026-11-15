"""Acceptance (Phase 6): dashboard numbers equal the backend records; failed jobs are visible."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.modules.discovery.models import BackgroundJob, NewsEvent
from app.modules.editorial.models import Article
from tests.conftest import auth, login, make_tenant, make_user
from tests.test_cms import env  # noqa: F401  (fixture: researched event, 2 drafts, CMS connected)
from tests.test_discovery_run import tenant_db


def _failed_job(tenant_id: Any) -> None:
    with tenant_db(tenant_id) as db:
        db.add(
            BackgroundJob(
                tenant_id=tenant_id,
                job_type="research",
                idempotency_key="research:test-failure",
                trigger="test",
                status="failed",
                attempts=1,
                error="Provider quota exceeded",
                result={"ai_error": "rate_limited"},
            )
        )


def test_summary_matches_the_records(client: TestClient, env) -> None:  # noqa: F811
    t, h = env["t"], env["h"]
    r = client.post(f"/api/v1/articles/{env['a']}/deliver", headers=h)
    assert r.json()["status"] == "delivered"
    fake = env["fake"]
    fake.articles[int(r.json()["remote_id"])].update(
        status="published", publishedAt="2026-11-15T06:00:00.000Z"
    )
    client.post("/api/v1/cms/sync", headers=h)
    _failed_job(t.tenant_id)

    s = client.get("/api/v1/dashboard/summary", headers=h).json()
    with tenant_db(t.tenant_id) as db:
        articles = list(db.scalars(select(Article)))
        events = {e.status: 0 for e in db.scalars(select(NewsEvent))}
        for e in db.scalars(select(NewsEvent)):
            events[e.status] += 1
        failed = db.scalar(
            select(func.count()).select_from(BackgroundJob).where(BackgroundJob.status == "failed")
        )
    assert s["articles"]["generated_today"] == len(articles) == 2
    assert s["articles"]["awaiting_review"] == sum(
        a.status in ("draft", "needs_review") for a in articles
    )
    assert s["articles"]["published"] == 1 and s["articles"]["sent_to_website"] == 0
    assert s["failures"]["jobs_24h"] == failed == 1
    assert s["pipeline"]["researching"] == events.get("researching", 0)
    assert s["discovery"]["quota_remaining"] == (
        s["discovery"]["daily_item_quota"] - s["discovery"]["items_today"]
    )
    assert s["usage"]["ai_calls_today"] > 0  # research + writing used the (fake) model
    assert s["usage"]["ai_cost_known"] is False and s["usage"]["search_provider"] is None
    assert s["cms"]["connected"] is True and s["cms"]["auto_deliver"] is False


def test_failed_jobs_are_visible_and_filterable(client: TestClient, env) -> None:  # noqa: F811
    _failed_job(env["t"].tenant_id)
    jobs = client.get("/api/v1/discovery/jobs?status=failed", headers=env["h"]).json()
    assert [j["error"] for j in jobs] == ["Provider quota exceeded"]
    by_type = client.get("/api/v1/discovery/jobs?job_type=writing", headers=env["h"]).json()
    assert by_type and {j["job_type"] for j in by_type} == {"writing"}
    notes = client.get("/api/v1/dashboard/notifications", headers=env["h"]).json()
    kinds = [n["kind"] for n in notes]
    assert "job_failed" in kinds and kinds.count("draft_ready") == 2
    failed = next(n for n in notes if n["kind"] == "job_failed")
    assert failed["severity"] == "error" and "quota" in failed["data"]["error"]
    assert notes == sorted(notes, key=lambda n: n["at"], reverse=True)


def test_notifications_follow_the_website(client: TestClient, env) -> None:  # noqa: F811
    d = client.post(f"/api/v1/articles/{env['a']}/deliver", headers=env["h"]).json()
    env["fake"].articles[int(d["remote_id"])]["status"] = "published"
    client.post("/api/v1/cms/sync", headers=env["h"])
    env["fake"].fail_next = 400
    client.post(f"/api/v1/articles/{env['b']}/deliver", headers=env["h"])
    kinds = [
        n["kind"] for n in client.get("/api/v1/dashboard/notifications", headers=env["h"]).json()
    ]
    assert {"sent_to_website", "website_status", "delivery_failed"} <= set(kinds)


def test_event_status_filter(client: TestClient, env) -> None:  # noqa: F811
    all_events = client.get("/api/v1/events", headers=env["h"]).json()
    status = all_events[0]["status"]
    same = client.get(f"/api/v1/events?status={status}", headers=env["h"]).json()
    assert same and all(e["status"] == status for e in same)
    assert client.get("/api/v1/events?status=archived", headers=env["h"]).json() == []


def test_dashboard_is_tenant_scoped_and_needs_login(client: TestClient, env) -> None:  # noqa: F811
    other = make_tenant("other-tv")
    s = client.get("/api/v1/dashboard/summary", headers=auth(login(client, other))).json()
    assert s["articles"]["generated_today"] == 0 and s["cms"]["connected"] is False
    assert (
        client.get("/api/v1/dashboard/notifications", headers=auth(login(client, other))).json()
        == []
    )
    assert client.get("/api/v1/dashboard/summary").status_code == 401
    reporter = auth(login(client, make_user(env["t"], "rep@janaki.example.com", ["reporter"])))
    assert client.get("/api/v1/dashboard/summary", headers=reporter).status_code == 200
