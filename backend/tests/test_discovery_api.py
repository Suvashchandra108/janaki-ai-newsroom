from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import worker
from tests.conftest import auth, login, make_tenant, make_user
from tests.test_discovery_run import FEED_A, FEEDS, FakeFetcher, run

SRC = {
    "name": "Kathmandu Post (test)",
    "feed_url": FEED_A,
    "allowed_domains": ["kathmandupost.example.com"],
    "region": "Madhesh Province",
    "category": "national",
    "credibility": "high",
}


def test_source_crud_and_validation(client: TestClient) -> None:
    t = make_tenant("alpha")
    h = auth(login(client, t))
    r = client.post("/api/v1/sources", json=SRC, headers=h)
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert r.json()["language"] == "en"
    assert client.post("/api/v1/sources", json=SRC, headers=h).status_code == 409

    bad_cases = [
        {**SRC, "feed_url": "https://evil.example.net/rss"},
        {**SRC, "feed_url": "http://169.254.169.254/latest"},
        {**SRC, "feed_url": "file:///etc/passwd"},
        {**SRC, "allowed_domains": ["not a domain"]},
        {**SRC, "kind": "search", "feed_url": None},
    ]
    for body in bad_cases:
        assert client.post("/api/v1/sources", json=body, headers=h).status_code == 422, body

    r = client.patch(
        f"/api/v1/sources/{sid}", json={"is_enabled": False, "priority": 90}, headers=h
    )
    assert r.status_code == 200 and r.json()["is_enabled"] is False
    r = client.patch(
        f"/api/v1/sources/{sid}", json={"allowed_domains": ["other.example.com"]}, headers=h
    )
    assert r.status_code == 422  # would orphan the existing feed URL
    assert client.delete(f"/api/v1/sources/{sid}", headers=h).status_code == 405


def test_source_permissions(client: TestClient) -> None:
    t = make_tenant("alpha")
    editor = auth(login(client, make_user(t, "ed@alpha.example.com", ["editor"])))
    reporter = auth(login(client, make_user(t, "rep@alpha.example.com", ["reporter"])))
    assert client.post("/api/v1/sources", json=SRC, headers=editor).status_code == 403
    assert client.post("/api/v1/sources", json=SRC, headers=reporter).status_code == 403
    assert client.get("/api/v1/sources", headers=reporter).status_code == 200
    assert client.post("/api/v1/discovery/run", headers=reporter).status_code == 403


def test_cross_tenant_sources_and_events_are_hidden(client: TestClient) -> None:
    a = make_tenant("alpha")
    b = make_tenant("beta")
    ha, hb = auth(login(client, a)), auth(login(client, b))
    sid = client.post("/api/v1/sources", json=SRC, headers=ha).json()["id"]
    run(a.tenant_id, fetcher=FakeFetcher({FEED_A: FEEDS[FEED_A]}))
    event_id = client.get("/api/v1/events", headers=ha).json()[0]["id"]

    assert client.get(f"/api/v1/sources/{sid}", headers=hb).status_code == 404
    assert (
        client.patch(f"/api/v1/sources/{sid}", json={"is_enabled": False}, headers=hb).status_code
        == 404
    )
    assert client.get(f"/api/v1/events/{event_id}", headers=hb).status_code == 404
    assert client.get("/api/v1/events", headers=hb).json() == []
    assert client.get("/api/v1/discovery/items", headers=hb).json() == []
    assert client.get("/api/v1/discovery/jobs", headers=hb).json() == []


def test_events_items_jobs_and_status(client: TestClient) -> None:
    t = make_tenant("alpha")
    h = auth(login(client, t))
    client.post("/api/v1/sources", json=SRC, headers=h)
    run(t.tenant_id, fetcher=FakeFetcher({FEED_A: FEEDS[FEED_A]}))

    evs = client.get("/api/v1/events", headers=h).json()
    assert len(evs) == 2
    detail = client.get(f"/api/v1/events/{evs[0]['id']}", headers=h).json()
    assert detail["items"] and detail["items"][0]["publisher_domain"] == "kathmandupost.example.com"
    assert len(client.get("/api/v1/discovery/items", headers=h).json()) == 2
    jobs = client.get("/api/v1/discovery/jobs", headers=h).json()
    assert jobs[0]["status"] == "succeeded" and jobs[0]["result"]["items_new"] == 2

    st = client.get("/api/v1/discovery/status", headers=h).json()
    assert st["daily_item_quota"] == 100 and st["paused"] is False
    assert st["next_scheduled_run"] is not None


def test_run_pause_resume(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    t = make_tenant("alpha")
    h = auth(login(client, t))
    monkeypatch.setattr(worker, "enqueue_manual_run", lambda tid: f"discovery:{tid}:manual:x")
    r = client.post("/api/v1/discovery/run", headers=h)
    assert r.status_code == 202 and r.json()["idempotency_key"].endswith("manual:x")

    assert client.post("/api/v1/discovery/pause", headers=h).json()["paused"] is True
    r = client.post("/api/v1/discovery/run", headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "discovery_paused"
    st = client.post("/api/v1/discovery/resume", headers=h).json()
    assert st["paused"] is False

    def broken(tid: object) -> str:
        raise ConnectionError("redis down")

    monkeypatch.setattr(worker, "enqueue_manual_run", broken)
    r = client.post("/api/v1/discovery/run", headers=h)
    assert r.status_code == 503 and r.json()["error"]["code"] == "queue_unavailable"
    actions = {a["action"] for a in client.get("/api/v1/audit-logs", headers=h).json()}
    assert {"discovery.paused", "discovery.resumed", "discovery.run_requested"} <= actions
