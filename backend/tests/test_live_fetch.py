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
