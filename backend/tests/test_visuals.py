"""Acceptance (Phase 5): sourced images carry provenance and licence metadata; unlicensed
images cannot be publishable; AI visuals are labelled; charts use verified data only."""

from __future__ import annotations

import io
import json
import uuid
from collections.abc import Iterable, Iterator
from typing import Any

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws
from PIL import Image
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.api.v1 import media_routes
from app.main import app
from app.modules.discovery.safe_fetch import FetchError, FetchResult
from app.modules.research.models import Claim, Evidence
from app.modules.visuals import commons, licences
from app.modules.visuals.models import MediaAsset
from app.modules.visuals.processing import ImageRejected, inspect, process
from app.modules.visuals.storage import LocalStorage, S3Storage, media_key
from tests.conftest import auth, login, make_tenant, make_user
from tests.research_fixtures import NOW, FakeLLM, research_run, seed_event, web_for
from tests.test_discovery_run import tenant_db


def jpeg(width: int = 1200, height: int = 800, exif: bool = True) -> bytes:
    img = Image.new("RGB", (width, height), (40, 90, 160))
    out = io.BytesIO()
    if exif:
        ex = Image.Exif()
        ex[0x010F] = "SecretCameraMaker"
        ex[0x8825] = {2: (27.0, 42.0, 0.0)}  # GPS
        img.save(out, "JPEG", exif=ex.tobytes())
    else:
        img.save(out, "JPEG")
    return out.getvalue()


def page(
    i: int,
    title: str,
    licence: str | None,
    url: str | None,
    mime: str = "image/jpeg",
    artist: str = "<a href='//x'>Ram Sharma</a>",
    restrictions: str = "",
) -> dict:
    ext: dict[str, dict[str, str]] = {
        "Artist": {"value": artist},
        "ImageDescription": {"value": f"<p>{title}</p>"},
    }
    if licence:
        ext["LicenseShortName"] = {"value": licence}
    if url:
        ext["LicenseUrl"] = {"value": url}
    if restrictions:
        ext["Restrictions"] = {"value": restrictions}
    return {
        "index": i,
        "title": f"File:{title}.jpg",
        "imageinfo": [
            {
                "url": f"https://upload.wikimedia.org/wikipedia/commons/a/ab/{i}.jpg",
                "thumburl": f"https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/{i}.jpg/1600px",
                "descriptionurl": f"https://commons.wikimedia.org/wiki/File:{title}.jpg",
                "mime": mime,
                "width": 4000,
                "height": 3000,
                "extmetadata": ext,
            }
        ],
    }


COMMONS = {
    "query": {
        "pages": [
            page(
                1,
                "Janaki Mandir Janakpur",
                "CC BY-SA 4.0",
                "https://creativecommons.org/licenses/by-sa/4.0",
                restrictions="personality",
            ),
            page(
                2,
                "Saptari flood NC",
                "CC BY-NC 2.0",
                "https://creativecommons.org/licenses/by-nc/2.0",
            ),
            page(3, "Mystery licence", None, None),
            page(4, "Old map of Madhesh", "Public domain", None),
            page(
                5,
                "Flood report",
                "CC BY 4.0",
                "https://creativecommons.org/licenses/by/4.0",
                mime="application/pdf",
            ),
        ]
    }
}


class FakeCommons:
    def __init__(self, image: bytes | None = None, payload: dict | None = None) -> None:
        self.image = image if image is not None else jpeg()
        self.payload = payload or COMMONS
        self.calls: list[str] = []

    def fetch(
        self,
        url: str,
        allowed_domains: Iterable[str],
        content_types: Any = (),
        max_bytes: int | None = None,
    ) -> FetchResult:
        self.calls.append(url)
        if url.startswith(commons.API):
            return FetchResult(url, url, 200, "application/json", json.dumps(self.payload).encode())
        if url.startswith(("https://upload.wikimedia.org/", "https://thumb.wikimedia.org/")):
            return FetchResult(url, url, 200, "image/jpeg", self.image)
        raise FetchError("http_status", "HTTP 404", status=404)

    def close(self) -> None:
        pass


class FakeGenerator:
    name, model = "fakegen", "img-1"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> bytes:
        self.prompts.append(prompt)
        return jpeg(1024, 768, exif=False)


@pytest.fixture
def env(client: TestClient, tmp_path) -> Iterator[dict[str, Any]]:
    t = make_tenant("janaki-tv")
    domains = ["kathmandupost.example.com", "himalayan.example.org"]
    eid = seed_event(t.tenant_id, domains=domains)
    research_run(t.tenant_id, eid, web=web_for(domains), llm=FakeLLM())
    with tenant_db(t.tenant_id) as db:
        from app.modules.discovery.models import NewsEvent

        ev = db.get(NewsEvent, eid)
        ev.region = "Madhesh Province"
    fake = FakeCommons()
    storage = LocalStorage(str(tmp_path / "media"))
    app.dependency_overrides[media_routes.get_fetcher] = lambda: fake
    app.dependency_overrides[media_routes.storage_dep] = lambda: storage
    yield {"t": t, "eid": eid, "fake": fake, "storage": storage, "h": auth(login(client, t))}
    app.dependency_overrides.clear()


def _search(client: TestClient, env: dict, query: str | None = None) -> list[dict]:
    r = client.post(
        f"/api/v1/events/{env['eid']}/media/search",
        headers=env["h"],
        json={"query": query} if query else {},
    )
    assert r.status_code == 201, r.text
    return r.json()


# --- licences ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,url,ok",
    [
        ("CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0", True),
        ("CC BY 2.0", "https://creativecommons.org/licenses/by/2.0", True),
        ("CC0", None, True),
        ("Public domain", None, True),
        ("CC BY-NC-SA 4.0", "https://creativecommons.org/licenses/by-nc-sa/4.0", False),
        ("CC BY-ND 4.0", "https://creativecommons.org/licenses/by-nd/4.0", False),
        ("GFDL", "https://www.gnu.org/copyleft/fdl.html", False),
        ("All rights reserved", None, False),
        (None, None, False),
        ("CC BY-SA 4.0", None, False),  # attribution licence without a licence link
    ],
)
def test_licence_rules(name: str | None, url: str | None, ok: bool) -> None:
    lic = licences.classify(name, url)
    assert licences.publishable(lic, "attribution text") is ok


def test_commons_parsing_and_attribution() -> None:
    images = commons.parse_search(COMMONS)
    assert [i.title for i in images] == [
        "Janaki Mandir Janakpur",
        "Saptari flood NC",
        "Mystery licence",
        "Old map of Madhesh",
    ]
    first = images[0]
    assert first.creator == "Ram Sharma" and first.restrictions == ["personality"]
    assert first.attribution_text == (
        "“Janaki Mandir Janakpur” by Ram Sharma, CC BY-SA "
        "4.0 (https://creativecommons.org/licenses/by-sa/4.0), "
        "via Wikimedia Commons"
    )
    assert first.download_url.endswith("1600px")  # never the huge original
    from app.modules.discovery.safe_fetch import host_allowed

    for host in ("commons.wikimedia.org", "upload.wikimedia.org", "thumb.wikimedia.org"):
        assert host_allowed(host, commons.DOMAINS)
    assert not host_allowed("wikimedia.org.evil.example", commons.DOMAINS)
    assert "filetype%3Abitmap" in commons.search_url("Janakpur")


# --- search and selection -----------------------------------------------------------------------


def test_search_records_provenance_and_licence(client: TestClient, env) -> None:
    found = _search(client, env)
    by_title = {m["title"]: m for m in found}
    assert set(by_title) == {
        "Janaki Mandir Janakpur",
        "Saptari flood NC",
        "Mystery licence",
        "Old map of Madhesh",
    }
    ok = by_title["Janaki Mandir Janakpur"]
    assert (
        ok["publishable"] and ok["status"] == "candidate" and ok["provider"] == "wikimedia_commons"
    )
    assert ok["source_page_url"].startswith("https://commons.wikimedia.org/wiki/")
    assert ok["licence_url"] and ok["creator"] == "Ram Sharma" and ok["restrictions"]
    assert ok["processing_history"][0]["step"] == "found"
    assert not by_title["Saptari flood NC"]["publishable"]
    assert "Non-commercial" in by_title["Saptari flood NC"]["licence_notes"]
    assert not by_title["Mystery licence"]["publishable"]
    assert by_title["Old map of Madhesh"]["publishable"]
    assert "Madhesh Province" in env["fake"].calls[0].replace("+", " ")
    assert _search(client, env) == []  # repeated search does not duplicate candidates
    assert len(client.get(f"/api/v1/events/{env['eid']}/media", headers=env["h"]).json()) == 4


def test_unlicensed_images_cannot_be_used(client: TestClient, env) -> None:
    nc = next(m for m in _search(client, env) if m["title"] == "Saptari flood NC")
    r = client.post(f"/api/v1/media/{nc['id']}/select", headers=env["h"], json={})
    assert r.status_code == 409 and "Non-commercial" in r.json()["error"]["message"]
    # The database itself refuses to mark it publishable or selected.
    with tenant_db(env["t"].tenant_id) as db, pytest.raises(IntegrityError):
        db.execute(
            text("UPDATE media_assets SET publishable = true WHERE id = :i"), {"i": nc["id"]}
        )
    with tenant_db(env["t"].tenant_id) as db, pytest.raises(IntegrityError):
        db.execute(
            text("UPDATE media_assets SET status = 'selected' WHERE id = :i"), {"i": nc["id"]}
        )


def test_select_downloads_processes_and_serves(client: TestClient, env) -> None:
    ok = next(m for m in _search(client, env) if m["title"] == "Janaki Mandir Janakpur")
    r = client.post(
        f"/api/v1/media/{ok['id']}/select",
        headers=env["h"],
        json={"role": "hero", "caption": "Janaki Mandir in Janakpur"},
    )
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["status"] == "selected" and m["mime"] == "image/jpeg" and m["width"] == 1200
    assert [d["name"] for d in m["derivatives"]] == ["w1200.webp", "w800.webp", "w400.webp"]
    assert m["caption"].startswith("Janaki Mandir in Janakpur — “Janaki Mandir Janakpur”")
    assert [h["step"] for h in m["processing_history"]] == ["found", "downloaded", "derivatives"]
    assert "no crop" in m["processing_history"][-1]["detail"]

    t = env["t"]
    for d in m["derivatives"]:
        assert d["key"].startswith(f"tenants/{t.tenant_id}/media/{m['id']}/")
    small = client.get(f"/api/v1/media/{m['id']}/files/w400.webp", headers=env["h"])
    assert small.status_code == 200 and small.headers["content-type"] == "image/webp"
    with Image.open(io.BytesIO(small.content)) as img:
        assert img.size == (400, 267) and not img.getexif()  # EXIF/GPS stripped
    src = client.get(f"/api/v1/media/{m['id']}/files/source.jpg", headers=env["h"])
    assert src.status_code == 200 and src.content == env["fake"].image  # original preserved
    assert (
        client.get(
            f"/api/v1/media/{m['id']}/files/..%2F..%2Fetc%2Fpasswd", headers=env["h"]
        ).status_code
        == 404
    )


def test_rejected_downloads(client: TestClient, env) -> None:
    ok = next(m for m in _search(client, env) if m["title"] == "Janaki Mandir Janakpur")
    env["fake"].image = b"<html>not an image</html>"
    r = client.post(f"/api/v1/media/{ok['id']}/select", headers=env["h"], json={})
    assert r.status_code == 422 and r.json()["error"]["code"] == "image_rejected"


def test_decompression_bomb_and_formats() -> None:
    bomb = io.BytesIO()
    Image.new("1", (8000, 6000)).save(bomb, "PNG")
    with pytest.raises(ImageRejected, match="too large"):
        inspect(bomb.getvalue())
    gif = io.BytesIO()
    Image.new("RGB", (10, 10)).save(gif, "GIF")
    with pytest.raises(ImageRejected, match="unsupported"):
        inspect(gif.getvalue())
    small = process(jpeg(300, 200, exif=False))
    assert [d[0] for d in small.derivatives] == ["w300.webp"]  # never upscaled


def test_select_must_target_article_of_same_story(client: TestClient, env) -> None:
    ok = next(m for m in _search(client, env) if m["title"] == "Janaki Mandir Janakpur")
    r = client.post(
        f"/api/v1/media/{ok['id']}/select", headers=env["h"], json={"article_id": str(uuid.uuid4())}
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "wrong_article"


def test_humans_only_and_tenant_isolation(client: TestClient, env) -> None:
    ok = next(m for m in _search(client, env) if m["title"] == "Janaki Mandir Janakpur")
    key = client.post(
        "/api/v1/api-keys",
        headers=env["h"],
        json={"name": "bot", "scopes": ["media.manage", "articles.read"]},
    ).json()["key"]
    r = client.post(f"/api/v1/media/{ok['id']}/select", headers={"X-API-Key": key}, json={})
    assert r.status_code == 403 and r.json()["error"]["code"] == "human_only"
    rev = auth(login(client, make_user(env["t"], "rev@janaki.example.com", ["reviewer"])))
    assert client.post(f"/api/v1/media/{ok['id']}/reject", headers=rev).status_code == 403

    other = auth(login(client, make_tenant("news-co-b")))
    assert client.get(f"/api/v1/events/{env['eid']}/media", headers=other).status_code == 404
    assert (
        client.post(f"/api/v1/media/{ok['id']}/select", headers=other, json={}).status_code == 404
    )
    assert (
        client.get(f"/api/v1/media/{ok['id']}/files/source.jpg", headers=other).status_code == 404
    )

    r = client.post(f"/api/v1/media/{ok['id']}/reject", headers=env["h"])
    assert r.json()["status"] == "rejected"


# --- charts ------------------------------------------------------------------------------------


def _add_claim(tenant_id, event_id, text_: str, status: str, value: float, unit: str) -> None:
    from app.modules.discovery import text as dtext

    with tenant_db(tenant_id) as db:
        c = Claim(
            tenant_id=tenant_id,
            event_id=event_id,
            text=text_,
            fingerprint=dtext.sha256(text_),
            claim_type="official",
            keywords=[],
            entities=[],
            numbers=[{"value": value, "unit": unit}],
            dates=[],
            status=status,
        )
        db.add(c)
        db.flush()
        db.add(
            Evidence(
                tenant_id=tenant_id,
                claim_id=c.id,
                url="https://a.example.com/x",
                publisher_domain="a.example.com",
                retrieved_at=NOW,
                excerpt=text_,
                relationship="supports",
            )
        )


def test_chart_only_from_verified_same_unit_figures(client: TestClient, env) -> None:
    t, eid, h = env["t"], env["eid"], env["h"]
    r = client.post(f"/api/v1/events/{eid}/media/chart", headers=h)
    assert r.status_code == 422 and r.json()["error"]["code"] == "no_chart_data"

    _add_claim(
        t.tenant_id,
        eid,
        "Saptari <script>alert(1)</script> families",
        "corroborated",
        1200,
        "families",
    )
    _add_claim(t.tenant_id, eid, "Siraha families displaced", "editor_verified", 800, "families")
    _add_claim(t.tenant_id, eid, "Rumoured 9000 families", "insufficient", 9000, "families")
    r = client.post(f"/api/v1/events/{eid}/media/chart", headers=h)
    assert r.status_code == 201, r.text
    m = r.json()
    spec = m["chart_spec"]
    assert spec["type"] == "bar" and spec["unit"] == "families"
    values = sorted(d["value"] for d in spec["data"])
    assert 9000 not in values and {800.0, 1200.0} <= set(values)
    assert spec["sources"] and spec["as_of"] and spec["methodology"]
    assert m["publishable"] and not m["ai_generated"] and m["caption"].startswith("Source:")
    svg = client.get(f"/api/v1/media/{m['id']}/files/chart.svg", headers=h)
    assert svg.status_code == 200 and b"<script>" not in svg.content
    assert b"&lt;script&gt;" in svg.content and b"Source:" in svg.content


# --- AI illustrations ---------------------------------------------------------------------------


def test_ai_illustrations_are_labelled_limited_and_photo_first(
    client: TestClient, env, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, eid, h = env["t"], env["eid"], env["h"]
    url = f"/api/v1/events/{eid}/media/illustration"
    r = client.post(url, headers=h)
    assert r.status_code == 503 and r.json()["error"]["code"] == "ai_not_configured"

    gen = FakeGenerator()
    monkeypatch.setattr(media_routes, "get_image_generator", lambda: gen)
    photos = _search(client, env)
    assert client.post(url, headers=h).status_code == 409  # licensed photos come first
    for p in photos:
        client.post(f"/api/v1/media/{p['id']}/reject", headers=h)

    r = client.post(url, headers=h)
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["ai_generated"] and m["kind"] == "illustration"
    assert m["label"].startswith("AI-generated illustration") and m["caption"] == m["label"]
    prompt = gen.prompts[0]
    assert "No identifiable people" in prompt and "Saptari" not in prompt  # no headline words
    sel = client.post(
        f"/api/v1/media/{m['id']}/select", headers=h, json={"caption": "Flood relief"}
    ).json()
    assert "AI-generated illustration" in sel["caption"]

    with tenant_db(t.tenant_id) as db:
        from app.modules.tenancy.models import Tenant

        ten = db.get(Tenant, t.tenant_id)
        ten.settings = {**ten.settings, "generation": {"max_illustrations_per_day": 1}}
    r = client.post(url, headers=h)
    assert r.status_code == 429 and r.json()["error"]["code"] == "illustration_limit"

    # The database refuses an AI image without its label.
    with tenant_db(t.tenant_id) as db, pytest.raises(IntegrityError):
        db.execute(text("UPDATE media_assets SET label = NULL WHERE id = :i"), {"i": m["id"]})


# --- storage ------------------------------------------------------------------------------------


def test_local_storage_blocks_path_traversal(tmp_path) -> None:
    s = LocalStorage(str(tmp_path))
    key = media_key(uuid.uuid4(), uuid.uuid4(), "../../evil name.webp")
    assert ".." not in key and key.endswith("evilname.webp")
    s.put(key, b"x", "image/webp")
    assert s.get(key) == b"x"
    with pytest.raises(ValueError):
        s.put("../outside.txt", b"x", "text/plain")


def test_s3_storage_round_trip() -> None:
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="janaki-media")
        s = S3Storage(bucket="janaki-media", client=client)
        s.put("tenants/t1/media/a/w400.webp", b"data", "image/webp")
        assert s.get("tenants/t1/media/a/w400.webp") == b"data"
        head = client.head_object(Bucket="janaki-media", Key="tenants/t1/media/a/w400.webp")
        assert head["ContentType"] == "image/webp"


def test_media_rows_are_tenant_isolated(env) -> None:
    other = make_tenant("news-co-b")
    with tenant_db(other.tenant_id) as db:
        assert db.scalars(select(MediaAsset)).all() == []
