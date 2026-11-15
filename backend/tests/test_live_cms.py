"""Live end-to-end check against a real JanakiTelevision website (Payload CMS).

Skipped unless these are set (a local or staging site only, never production):
  CMS_E2E_URL          e.g. http://localhost:3000
  CMS_E2E_KEY          API key of an *active* integration on that site
  CMS_E2E_ADMIN_TOKEN  a staff administrator's JWT on that site (to inspect and publish)
  CMS_E2E_LEAVE_DRAFT  optional: stop before publishing, so the draft can be inspected
"""

from __future__ import annotations

import io
import json
import os
import urllib.error
import urllib.request
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import get_settings
from app.modules.cms import service as cms
from app.modules.cms.models import CmsConnection
from app.modules.cms.payload import PayloadClient
from app.modules.visuals.storage import LocalStorage, media_key
from tests.conftest import make_tenant
from tests.test_cms import _hero
from tests.test_discovery_run import tenant_db
from tests.test_editorial import WriterLLM, articles, researched, write

URL = os.environ.get("CMS_E2E_URL", "")
KEY = os.environ.get("CMS_E2E_KEY", "")
ADMIN = os.environ.get("CMS_E2E_ADMIN_TOKEN", "")
pytestmark = pytest.mark.skipif(not (URL and KEY and ADMIN), reason="no live CMS configured")

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def site(
    method: str, path: str, data: Any = None, auth: str | None = None
) -> tuple[int, dict[str, Any]]:
    headers = {"Content-Type": "application/json"}
    if auth:
        headers["Authorization"] = auth
    req = urllib.request.Request(  # noqa: S310 - test-only, operator-supplied site URL
        URL + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with _opener.open(req) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_draft_reaches_the_real_cms_unpublished_and_status_comes_back(
    client: TestClient, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(get_settings(), "cms_allow_private_hosts", True)
    admin, bot = f"JWT {ADMIN}", f"integrations API-Key {KEY}"
    t = make_tenant("janaki-tv")
    eid = researched(t.tenant_id)
    write(t.tenant_id, eid, WriterLLM())
    arts = articles(t.tenant_id, eid)
    a_id = arts["straight"]["article"].id
    storage = LocalStorage(str(tmp_path / "media"))
    env = {"t": t, "eid": eid, "a": a_id, "storage": storage}
    asset = _hero(env)
    img = io.BytesIO()
    Image.new("RGB", (1200, 800), (40, 90, 160)).save(img, "WEBP")
    storage.put(media_key(t.tenant_id, asset, "w1200.webp"), img.getvalue(), "image/webp")

    with tenant_db(t.tenant_id) as db:
        conn = cms.configure(db, tenant_id=t.tenant_id, base_url=URL, api_key=KEY)
        who = cms.check_connection(cms.default_client(conn))
        assert who["integration"]
        d = cms.deliver(db, tenant_id=t.tenant_id, article_id=a_id, storage=storage)
        assert d.status == "delivered", d.last_error
        remote_id, media_id = d.remote_id, d.remote_media_id
    print(f"\nDelivered draft {remote_id} with photo {media_id} to {URL}")

    # What the editor sees in the CMS.
    s, doc = site("GET", f"/api/articles/{remote_id}?depth=0", auth=admin)
    assert s == 200
    assert doc["status"] == "draft" and doc["aiAssisted"] is True
    assert doc["publishedAt"] is None and not doc.get("authors")
    assert doc["newsroomRef"] == f"jn-{a_id}" and doc["deliveredBy"]
    assert doc["editorialNotes"].startswith("AI NEWSROOM DRAFT")
    assert "[CORROBORATED]" in doc["editorialNotes"]
    assert str(doc["heroImage"]) == media_id and "Ram Sharma" in doc["heroImageCredit"]
    assert doc["body"]["root"]["children"][0]["children"][0]["text"].startswith("Floods")
    s, media = site("GET", f"/api/media/{media_id}?depth=0", auth=admin)
    assert s == 200 and "CC BY-SA 4.0" in media["usageNotes"]

    # The public cannot see it; the integration cannot publish, edit or delete it.
    s, pub = site("GET", f"/api/articles?where[id][equals]={remote_id}")
    assert s == 200 and pub["totalDocs"] == 0
    assert site("PATCH", f"/api/articles/{remote_id}", {"status": "published"}, bot)[0] == 403
    assert site("PATCH", f"/api/articles/{remote_id}", {"title": "Changed"}, bot)[0] == 403
    assert site("DELETE", f"/api/articles/{remote_id}", auth=bot)[0] == 403
    s, body = site(
        "POST",
        "/api/articles",
        {"title": "Sneaky", "language": "en", "status": "published", "newsroomRef": "sneaky-1"},
        bot,
    )
    assert s == 403, body

    # Delivering again does not create a second draft.
    with tenant_db(t.tenant_id) as db:
        again = cms.deliver(db, tenant_id=t.tenant_id, article_id=a_id, storage=storage)
        assert again.remote_id == remote_id
    s, found = site("GET", f"/api/articles?where[newsroomRef][equals]=jn-{a_id}", auth=admin)
    assert found["totalDocs"] == 1

    if os.environ.get("CMS_E2E_LEAVE_DRAFT"):
        return  # leave the draft in the CMS for a person to look at
    # A person adds the byline and publishes; the newsroom sees it on the next sync.
    s, author = site(
        "POST", "/api/authors", {"displayName": "E2E Editor", "slug": f"e2e-{a_id.hex[:8]}"}, admin
    )
    assert s == 201, author
    s, cats = site("GET", "/api/categories?limit=1&depth=0")
    assert cats["docs"], "the site needs at least one section"
    s, pubd = site(
        "PATCH",
        f"/api/articles/{remote_id}",
        {
            "authors": [author["doc"]["id"]],
            "categories": [cats["docs"][0]["id"]],
            "status": "published",
        },
        admin,
    )
    assert s == 200, pubd
    with tenant_db(t.tenant_id) as db:
        out = cms.sync(db, tenant_id=t.tenant_id)
        d2 = cms.get_delivery(db, t.tenant_id, a_id)
        assert d2 is not None
        assert out["changed"] == 1 and d2.remote_status == "published" and d2.remote_published_at
    s, pub = site("GET", f"/api/articles?where[id][equals]={remote_id}")
    assert pub["totalDocs"] == 1


def test_client_reports_an_inactive_or_wrong_key(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "cms_allow_private_hosts", True)
    conn = CmsConnection(base_url=URL)
    bad = PayloadClient(URL, "not-a-real-key-not-a-real-key", allow_private=True)
    from app.modules.cms.payload import CmsError

    with pytest.raises(CmsError) as exc:
        cms.check_connection(bad)
    assert exc.value.code in ("unauthorized", "inactive")
    assert conn.base_url == URL
