"""Acceptance (Phase 4, English): eligible events produce two distinct angles; unsupported
content is flagged; usage is recorded; AI never approves; editors edit with version history."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app import worker
from app.db.session import new_session
from app.modules.ai_gateway.gateway import AIError, LLMResult
from app.modules.ai_gateway.models import UsageRecord
from app.modules.discovery.models import NewsEvent
from app.modules.editorial import service as editorial
from app.modules.editorial.models import Article
from tests.conftest import auth, login, make_tenant, make_user
from tests.research_fixtures import FakeLLM, research_run, seed_event, web_for
from tests.test_discovery_run import tenant_db

TWO = ["kathmandupost.example.com", "himalayan.example.org"]

PLAN_AB = {
    "article_a": {"claims": ["C1"]},
    "article_b": {"focus": "Relief for displaced families", "claims": ["C2"]},
    "article_b_reason": "Relief package is a distinct angle",
}

DRAFT_A = {
    "headline": "Saptari floods displace 2,000 families, Madhesh government says",
    "alt_headline": "2,000 families displaced by Saptari floods",
    "summary": "Floods in Saptari district have displaced 2,000 families, according to the "
    "Madhesh Province government.",
    "paragraphs": [
        {
            "text": "Floods in Saptari district have displaced 2,000 families, the Madhesh "
            "Province government said on Friday.",
            "claims": ["C1"],
        },
        {
            "text": "The displacement was confirmed by two independent news outlets.",
            "claims": ["C1"],
        },
    ],
    "image_caption": "Flooded fields in Saptari district",
    "seo_title": "Saptari floods displace 2,000 families | Madhesh Province news update today",
    "seo_description": "Floods in Saptari have displaced 2,000 families, the Madhesh Province "
    "government said.",
    "keywords": ["Saptari", "floods", "Madhesh", "saptari"],
    "location": "Saptari, Madhesh Province",
    "social": {"facebook": "Floods displace 2,000 families in Saptari.", "x": "x" * 400},
}

DRAFT_B = {
    "headline": "Chief Minister announces relief for flood-hit households",
    "summary": "The Chief Minister announced relief for affected households, according to "
    "The Kathmandu Post.",
    "paragraphs": [
        {
            "text": "According to The Kathmandu Post, the Chief Minister announced relief of NPR "
            "50 million for affected households.",
            "claims": ["C2"],
        },
    ],
    "seo_title": "Relief announced for Saptari flood households",
    "seo_description": "The Chief Minister announced NPR 50 million relief.",
    "keywords": ["relief"],
}


class WriterLLM:
    """Scripted model: returns the plan for planning prompts and drafts per angle."""

    name = "fake"
    model = "fake-writer"

    def __init__(
        self,
        plan: dict | None = None,
        a: dict | None = None,
        b: dict | None = None,
        fail: bool = False,
    ) -> None:
        self.plan = PLAN_AB if plan is None else plan
        self.a = a or DRAFT_A
        self.b = b or DRAFT_B
        self.fail = fail
        self.calls: list[str] = []

    def generate_json(self, *, system: str, user: str, max_output_tokens: int) -> LLMResult:
        if self.fail:
            raise AIError("rate_limited", "quota", retryable=True)
        if "planning coverage" in system:
            kind, data = "plan", self.plan
        elif "Article B" in system:
            kind, data = "write_b", self.b
        else:
            kind, data = "write_a", self.a
        self.calls.append(kind)
        return LLMResult(json.loads(json.dumps(data)), self.name, self.model, 800, 300)


def researched(tenant_id, domains=TWO):
    eid = seed_event(tenant_id, domains=domains)
    research_run(tenant_id, eid, web=web_for(domains), llm=FakeLLM())
    return eid


def write(tenant_id, eid, llm, key="w1"):
    with tenant_db(tenant_id) as db:
        return editorial.run_writing(
            db, tenant_id=tenant_id, event_id=eid, idempotency_key=key, trigger="test", llm=llm
        )


def articles(tenant_id, eid) -> dict[str, dict[str, Any]]:
    with tenant_db(tenant_id) as db:
        out = {}
        for a in db.scalars(select(Article).where(Article.event_id == eid)):
            v = editorial.current_version(db, a)
            out[a.angle] = {"article": a, "v": v, "codes": [f["code"] for f in v.flags]}
        return out


@pytest.fixture
def tenant(client: TestClient):
    return make_tenant("janaki-tv")


def test_writes_two_distinct_angles_with_citations_and_limits(tenant) -> None:
    eid = researched(tenant.tenant_id)
    llm = WriterLLM()
    job = write(tenant.tenant_id, eid, llm)
    assert job is not None and job.status == "succeeded", job.result
    assert llm.calls == ["plan", "write_a", "write_b"]
    arts = articles(tenant.tenant_id, eid)
    assert set(arts) == {"straight", "context"}

    a, b = arts["straight"], arts["context"]
    assert a["article"].status == "draft" and a["codes"] == []
    assert a["article"].language == "en" and a["article"].slug.startswith("saptari-floods")
    v = a["v"]
    assert all(p["claim_ids"] for p in v.paragraphs)
    assert len(v.seo_title) <= 70 and len(v.seo_description) <= 170
    assert len(v.social["x"]) <= 280 and v.keywords == ["saptari", "floods", "madhesh"]
    assert v.created_by_kind == "ai" and v.model == "fake-writer"
    assert "kathmandupost.example.com" in v.attribution and v.attribution.startswith("AI-assisted")
    # B relies on a single-source claim: shown to the editor as information.
    assert b["codes"] == ["single_source_claim"] and b["article"].status == "draft"

    with tenant_db(tenant.tenant_id) as db:
        assert db.get(NewsEvent, eid).status == "draft"
        kinds = dict(
            db.execute(select(UsageRecord.kind, func.count()).group_by(UsageRecord.kind))
            .tuples()
            .all()
        )
    assert kinds == {"ai.claim_extraction": 2, "ai.angle_planning": 1, "ai.writing": 2}


def test_no_second_article_without_distinct_evidence(tenant) -> None:
    eid = researched(tenant.tenant_id)
    plan = {
        "article_a": {"claims": ["C1", "C2"]},
        "article_b": None,
        "article_b_reason": "Only one development to report",
    }
    write(tenant.tenant_id, eid, WriterLLM(plan=plan))
    arts = articles(tenant.tenant_id, eid)
    assert set(arts) == {"straight"}
    assert "Only one development" in arts["straight"]["v"].note


def test_second_article_repeating_first_is_discarded(tenant) -> None:
    eid = researched(tenant.tenant_id)
    same_b = {**DRAFT_A, "headline": "Another headline about Saptari displacement"}
    plan = {**PLAN_AB, "article_b": {"focus": "x", "claims": ["C1", "C2"]}}
    job = write(tenant.tenant_id, eid, WriterLLM(plan=plan, b=same_b))
    assert job is not None and "too similar" in job.result["article_b"]
    assert set(articles(tenant.tenant_id, eid)) == {"straight"}


def test_plan_with_b_repeating_a_claims_is_rejected_before_writing(tenant) -> None:
    eid = researched(tenant.tenant_id)
    plan = {"article_a": {"claims": ["C1"]}, "article_b": {"focus": "x", "claims": ["C1"]}}
    llm = WriterLLM(plan=plan)
    job = write(tenant.tenant_id, eid, llm)
    assert llm.calls == ["plan", "write_a"] and "repeat" in job.result["article_b"]


def test_fabrications_are_flagged_for_the_editor(tenant) -> None:
    eid = researched(tenant.tenant_id)
    bad = copy.deepcopy(DRAFT_A)
    bad["headline"] = "Saptari floods displace 5,000 families"
    bad["paragraphs"] += [
        {"text": "At least 400 people died in the floods.", "claims": ["C1"]},
        {"text": "Residents said they were frightened as water rose overnight.", "claims": []},
        {"text": "“We will rebuild every single home,” the minister said.", "claims": ["C1"]},
        {"text": "Officials confirmed the figures.", "claims": ["C99"]},
    ]
    write(tenant.tenant_id, eid, WriterLLM(a=bad, plan={**PLAN_AB, "article_b": None}))
    a = articles(tenant.tenant_id, eid)["straight"]
    assert a["article"].status == "needs_review"
    codes = a["codes"]
    assert codes.count("uncited_paragraph") == 2  # no claims, and an unknown claim id
    assert "unverified_quote" in codes
    msgs = " ".join(f["message"] for f in a["v"].flags)
    assert "400" in msgs and "5000" in msgs
    assert all(cid for p in a["v"].paragraphs for cid in p["claim_ids"])  # C99 dropped


def test_conflicting_claim_is_flagged(tenant) -> None:
    eid = researched(tenant.tenant_id, domains=[*TWO, "rising.example.net"])
    with tenant_db(tenant.tenant_id) as db:
        from app.modules.research.models import Claim

        relief = db.scalar(select(Claim).where(Claim.text.like("%NPR 50 million%")))
        relief.status = "editor_verified"  # make the event eligible despite the conflict
    write(tenant.tenant_id, eid, WriterLLM(plan={**PLAN_AB, "article_b": None}))
    assert "conflicting_claim" in articles(tenant.tenant_id, eid)["straight"]["codes"]


def test_not_eligible_without_corroborated_or_verified_claims(tenant) -> None:
    eid = researched(tenant.tenant_id, domains=["kathmandupost.example.com"])
    llm = WriterLLM()
    job = write(tenant.tenant_id, eid, llm)
    assert (
        job is not None and job.status == "skipped" and "editor can verify" in job.result["reason"]
    )
    assert llm.calls == [] and articles(tenant.tenant_id, eid) == {}


def test_no_ai_and_quota_errors(tenant) -> None:
    eid = researched(tenant.tenant_id)
    job = write(tenant.tenant_id, eid, None, key="k1")
    assert job.status == "failed" and job.result["ai_error"] == "not_configured"
    job = write(tenant.tenant_id, eid, WriterLLM(fail=True), key="k2")
    assert job.status == "failed" and job.result["ai_error"] == "rate_limited"
    job = write(tenant.tenant_id, eid, WriterLLM(), key="k2")  # retry under the same key
    assert job.status == "succeeded" and job.attempts == 2
    assert write(tenant.tenant_id, eid, WriterLLM(), key="k2") is None  # idempotent
    job = write(tenant.tenant_id, eid, WriterLLM(), key="k3")
    assert job.status == "skipped" and job.result["reason"] == "already written"


def test_unique_slugs(tenant) -> None:
    e1, e2 = researched(tenant.tenant_id), None
    write(tenant.tenant_id, e1, WriterLLM(plan={**PLAN_AB, "article_b": None}))
    from tests.research_fixtures import ART

    pages = {d: (ART[d][0] + "?2", ART[d][1]) for d in TWO}
    e2 = seed_event(tenant.tenant_id, domains=TWO, pages=pages)
    web = web_for([])
    web.pages.update({u: b for u, b in pages.values()})
    research_run(tenant.tenant_id, e2, web=web, llm=FakeLLM(), key="r2")
    write(tenant.tenant_id, e2, WriterLLM(plan={**PLAN_AB, "article_b": None}), key="w2")
    s1 = articles(tenant.tenant_id, e1)["straight"]["article"].slug
    s2 = articles(tenant.tenant_id, e2)["straight"]["article"].slug
    assert s1 != s2 and s2 == f"{s1}-2"


def test_versions_are_immutable_in_the_database(tenant) -> None:
    eid = researched(tenant.tenant_id)
    write(tenant.tenant_id, eid, WriterLLM())
    db = new_session()
    with pytest.raises(DBAPIError, match="permission denied"):
        db.execute(text("UPDATE article_versions SET headline = 'x'"))
    db.rollback()
    db.close()


# --- API ----------------------------------------------------------------------------------


@pytest.fixture
def written(client: TestClient, tenant):
    eid = researched(tenant.tenant_id)
    write(tenant.tenant_id, eid, WriterLLM())
    ids = {k: v["article"].id for k, v in articles(tenant.tenant_id, eid).items()}
    return tenant, eid, ids


def test_editor_views_edits_and_history(client: TestClient, written) -> None:
    t, eid, ids = written
    ed = auth(login(client, make_user(t, "ed@janaki.example.com", ["editor"])))
    lst = client.get(f"/api/v1/events/{eid}/articles", headers=ed).json()
    assert {a["angle"] for a in lst} == {"straight", "context"}
    art = client.get(f"/api/v1/articles/{ids['straight']}", headers=ed).json()
    claim_id = art["current"]["paragraphs"][0]["claim_ids"][0]

    r = client.patch(
        f"/api/v1/articles/{ids['straight']}",
        headers=ed,
        json={
            "headline": "Saptari floods leave 2,000 families homeless",
            "paragraphs": [
                {
                    "text": "Floods have displaced 2,000 families in Saptari.",
                    "claim_ids": [claim_id],
                },
                {"text": "More than 9,000 people are in shelters.", "claim_ids": []},
            ],
            "note": "Tightened the lede",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["current_version"] == 2 and body["versions"] == [1, 2]
    assert body["current"]["created_by_kind"] == "user" and body["status"] == "needs_review"
    assert {f["code"] for f in body["current"]["flags"]} == {"uncited_paragraph"}
    v1 = client.get(f"/api/v1/articles/{ids['straight']}/versions/1", headers=ed).json()
    assert v1["created_by_kind"] == "ai" and v1["headline"] != body["current"]["headline"]

    bad = client.patch(
        f"/api/v1/articles/{ids['straight']}",
        headers=ed,
        json={"paragraphs": [{"text": "x", "claim_ids": ["00000000-0000-0000-0000-000000000000"]}]},
    )
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "unknown_claim"
    assert client.get("/api/v1/articles?status=needs_review", headers=ed).json()[0]["flag_count"]


def test_regenerate_limit_and_reject(
    client: TestClient, written, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, _, ids = written
    ed = auth(login(client, make_user(t, "ed@janaki.example.com", ["editor"])))
    from app.api.v1 import editorial_routes

    monkeypatch.setattr(editorial_routes, "get_writing_provider", lambda: WriterLLM())
    with tenant_db(t.tenant_id) as db:
        from app.modules.tenancy.models import Tenant

        ten = db.get(Tenant, t.tenant_id)
        ten.settings = {**ten.settings, "generation": {"max_regenerations": 1}}
    url = f"/api/v1/articles/{ids['straight']}"
    r = client.post(f"{url}/regenerate", headers=ed)
    assert r.status_code == 200 and r.json()["current_version"] == 2
    assert r.json()["regenerations"] == 1
    r = client.post(f"{url}/regenerate", headers=ed)
    assert r.status_code == 429 and r.json()["error"]["code"] == "regeneration_limit"

    r = client.post(f"{url}/reject", headers=ed, json={"reason": "Duplicate of our own story"})
    assert r.json()["status"] == "rejected"
    assert (
        client.patch(url, headers=ed, json={"headline": "Edited after reject"}).status_code == 409
    )
    actions = {
        a["action"] for a in client.get("/api/v1/audit-logs", headers=auth(login(client, t))).json()
    }
    assert {"article.regenerated", "article.rejected"} <= actions


def test_permissions_humans_and_isolation(
    client: TestClient, written, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, eid, ids = written
    url = f"/api/v1/articles/{ids['straight']}"
    rev = auth(login(client, make_user(t, "rev@janaki.example.com", ["reviewer"])))
    rep = auth(login(client, make_user(t, "rep@janaki.example.com", ["reporter"])))
    assert client.patch(url, headers=rev, json={"headline": "Reviewer edit"}).status_code == 403
    assert client.post(f"{url}/reject", headers=rep, json={"reason": "nope"}).status_code == 403
    assert client.patch(url, headers=rep, json={"headline": "Reporter edit ok"}).status_code == 200

    admin = auth(login(client, t))
    key = client.post(
        "/api/v1/api-keys",
        headers=admin,
        json={"name": "bot", "scopes": ["articles.read", "articles.edit", "articles.reject"]},
    ).json()
    hk = {"X-API-Key": key["key"]}
    assert client.get(url, headers=hk).status_code == 200
    r = client.patch(url, headers=hk, json={"headline": "Machine edit attempt"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "human_only"

    other = auth(login(client, make_tenant("news-co-b")))
    assert client.get(url, headers=other).status_code == 404
    assert client.get(f"/api/v1/events/{eid}/articles", headers=other).status_code == 404
    assert client.get("/api/v1/articles", headers=other).json() == []

    monkeypatch.setattr(worker, "enqueue_writing", lambda tid, ev: "writing:x:manual:y")
    r = client.post(f"/api/v1/events/{eid}/write", headers=admin)
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_eligible"  # already 'draft'


def test_worker_writing_and_schedule(
    client: TestClient, tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready = researched(tenant.tenant_id)
    researched(tenant.tenant_id, domains=["rising.example.net"])  # single source: not ready
    sent: list[tuple] = []
    monkeypatch.setattr(worker.write_event, "delay", lambda *a: sent.append(a))
    assert worker.writing_schedule_all() == 1 and sent[0][1] == str(ready)

    monkeypatch.setattr(worker, "get_writing_provider", lambda: WriterLLM())
    out = worker.execute_writing(str(tenant.tenant_id), str(ready), "wk", "schedule")
    assert out["status"] == "succeeded"
