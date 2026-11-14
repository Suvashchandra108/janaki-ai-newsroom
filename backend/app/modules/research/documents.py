"""Fetching article pages for research, with permitted access only.

* Only URLs on the source's approved domains are fetched (via ``SafeFetcher``).
* robots.txt is honoured: a 4xx robots file means "allowed"; an unreachable or 5xx one means
  "not now" (conservative, as major crawlers do).
* Text is kept for internal research only and is never republished; excerpts shown to editors
  are short quotations.
"""

from __future__ import annotations

import re
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.discovery import text as dtext
from app.modules.discovery.models import DiscoveredItem, NewsSource
from app.modules.discovery.safe_fetch import FetchError, SafeFetcher, host_allowed
from app.modules.research.models import SourceDocument

ROBOTS_USER_AGENT = "JanakiNewsroomBot"
MIN_TEXT_CHARS = 200

_SKIP = {
    "script",
    "style",
    "noscript",
    "nav",
    "footer",
    "aside",
    "form",
    "header",
    "figure",
    "svg",
    "button",
    "iframe",
    "template",
}
_BLOCK = {"p", "li", "h1", "h2", "h3", "h4", "blockquote"}


class _MainTextParser(HTMLParser):
    """Collects paragraph-level text, preferring content inside <article>."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.article_depth = 0
        self.block: list[str] | None = None
        self.in_article_blocks: list[str] = []
        self.all_blocks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self.skip_depth += 1
        elif tag == "article":
            self.article_depth += 1
        elif tag in _BLOCK and self.skip_depth == 0:
            self.block = []
        elif tag == "br" and self.block is not None:
            self.block.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP and self.skip_depth:
            self.skip_depth -= 1
        elif tag == "article" and self.article_depth:
            self.article_depth -= 1
        elif tag in _BLOCK and self.block is not None:
            text = re.sub(r"\s+", " ", "".join(self.block)).strip()
            if len(text) >= 25:
                self.all_blocks.append(text)
                if self.article_depth:
                    self.in_article_blocks.append(text)
            self.block = None

    def handle_data(self, data: str) -> None:
        if self.block is not None and self.skip_depth == 0:
            self.block.append(data)


def extract_main_text(html: str, max_chars: int) -> str:
    parser = _MainTextParser()
    parser.feed(html)
    parser.close()
    blocks = (
        parser.in_article_blocks
        if sum(map(len, parser.in_article_blocks)) >= MIN_TEXT_CHARS
        else parser.all_blocks
    )
    return "\n\n".join(blocks)[:max_chars]


@dataclass
class RobotsCache:
    fetcher: SafeFetcher
    _cache: dict[str, urllib.robotparser.RobotFileParser | str] = field(default_factory=dict)

    def allowed(self, url: str) -> tuple[bool, str | None]:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if host not in self._cache:
            self._cache[host] = self._load(f"{parts.scheme}://{parts.netloc}/robots.txt", host)
        entry = self._cache[host]
        if isinstance(entry, str):
            return False, entry
        return entry.can_fetch(ROBOTS_USER_AGENT, url), "disallowed by robots.txt"

    def _load(self, robots_url: str, host: str) -> urllib.robotparser.RobotFileParser | str:
        rp = urllib.robotparser.RobotFileParser()
        try:
            res = self.fetcher.fetch(robots_url, [host])
            rp.parse(res.body.decode("utf-8", errors="replace").splitlines())
        except FetchError as exc:
            if exc.status is not None and 400 <= exc.status < 500:
                rp.parse([])  # no robots.txt: everything allowed
            else:
                return f"robots.txt unavailable ({exc.code}); will retry later"
        return rp


def get_or_fetch_document(
    db: Session,
    *,
    item: DiscoveredItem,
    source: NewsSource,
    fetcher: SafeFetcher,
    robots: RobotsCache,
    now: datetime,
) -> SourceDocument:
    doc = db.scalar(
        select(SourceDocument).where(
            SourceDocument.tenant_id == item.tenant_id, SourceDocument.item_id == item.id
        )
    )
    if doc is not None and doc.status in ("fetched", "not_allowed", "blocked_by_robots", "empty"):
        return doc
    if doc is None:
        doc = SourceDocument(
            tenant_id=item.tenant_id, item_id=item.id, status="failed", fetched_at=now
        )
        db.add(doc)
    doc.fetched_at = now
    doc.error = None

    if not host_allowed(dtext.domain_of(item.url), source.allowed_domains):
        doc.status, doc.error = "not_allowed", "publisher domain is not on the approved list"
        db.flush()
        return doc
    ok, reason = robots.allowed(item.url)
    if not ok:
        doc.status = "blocked_by_robots" if reason == "disallowed by robots.txt" else "failed"
        doc.error = reason
        db.flush()
        return doc
    try:
        res = fetcher.fetch(item.url, source.allowed_domains)
    except FetchError as exc:
        doc.status, doc.error = "failed", f"{exc.code}: {exc.message}"[:500]
        db.flush()
        return doc
    text = extract_main_text(
        res.body.decode("utf-8", errors="replace"), get_settings().research_max_text_chars
    )
    doc.final_url = res.final_url[:2000]
    if len(text) < MIN_TEXT_CHARS:
        doc.status, doc.error, doc.text = "empty", "no article text found", None
    else:
        doc.status, doc.text, doc.text_hash = (
            "fetched",
            text,
            dtext.sha256(re.sub(r"\s+", " ", text.lower())),
        )
    db.flush()
    return doc
