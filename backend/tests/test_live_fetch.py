"""Live network check, run in CI only (LIVE_FETCH=1). Verifies the production fetch path —
real DNS, public-IP check, pinned connection, TLS to the real hostname — against a public feed."""

from __future__ import annotations

import os

import pytest

from app.modules.discovery.adapters import parse_feed
from app.modules.discovery.safe_fetch import SafeFetcher

pytestmark = pytest.mark.skipif(
    os.environ.get("LIVE_FETCH") != "1", reason="set LIVE_FETCH=1 to run against the internet"
)

LIVE_FEED = os.environ.get("LIVE_FEED_URL", "https://feeds.bbci.co.uk/news/world/rss.xml")
LIVE_DOMAINS = os.environ.get("LIVE_FEED_DOMAINS", "bbci.co.uk").split(",")


def test_real_feed_fetch_and_parse() -> None:
    fetcher = SafeFetcher()  # production defaults: public IPs only, ports 80/443
    try:
        res = fetcher.fetch(LIVE_FEED, LIVE_DOMAINS)
    finally:
        fetcher.close()
    leads = parse_feed(res.body)
    assert res.status == 200
    assert len(leads) > 0
    assert all(lead.url.startswith("http") and lead.title for lead in leads)


def test_real_wikimedia_commons_search_and_download() -> None:
    from app.modules.visuals import commons, licences
    from app.modules.visuals.processing import process

    fetcher = SafeFetcher(
        timeout=20,
        max_bytes=8_000_000,
        user_agent="JanakiNewsroomBot/0.1 (CI; contact: newsroom@janaki-newsroom.example.com)",
    )
    try:
        images = commons.search(fetcher, "Janakpur Janaki Mandir", limit=8)
        usable = [i for i in images if licences.publishable(i.licence, i.attribution_text)]
        print(f"\nCommons: {len(images)} results, {len(usable)} publishable")
        for i in images[:5]:
            print(
                f"  {'OK ' if i in usable else 'NO '} {i.title[:50]} | {i.licence.name} | "
                f"{(i.creator or '')[:30]}"
            )
        assert usable, "expected at least one commercially usable image"
        res = fetcher.fetch(
            usable[0].download_url,
            commons.DOMAINS,
            content_types=commons.IMAGE_MIMES,
            max_bytes=8_000_000,
        )
        p = process(res.body)
        print(
            f"Downloaded {len(res.body)} bytes {p.width}x{p.height}; derivatives "
            f"{[d[0] for d in p.derivatives]}"
        )
        assert p.derivatives
    finally:
        fetcher.close()
