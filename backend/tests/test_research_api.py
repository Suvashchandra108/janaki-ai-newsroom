from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import worker
from tests.conftest import auth, login, make_tenant, make_user
from tests.research_fixtures import FakeLLM, research_run, seed_event, web_for


@pytest.fixture
def researched(client: TestClient):
    t = make_tenant("janaki-tv")
    eid = seed_event(t.tenant_id)
    research_run(t.tenant_id, eid, web=web_for(), llm=FakeLLM())
    return t, eid


def _flood(claims: list[dict]) -> dict:
    return next(c for c in claims if "2,000 families" in c["text"])


def test_claims_and_evidence_are_inspectable(client: TestClient, researched) -> None:
    t, eid = researched
    rep = auth(login(client, make_user(t, "rep@janaki.example.com", ["reporter"])))
    claims = client.get(f"/api/v1/events/{eid}/claims", headers=rep).json()
    flood = _flood(claims)
    assert flood["status"] == "conflicting" and "rising.example.net" in flood["status_reason"]
    ev = flood["evidence"]
    assert {e["relationship"] for e in ev} == {"supports", "contradicts"}
    assert all(e["url"].startswith("https://") and e["excerpt"] and e["retrieved_at"] for e in ev)

    research = client.get(f"/api/v1/events/{eid}/research", headers=rep).json()
    assert research["event_status"] == "evidence_assessment"
    assert research["claim_statuses"] == {"conflicting": 1, "insufficient": 1}
    assert {d["status"] for d in research["documents"]} == {"fetched"}
    assert research["last_job_status"] == "succeeded"

    single = client.get(f"/api/v1/claims/{flood['id']}", headers=rep).json()
    assert single["id"] == flood["id"]


def test_editor_review_rules(client: TestClient, researched) -> None:
    t, eid = researched
    rev = auth(login(client, make_user(t, "rev@janaki.example.com", ["reviewer"])))
    rep = auth(login(client, make_user(t, "rep@janaki.example.com", ["reporter"])))
    claims = client.get(f"/api/v1/events/{eid}/claims", headers=rev).json()
    relief = next(c for c in claims if "NPR 50 million" in c["text"])
    url = f"/api/v1/claims/{relief['id']}/review"

    assert client.post(url, json={"verified": True}, headers=rep).status_code == 403
    r = client.post(url, json={"verified": True}, headers=rev)
    assert r.status_code == 422 and r.json()["error"]["code"] == "note_required"
    r = client.post(
        url,
        json={"verified": True, "note": "Confirmed with the CM's office press release, 14 Nov"},
        headers=rev,
    )
    assert r.status_code == 200 and r.json()["status"] == "editor_verified"
    assert r.json()["reviewed_by"] is not None

    r = client.post(url, json={"verified": False}, headers=rev)
    assert r.json()["status"] == "insufficient"  # back to the rule-based status
    actions = [
        a["action"] for a in client.get("/api/v1/audit-logs", headers=auth(login(client, t))).json()
    ]
    assert "claim.verified" in actions and "claim.verification_removed" in actions


def test_api_keys_cannot_verify_claims(client: TestClient, researched) -> None:
    t, eid = researched
    h = auth(login(client, t))
    key = client.post(
        "/api/v1/api-keys",
        json={"name": "bot", "scopes": ["events.read", "evidence.review"]},
        headers=h,
    ).json()["key"]
    claim_id = client.get(f"/api/v1/events/{eid}/claims", headers=h).json()[0]["id"]
    r = client.post(
        f"/api/v1/claims/{claim_id}/review",
        json={"verified": True, "note": "automated"},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "human_only"


def test_research_data_is_tenant_isolated(client: TestClient, researched) -> None:
    t, eid = researched
    other = auth(login(client, make_tenant("news-co-b")))
    claim_id = client.get(f"/api/v1/events/{eid}/claims", headers=auth(login(client, t))).json()[0][
        "id"
    ]
    assert client.get(f"/api/v1/events/{eid}/claims", headers=other).status_code == 404
    assert client.get(f"/api/v1/events/{eid}/research", headers=other).status_code == 404
    assert client.get(f"/api/v1/claims/{claim_id}", headers=other).status_code == 404
    assert (
        client.post(
            f"/api/v1/claims/{claim_id}/review", json={"verified": True, "note": "x"}, headers=other
        ).status_code
        == 404
    )
    assert client.get("/api/v1/usage/ai", headers=other).json()["ai_calls"] == 0


def test_manual_research_and_usage(
    client: TestClient, researched, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, eid = researched
    h = auth(login(client, t))
    monkeypatch.setattr(worker, "enqueue_research", lambda tid, ev: f"research:{ev}:manual:x")
    r = client.post(f"/api/v1/events/{eid}/research", headers=h)
    assert r.status_code == 202 and r.json()["idempotency_key"].endswith("manual:x")
    usage = client.get("/api/v1/usage/ai", headers=h).json()
    assert usage == {
        "days": 30,
        "ai_calls": 3,
        "input_tokens": 3000,
        "output_tokens": 600,
        "by_kind": {"ai.claim_extraction": 3},
    }
    rep = auth(login(client, make_user(t, "rep@janaki.example.com", ["reporter"])))
    assert client.post(f"/api/v1/events/{eid}/research", headers=rep).status_code == 403
    assert client.get("/api/v1/usage/ai", headers=rep).status_code == 403
