"""Source adapters: RSS/Atom feeds and pluggable search providers.

Search results are *leads* for research, never proof (docs/EDITORIAL_WORKFLOW.md).
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urlsplit

import feedparser

from app.modules.discovery.text import clean_text

MAX_ENTRIES_PER_FEED = 200


@dataclass(frozen=True)
class Lead:
    url: str
    title: str
    description: str
    author: str | None
    published_at: datetime | None


def _ts(entry: Any) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            return datetime.fromtimestamp(calendar.timegm(value), tz=UTC)
    return None


def parse_feed(body: bytes) -> list[Lead]:
    """Parse RSS/Atom bytes. feedparser never fetches remote resources when given bytes."""
    parsed = feedparser.parse(body)
    if parsed.get("bozo") and not parsed.entries:
        raise ValueError("Not a valid RSS/Atom feed")
    leads: list[Lead] = []
    for entry in parsed.entries[:MAX_ENTRIES_PER_FEED]:
        link = (entry.get("link") or "").strip()
        title = clean_text(entry.get("title"), 500)
        if not link or not title or urlsplit(link).scheme not in ("http", "https"):
            continue
        leads.append(
            Lead(
                url=link[:2000],
                title=title,
                description=clean_text(entry.get("summary") or entry.get("description"), 2000),
                author=clean_text(entry.get("author"), 200) or None,
                published_at=_ts(entry),
            )
        )
    return leads


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, *, language: str, limit: int) -> list[Lead]: ...


class NullSearchProvider:
    """Used until a search provider is chosen and configured (see DEVELOPMENT_ROADMAP)."""

    name = "none"

    def search(self, query: str, *, language: str, limit: int) -> list[Lead]:
        raise RuntimeError("No search provider configured")


def get_search_provider() -> SearchProvider:
    return NullSearchProvider()
