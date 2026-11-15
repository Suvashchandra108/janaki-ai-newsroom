"""Acceptance (Phase 7): drafts reach the website CMS as unpublished drafts, exactly once, with
sources in the internal notes; the newsroom follows their status but never approves or publishes.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text

from app import worker
from app.api.v1 import cms_routes
from app.core.config import Settings
from app.main import app
from app.modules.audit.models import AuditLog
from app.modules.cms import mapping
from app.modules.cms import service as cms
from app.modules.cms.models import CmsConnection, CmsDelivery
from app.modules.cms.payload import CmsError, PayloadClient, parse_base_url
from app.modules.editorial.models import Article
from app.modules.visuals.models import MediaAsset
from app.modules.visuals.storage import LocalStorage, media_key
from tests.conftest import auth, login, make_tenant, make_user
from tests.test_discovery_run import tenant_db
from tests.test_editorial import WriterLLM, articles, researched, write

KEY = "test-integration-key-0123456789abcdef"


class FakeCMS:
    """A tiny in-memory Payload: articles, media, categories and /integrations/me."""

    def __init__(self) -> None:
        self.articles: dict[int, dict[str, Any]] = {}
        self.media: dict[int, dict[str, Any]] = {}
        self.categories = {"disaster": 7}
        self.calls: list[tuple[str, str]] = []
        self.fail_next: int | None = None  # HTTP status for the next POST
        self.drop_response_after_create = False
        self.active = True
        self.next_id = 100

    def __call__(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, bytes]:
        parts = urlsplit(url)
        q = {k: v[0] for k, v in parse_qs(parts.query).items()}
        path = parts.path
        self.calls.append((method, path))
        if headers.get("Authorization") != f"integrations API-Key {KEY}":
            return 403, json.dumps({"errors": [{"message": "Forbidden"}]}).encode()
        if method == "POST" and self.fail_next:
            status, self.fail_next = self.fail_next, None
            return status, json.dumps({"errors": [{"message": "Something broke"}]}).encode()
        if path == "/api/integrations/me":
            return 200, json.dumps(
                {"user": {"id": 1, "name": "AI newsroom", "active": self.active}}
            ).encode()
        if path == "/api/categories":
            cid = self.categories.get(q.get("where[slug][equals]", ""))
            return 200, json.dumps({"docs": [{"id": cid}] if cid else []}).encode()
        if path == "/api/articles" and method == "GET":
            ref = q.get("where[newsroomRef][equals]")
            docs = [a for a in self.articles.values() if a["newsroomRef"] == ref]
            return 200, json.dumps({"docs": docs[:1]}).encode()
        if path == "/api/articles" and method == "POST":
            data = json.loads(body or b"{}")
            if data.get("status") != "draft":
                return 403, b'{"errors":[{"message":"Integrations can only deliver drafts."}]}'
            if any(a["newsroomRef"] == data["newsroomRef"] for a in self.articles.values()):
                return 400, b'{"errors":[{"message":"Value must be unique"}]}'
            self.next_id += 1
            doc = {**data, "id": self.next_id, "aiAssisted": True, "publishedAt": None}
            self.articles[self.next_id] = doc
            if self.drop_response_after_create:
                self.drop_response_after_create = False
                return 502, b"{}"
            return 201, json.dumps({"doc": doc}).encode()
        if path.startswith("/api/articles/") and method == "GET":
            doc = self.articles.get(int(path.rsplit("/", 1)[-1]))
            return (200, json.dumps(doc).encode()) if doc else (404, b"{}")
        if path == "/api/media" and method == "POST":
            assert b'name="_payload"' in (body or b"") and b'name="file"' in (body or b"")
            fields = json.loads((body or b"").split(b"\r\n\r\n", 1)[1].split(b"\r\n--", 1)[0])
            self.next_id += 1
            self.media[self.next_id] = {"id": self.next_id, **fields}
            return 201, json.dumps({"doc": self.media[self.next_id]}).encode()
        return 404, b"{}"


@pytest.fixture
def env(client: TestClient, tmp_path) -> Iterator[dict[str, Any]]:
    t = make_tenant("janaki-tv")
    eid = researched(t.tenant_id)
    write(t.tenant_id, eid, WriterLLM())
    arts = articles(t.tenant_id, eid)
    fake = FakeCMS()
    storage = LocalStorage(str(tmp_path / "media"))

    def factory(conn: CmsConnection) -> PayloadClient:
        return PayloadClient(conn.base_url, KEY, transport=fake)

    with tenant_db(t.tenant_id) as db:
        cms.configure(
            db, tenant_id=t.tenant_id, base_url="https://cms.janaki.example.com", api_key=KEY
        )
    app.dependency_overrides[cms_routes.client_factory_dep] = lambda: factory
    app.dependency_overrides[cms_routes.storage_dep] = lambda: storage
    yield {
        "t": t,
        "eid": eid,
        "a": arts["straight"]["article"].id,
        "b": arts["context"]["article"].id,
        "fake": fake,
        "factory": factory,
        "storage": storage,
        "h": auth(login(client, t)),
    }
    app.dependency_overrides.clear()


def _hero(env: dict[str, Any]) -> uuid.UUID:
    """A selected, licensed hero photo with stored derivatives for article A."""
    t = env["t"]
    aid = uuid.uuid4()
    for name, data in (("w400.webp", b"small"), ("w1200.webp", b"RIFF-big-webp")):
        env["storage"].put(media_key(t.tenant_id, aid, name), data, "image/webp")
    with tenant_db(t.tenant_id) as db:
        from datetime import UTC, datetime

        db.add(
            MediaAsset(
                id=aid,
                tenant_id=t.tenant_id,
                event_id=env["eid"],
                article_id=env["a"],
                role="hero",
                kind="photo",
                status="selected",
                provider="wikimedia_commons",
                source_page_url="https://commons.wikimedia.org/wiki/File:Flood.jpg",
                original_url="https://upload.wikimedia.org/flood.jpg",
                title="Flood in Saptari",
                creator="Ram Sharma",
                retrieved_at=datetime.now(UTC),
                licence_name="CC BY-SA 4.0",
                licence_url="https://creativecommons.org/licenses/by-sa/4.0",
                attribution_required=True,
                attribution_text=(
                    "“Flood in Saptari” by Ram Sharma, CC BY-SA 4.0, via Wikimedia Commons"
                ),
                commercial_use=True,
                restrictions=[],
                publishable=True,
                caption="Flooded fields — Ram Sharma",
                derivatives=[
                    {
                        "name": "w400.webp",
                        "key": media_key(t.tenant_id, aid, "w400.webp"),
                        "width": 400,
                        "mime": "image/webp",
                    },
                    {
                        "name": "w1200.webp",
                        "key": media_key(t.tenant_id, aid, "w1200.webp"),
                        "width": 1200,
                        "mime": "image/webp",
                    },
                ],
                selected_at=datetime.now(UTC),
            )
        )
    return aid


def _deliver(client: TestClient, env: dict[str, Any], article_id: uuid.UUID, headers=None):
    return client.post(f"/api/v1/articles/{article_id}/deliver", headers=headers or env["h"])


# --- address safety --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://cms.example.com",  # not https
        "https://cms.example.com/admin",  # path
        "https://user:pw@cms.example.com",
        "https://10.0.0.5",
        "https://127.0.0.1",
        "https://cms.example.com:8443",
        "ftp://cms.example.com",
    ],
)
def test_cms_address_must_be_public_https_origin(url: str) -> None:
    with pytest.raises(CmsError):
        parse_base_url(url, allow_private=False)


def test_cms_address_normalised_and_private_hosts_need_dev_flag() -> None:
    assert parse_base_url("https://CMS.Example.com/", allow_private=False).base_url == (
        "https://cms.example.com"
    )
    assert parse_base_url("http://localhost:3000", allow_private=True).port == 3000
    with pytest.raises(ValueError, match="cms_allow_private_hosts"):
        Settings(
            environment="production",
            jwt_secret="x" * 40,
            api_key_pepper="y" * 40,
            mfa_encryption_key="0" * 43 + "=",
            cms_allow_private_hosts=True,
        )


def test_internal_addresses_are_refused_at_connection_time() -> None:
    client = PayloadClient(
        "https://cms.example.com", KEY, resolver=lambda host, port: ["169.254.169.254"]
    )
    with pytest.raises(CmsError) as exc:
        client.find_article_by_ref("x")
    assert exc.value.code == "blocked_address" and not exc.value.retryable


# --- mapping ---------------------------------------------------------------------------------


def test_lexical_matches_the_website_structure() -> None:
    doc = mapping.lexical(["One.", "  ", "Two."])
    paras = doc["root"]["children"]
    assert [p["children"][0]["text"] for p in paras] == ["One.", "Two."]
    assert paras[0]["type"] == "paragraph" and paras[0]["children"][0]["type"] == "text"


# --- delivery --------------------------------------------------------------------------------


def test_delivers_an_unpublished_draft_with_sources_and_photo(client: TestClient, env) -> None:
    _hero(env)
    r = _deliver(client, env, env["a"])
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "delivered" and d["remote_status"] == "draft" and d["remote_media_id"]
    doc = env["fake"].articles[int(d["remote_id"])]
    assert doc["status"] == "draft" and doc["newsroomRef"] == f"jn-{env['a']}"
    assert doc["slug"].endswith("-" + env["a"].hex[:6]) and len(doc["slug"]) <= 120
    assert doc["title"].startswith("Saptari floods displace 2,000 families")
    assert len(doc["title"]) <= 200 and len(doc["seo"]["title"]) <= 70
    assert len(doc["distribution"]["socialSummary"]) <= 280 and len(doc["tags"]) <= 15
    assert "authors" not in doc  # the byline is the editor's decision
    assert doc["publishedAt"] is None
    assert doc["body"]["root"]["children"][0]["children"][0]["text"].startswith("Floods in Saptari")
    notes = doc["editorialNotes"]
    assert notes.startswith("AI NEWSROOM DRAFT — not yet checked by a person")
    assert "[CORROBORATED]" in notes and "kathmandupost.example.com" in notes
    assert "Alternative headline: 2,000 families displaced" in notes
    assert "CC BY-SA 4.0" in notes
    assert doc["heroImage"] == int(d["remote_media_id"])
    assert "Ram Sharma" in doc["heroImageCredit"]
    media = env["fake"].media[int(d["remote_media_id"])]
    assert "Licence: CC BY-SA 4.0" in media["usageNotes"] and media["alt"]
    with tenant_db(env["t"].tenant_id) as db:
        assert db.get(Article, env["a"]).status == "delivered"
        actions = set(
            db.scalars(select(AuditLog.action).where(AuditLog.tenant_id == env["t"].tenant_id))
        )
    assert "cms.draft_delivered" in actions


def _set_category(value: str) -> None:
    # Versions are immutable for the app role; the test uses the schema owner to set it up.
    engine = create_engine(os.environ["DATABASE_OWNER_URL"])
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL app.bypass_rls = 'on'"))
        conn.execute(text("UPDATE article_versions SET category = :c"), {"c": value})
    engine.dispose()


def test_section_mapped_by_slug_or_left_for_the_editor(client: TestClient, env) -> None:
    _set_category("disaster")
    d = _deliver(client, env, env["a"]).json()
    assert env["fake"].articles[int(d["remote_id"])]["categories"] == [7]
    _set_category("unknown-section")
    d = _deliver(client, env, env["b"]).json()
    assert "categories" not in env["fake"].articles[int(d["remote_id"])]


def test_delivery_is_idempotent(client: TestClient, env) -> None:
    first = _deliver(client, env, env["a"]).json()
    again = _deliver(client, env, env["a"]).json()
    assert first["remote_id"] == again["remote_id"]
    assert len(env["fake"].articles) == 1
    assert sum(1 for m, p in env["fake"].calls if m == "POST" and p == "/api/articles") == 1


def test_timeout_after_create_is_recovered_without_a_duplicate(client: TestClient, env) -> None:
    env["fake"].drop_response_after_create = True
    d = _deliver(client, env, env["a"]).json()
    assert d["status"] == "failed" and d["retryable"] is True
    assert len(env["fake"].articles) == 1  # it was created, but we did not hear back
    d = _deliver(client, env, env["a"]).json()
    assert d["status"] == "delivered" and d["attempts"] == 2
    assert len(env["fake"].articles) == 1


def test_rejection_by_the_cms_is_recorded_not_retried(client: TestClient, env) -> None:
    env["fake"].fail_next = 400
    d = _deliver(client, env, env["a"]).json()
    assert (
        d["status"] == "failed" and d["retryable"] is False and "Something broke" in d["last_error"]
    )
    with tenant_db(env["t"].tenant_id) as db:
        assert env["a"] not in cms.deliverable_articles(db, env["t"].tenant_id)
        assert env["b"] in cms.deliverable_articles(db, env["t"].tenant_id)


def test_wrong_key_is_reported_clearly(client: TestClient, env) -> None:
    def bad(conn: CmsConnection) -> PayloadClient:
        return PayloadClient(conn.base_url, "wrong-key-wrong-key", transport=env["fake"])

    app.dependency_overrides[cms_routes.client_factory_dep] = lambda: bad
    d = _deliver(client, env, env["a"]).json()
    assert d["status"] == "failed" and "unauthorized" in d["last_error"]


def test_rejected_articles_are_never_delivered(client: TestClient, env) -> None:
    with tenant_db(env["t"].tenant_id) as db:
        db.get(Article, env["a"]).status = "rejected"
    r = _deliver(client, env, env["a"])
    assert r.status_code == 409
    assert env["fake"].articles == {}


def test_no_connection_means_no_delivery(client: TestClient) -> None:
    t = make_tenant("other-tv")
    eid = researched(t.tenant_id)
    write(t.tenant_id, eid, WriterLLM())
    aid = articles(t.tenant_id, eid)["straight"]["article"].id
    r = client.post(f"/api/v1/articles/{aid}/deliver", headers=auth(login(client, t)))
    assert r.status_code == 409 and "not connected" in r.json()["error"]["message"]


# --- status sync -----------------------------------------------------------------------------


def test_status_follows_the_cms_until_published_or_removed(client: TestClient, env) -> None:
    a = _deliver(client, env, env["a"]).json()
    b = _deliver(client, env, env["b"]).json()
    env["fake"].articles[int(a["remote_id"])].update(
        status="published", publishedAt="2026-11-15T06:00:00.000Z"
    )
    del env["fake"].articles[int(b["remote_id"])]
    r = client.post("/api/v1/cms/sync", headers=env["h"])
    assert r.json() == {"checked": 2, "changed": 2}
    a2 = client.get(f"/api/v1/articles/{env['a']}/delivery", headers=env["h"]).json()
    b2 = client.get(f"/api/v1/articles/{env['b']}/delivery", headers=env["h"]).json()
    assert a2["remote_status"] == "published" and a2["remote_published_at"].startswith("2026-11-15")
    assert b2["remote_status"] == "removed"
    assert client.post("/api/v1/cms/sync", headers=env["h"]).json() == {"checked": 1, "changed": 0}


# --- connection management -------------------------------------------------------------------


def test_connection_api_is_admin_and_human_only_and_never_returns_the_key(
    client: TestClient, env
) -> None:
    got = client.get("/api/v1/cms/connection", headers=env["h"]).json()
    assert got["api_key_last4"] == KEY[-4:] and "api_key" not in got
    assert "api_key_encrypted" not in json.dumps(got)
    r = client.put(
        "/api/v1/cms/connection",
        headers=env["h"],
        json={"base_url": "https://cms.janaki.example.com", "auto_deliver": True},
    )
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    assert "AI newsroom" in r.json()["detail"]
    env["fake"].active = False
    r = client.post("/api/v1/cms/connection/check", headers=env["h"]).json()
    assert r["ok"] is False and "not active" in r["detail"]
    reporter = auth(login(client, make_user(env["t"], "rep@janaki.example.com", ["reporter"])))
    assert client.get("/api/v1/cms/connection", headers=reporter).status_code == 403
    r = client.put(
        "/api/v1/cms/connection",
        headers=env["h"],
        json={"base_url": "http://169.254.169.254"},
    )
    assert r.status_code == 422
    with tenant_db(env["t"].tenant_id) as db:
        stored = db.scalar(select(CmsConnection.api_key_encrypted))
    assert stored and KEY not in stored  # encrypted at rest


def test_connections_and_deliveries_are_tenant_isolated(client: TestClient, env) -> None:
    _deliver(client, env, env["a"])
    other = make_tenant("other-tv")
    h = auth(login(client, other))
    assert client.get("/api/v1/cms/connection", headers=h).status_code == 404
    assert client.get(f"/api/v1/articles/{env['a']}/delivery", headers=h).status_code == 404
    with tenant_db(other.tenant_id) as db:
        assert db.scalar(select(CmsDelivery.id)) is None
        assert db.scalar(select(CmsConnection.id)) is None


# --- scheduler -------------------------------------------------------------------------------


def test_automatic_delivery_only_when_switched_on(client: TestClient, env, monkeypatch) -> None:
    queued: list[tuple[str, str]] = []
    monkeypatch.setattr(worker.deliver_article, "delay", lambda t, a: queued.append((t, a)))
    assert worker.cms_deliver_all() == 0
    with tenant_db(env["t"].tenant_id) as db:
        db.scalar(select(CmsConnection)).auto_deliver = True
    assert worker.cms_deliver_all() == 2
    assert {a for _, a in queued} == {str(env["a"]), str(env["b"])}
    monkeypatch.setattr(cms, "default_client", env["factory"])
    monkeypatch.setattr("app.modules.visuals.storage.get_storage", lambda: env["storage"])
    out = worker.execute_delivery(str(env["t"].tenant_id), str(env["a"]))
    assert out["status"] == "delivered"
    queued.clear()
    assert worker.cms_deliver_all() == 1  # A is done; only B remains
