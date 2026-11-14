from __future__ import annotations

from app.modules.discovery import text
from app.modules.discovery.adapters import parse_feed


def test_canonical_url_removes_tracking_and_noise() -> None:
    a = "http://www.Example.com/news/story-1/?utm_source=fb&id=7&fbclid=x#top"
    b = "https://example.com/news/story-1?id=7"
    assert text.canonical_url(a) == text.canonical_url(b) == "https://example.com/news/story-1?id=7"
    assert text.canonical_url("https://example.com/a?id=1") != text.canonical_url(
        "https://example.com/a?id=2"
    )


def test_clustering_groups_same_event_and_separates_different_ones() -> None:
    def sig(title: str) -> tuple[list[str], int]:
        return text.keywords(title), text.simhash64(text.tokens(title))

    a = sig("Flood in Saptari district displaces 2,000 families, Madhesh government says")
    b = sig("Saptari flood: 2,000 families displaced as Madhesh Province seeks relief")
    c = sig("Nepal cricket team beats UAE in Kirtipur qualifier")
    assert text.same_event(*a, *b)
    assert not text.same_event(*a, *c)


def test_simhash_fits_bigint() -> None:
    h = text.simhash64(text.tokens("Janakpur municipality approves new budget for schools"))
    assert -(2**63) <= h < 2**63


def test_parse_feed_rss_and_atom() -> None:
    rss = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>
      <item><title>Budget &amp; schools</title><link>https://example.com/a</link>
        <description>&lt;p&gt;Council <b>approved</b> it.&lt;/p&gt;</description>
        <pubDate>Sat, 14 Nov 2026 08:00:00 GMT</pubDate></item>
      <item><title>No link</title></item>
      <item><title>Bad scheme</title><link>javascript:alert(1)</link></item>
    </channel></rss>"""
    leads = parse_feed(rss)
    assert len(leads) == 1
    assert leads[0].title == "Budget & schools"
    assert leads[0].description == "Council approved it."
    assert leads[0].published_at is not None and leads[0].published_at.hour == 8

    atom = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>T</title>
      <entry><title>Atom story</title><link href="https://example.com/b"/>
      <updated>2026-11-14T09:00:00Z</updated><summary>S</summary></entry></feed>"""
    assert [le.url for le in parse_feed(atom)] == ["https://example.com/b"]


def test_parse_feed_rejects_garbage() -> None:
    import pytest

    with pytest.raises(ValueError):
        parse_feed(b"<html><body>not a feed")
