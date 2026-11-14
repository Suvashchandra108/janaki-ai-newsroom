"""Acceptance: news is discovered automatically, duplicates handled, sources traceable,
jobs do not duplicate on retry, tenant quotas respected."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app import worker
from app.db.session import new_session, set_tenant_context, system_scope
from app.modules.discovery import service as discovery
from app.modules.discovery.adapters import Lead
from app.modules.discovery.models import BackgroundJob, DiscoveredItem, NewsEvent, NewsSource
from app.modules.discovery.safe_fetch import FetchError, FetchResult
from app.modules.tenancy.models import Tenant
from tests.conftest import make_tenant

NOW = datetime(2026, 11, 14, 6, 0, tzinfo=UTC)


@contextmanager
def tenant_db(tenant_id: uuid.UUID) -> Iterator[Session]:
    """Tenant-scoped session that is always closed, so a failing assertion never leaves a
    transaction holding locks (which would block the TRUNCATE in conftest)."""
    db = new_session()
    try:
        set_tenant_context(db, tenant_id)
        yield db
        db.commit()
    finally:
        db.close()


def rss(*items: tuple[str, str]) -> bytes:
    body = "".join(
        f"<item><title>{t}</title><link>{u}</link><description>{t}.</description>"
        f"<pubDate>Sat, 14 Nov 2026 05:00:00 GMT</pubDate></item>"
        for t, u in items
    )
    return (
        f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>{body}'
        f"</channel></rss>".encode()
    )


FEED_A = "https://kathmandupost.example.com/rss"
FEED_B = "https://himalayan.example.org/feed"
FEEDS = {
    FEED_A: rss(
        (
            "Flood in Saptari district displaces 2,000 families, Madhesh government says",
            "https://kathmandupost.example.com/national/saptari-flood?utm_source=rss",
        ),
        (
            "Saptari flood duplicate link variant",  # same URL after canonicalisation
            "https://www.kathmandupost.example.com/national/saptari-flood/",
        ),
        (
            "Janakpur municipality approves budget for public schools",
            "https://kathmandupost.example.com/madhesh/janakpur-budget",
        ),
    ),
    FEED_B: rss(
        (
            "Saptari flood: 2,000 families displaced as Madhesh Province seeks relief",
            "https://himalayan.example.org/saptari-flood-relief",
        ),
        (
            "Nepal cricket team beats UAE in Kirtipur qualifier",
            "https://himalayan.example.org/sports/cricket-uae",
        ),
    ),
}


class FakeFetcher:
    def __init__(self, feeds: dict[str, bytes], fail: Iterable[str] = ()) -> None:
        self.feeds = feeds
        self.fail = set(fail)
        self.calls: list[str] = []

    def fetch(self, url: str, allowed_domains: Iterable[str]) -> FetchResult:
        self.calls.append(url)
        if url in self.fail:
            raise FetchError("network", "connection reset")
        return FetchResult(url, url, 200, "application/rss+xml", self.feeds[url])

    def close(self) -> None:
        pass


def add_source(tenant_id: uuid.UUID, feed: str, domain: str, **kw: Any) -> uuid.UUID:
    with tenant_db(tenant_id) as db:
        src = NewsSource(
            tenant_id=tenant_id,
            name=domain,
            kind=kw.pop("kind", "rss"),
            feed_url=feed,
            allowed_domains=[domain],
            language="en",
            region="Madhesh Province",
            category="national",
            **kw,
        )
        db.add(src)
        db.commit()
        sid = src.id
    return sid


def run(
    tenant_id: uuid.UUID,
    key: str = "k1",
    fetcher: Any = None,
    search: Any = None,
    now: datetime = NOW,
) -> BackgroundJob | None:
    with tenant_db(tenant_id) as db:
        job = discovery.run_discovery(
            db,
            tenant_id=tenant_id,
            idempotency_key=key,
            trigger="test",
            fetcher=fetcher or FakeFetcher(FEEDS),
            search=search,
            now=now,
        )
    return job


def counts(tenant_id: uuid.UUID) -> tuple[int, int]:
    with tenant_db(tenant_id) as db:
        items = db.scalar(select(func.count()).select_from(DiscoveredItem))
        events = db.scalar(select(func.count()).select_from(NewsEvent))
    return int(items or 0), int(events or 0)


def set_discovery(tenant_id: uuid.UUID, **values: Any) -> None:
    with new_session() as db, system_scope(db):
        t = db.get(Tenant, tenant_id)
        assert t is not None
        t.settings = {**t.settings, "discovery": {**t.settings["discovery"], **values}}
        flag_modified(t, "settings")
        db.commit()


@pytest.fixture
def tenant(client: TestClient):
    t = make_tenant("janaki-tv")
    add_source(t.tenant_id, FEED_A, "kathmandupost.example.com", priority=80)
    add_source(t.tenant_id, FEED_B, "himalayan.example.org", priority=60)
    return t


def test_discovery_dedupes_and_clusters_across_publishers(tenant) -> None:
    job = run(tenant.tenant_id)
    assert job is not None and job.status == "succeeded"
    assert job.result["items_new"] == 4 and job.result["duplicates"] == 1
    with tenant_db(tenant.tenant_id) as db:
        events = {e.title: e for e in db.scalars(select(NewsEvent))}
        flood = next(e for t, e in events.items() if "Saptari" in t)
        assert flood.item_count == 2 and flood.publisher_count == 2
        flood_items = db.scalars(select(DiscoveredItem).where(DiscoveredItem.event_id == flood.id))
        # Individual source records are preserved inside the grouped event.
        assert {i.publisher_domain for i in flood_items} == {
            "kathmandupost.example.com",
            "himalayan.example.org",
        }
    assert len(events) == 3


def test_same_key_does_not_run_twice(tenant) -> None:
    run(tenant.tenant_id, key="discovery:x:2026-11-14T06")
    before = counts(tenant.tenant_id)
    assert run(tenant.tenant_id, key="discovery:x:2026-11-14T06") is None
    assert counts(tenant.tenant_id) == before


def test_new_run_skips_already_seen_urls_and_extends_events(tenant) -> None:
    run(tenant.tenant_id, key="h1")
    later = dict(FEEDS)
    later[FEED_B] = rss(
        (
            "Relief reaches Saptari flood families displaced in Madhesh",
            "https://himalayan.example.org/saptari-relief-day2",
        )
    )
    job = run(tenant.tenant_id, key="h2", fetcher=FakeFetcher(later))
    assert job is not None
    assert job.result["items_new"] == 1 and job.result["events_new"] == 0
    assert job.result["duplicates"] == 3


def test_failed_job_is_retried_under_same_key_without_duplicates(tenant) -> None:
    job = run(tenant.tenant_id, key="r1", fetcher=FakeFetcher(FEEDS, fail=[FEED_A, FEED_B]))
    assert job is not None and job.status == "failed"
    job2 = run(tenant.tenant_id, key="r1")
    assert job2 is not None and job2.id == job.id and job2.attempts == 2
    assert job2.status == "succeeded"
    with tenant_db(tenant.tenant_id) as db:
        assert db.scalar(select(func.count()).select_from(BackgroundJob)) == 1


def test_partial_failure_is_recorded_on_source(tenant) -> None:
    job = run(tenant.tenant_id, fetcher=FakeFetcher(FEEDS, fail=[FEED_B]))
    assert job is not None and job.status == "partial"
    assert job.result["sources_ok"] == 1 and job.result["sources_failed"] == 1
    with tenant_db(tenant.tenant_id) as db:
        src = db.scalar(select(NewsSource).where(NewsSource.feed_url == FEED_B))
        assert (
            src is not None
            and src.consecutive_failures == 1
            and "network" in (src.last_error or "")
        )


def test_daily_quota_is_respected(tenant) -> None:
    set_discovery(tenant.tenant_id, daily_item_quota=2)
    job = run(tenant.tenant_id, key="q1")
    assert job is not None and job.result["items_new"] == 2 and job.result["quota_remaining"] == 0
    job2 = run(tenant.tenant_id, key="q2")
    assert job2 is not None and job2.status == "skipped"
    assert job2.result["reason"] == "daily_quota_exhausted"
    assert counts(tenant.tenant_id)[0] == 2


def test_paused_tenant_is_skipped(tenant) -> None:
    set_discovery(tenant.tenant_id, paused=True)
    job = run(tenant.tenant_id)
    assert job is not None and job.status == "skipped" and job.result["reason"] == "paused"
    assert counts(tenant.tenant_id) == (0, 0)


def test_disabled_source_is_not_fetched(tenant) -> None:
    with tenant_db(tenant.tenant_id) as db:
        src = db.scalar(select(NewsSource).where(NewsSource.feed_url == FEED_B))
        assert src is not None
        src.is_enabled = False
    fetcher = FakeFetcher(FEEDS)
    run(tenant.tenant_id, fetcher=fetcher)
    assert fetcher.calls == [FEED_A]


def test_search_results_limited_to_approved_publishers(client: TestClient) -> None:
    t = make_tenant("alpha")
    add_source(
        t.tenant_id, None, "kathmandupost.example.com", kind="search", search_query="Madhesh flood"
    )

    class FakeSearch:
        name = "fake"

        def search(self, query: str, *, language: str, limit: int) -> list[Lead]:
            return [
                Lead("https://kathmandupost.example.com/x", "Madhesh flood relief", "", None, None),
                Lead("https://random-blog.example.net/y", "Madhesh flood rumour", "", None, None),
            ]

    job = run(t.tenant_id, search=FakeSearch())
    assert job is not None and job.result["items_new"] == 1


def test_missing_search_provider_fails_cleanly(client: TestClient) -> None:
    t = make_tenant("alpha")
    add_source(
        t.tenant_id, None, "kathmandupost.example.com", kind="search", search_query="Madhesh"
    )
    job = run(t.tenant_id, search=None)
    assert job is not None and job.status == "failed"


def test_tenants_are_isolated_in_discovery(tenant) -> None:
    other = make_tenant("news-co-b")
    run(tenant.tenant_id)
    assert counts(other.tenant_id) == (0, 0)
    # Same URLs in another tenant are not treated as duplicates of the first tenant's items.
    add_source(other.tenant_id, FEED_A, "kathmandupost.example.com")
    job = run(other.tenant_id)
    assert job is not None and job.result["items_new"] == 2


def test_worker_execute_and_scheduler(tenant, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker, "_fetcher", lambda: FakeFetcher(FEEDS))
    out = worker.execute(str(tenant.tenant_id), "w1", "schedule")
    assert out["status"] == "succeeded"
    assert worker.execute(str(tenant.tenant_id), "w1", "schedule") == {"status": "already_done"}

    paused = make_tenant("paused-co")
    set_discovery(paused.tenant_id, paused=True)
    sent: list[tuple[str, ...]] = []
    monkeypatch.setattr(worker.run_tenant, "delay", lambda *a: sent.append(a))
    assert worker.schedule_all() == 1
    assert sent[0][0] == str(tenant.tenant_id) and sent[0][2] == "schedule"
    assert sent[0][1].startswith(f"discovery:{tenant.tenant_id}:")


def test_beat_schedule_is_hourly() -> None:
    entry = worker.celery_app.conf.beat_schedule["discovery-hourly"]
    assert entry["task"] == "discovery.schedule_all"
    assert entry["schedule"].minute == {5} and len(entry["schedule"].hour) == 24
