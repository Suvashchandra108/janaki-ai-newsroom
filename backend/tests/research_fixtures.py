"""Shared fixtures for research tests: three publishers covering one flood story."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.modules.ai_gateway.gateway import AIError, LLMResult
from app.modules.discovery import text as dtext
from app.modules.discovery.models import BackgroundJob, DiscoveredItem, NewsEvent, NewsSource
from app.modules.discovery.safe_fetch import FetchError, FetchResult
from app.modules.research import service as research
from tests.test_discovery_run import tenant_db

NOW = datetime(2026, 11, 14, 6, 0, tzinfo=UTC)
FILLER = " Rescue teams worked through the night to move residents to higher ground." * 4


def page(*paragraphs: str) -> bytes:
    body = "".join(f"<p>{p}</p>" for p in (*paragraphs, FILLER))
    return (
        f"<html><body><nav><p>Menu items here for the site</p></nav><article>{body}"
        f"</article></body></html>".encode()
    )


ART = {
    "kathmandupost.example.com": (
        "https://kathmandupost.example.com/national/saptari-flood",
        page(
            "Floods in Saptari district have displaced 2,000 families, the Madhesh Province "
            "government said on Friday.",
            "The Chief Minister announced relief of NPR 50 million for affected households.",
        ),
    ),
    "himalayan.example.org": (
        "https://himalayan.example.org/saptari-flood-relief",
        page(
            "At least 2,000 families were displaced by floods in Saptari district, according "
            "to the Madhesh Province government."
        ),
    ),
    "rising.example.net": (
        "https://rising.example.net/news/saptari-floods",
        page(
            "Floods in Saptari district displaced 3,000 families, local officials told "
            "reporters on Saturday."
        ),
    ),
}

# What a well-behaved model would extract from each article (keyed by a phrase in the text).
CLAIMS: dict[str, list[dict[str, Any]]] = {
    "have displaced 2,000 families": [
        {
            "text": "Floods in Saptari district displaced 2,000 families",
            "type": "official",
            "excerpt": "Floods in Saptari district have displaced 2,000 families",
            "entities": ["Saptari", "Madhesh Province government"],
            "numbers": [{"value": 2000, "unit": "families"}],
            "dates": ["Friday"],
        },
        {
            "text": "The Chief Minister announced NPR 50 million in relief for affected households",
            "type": "official",
            "excerpt": "The Chief Minister announced relief of NPR 50 million for affected "
            "households",
            "entities": ["Chief Minister"],
            "numbers": [{"value": 50, "unit": "NPR million"}],
            "dates": [],
        },
    ],
    "At least 2,000 families": [
        {
            "text": "Floods in Saptari district displaced 2,000 families",
            "type": "official",
            "excerpt": "At least 2,000 families were displaced by floods in Saptari district",
            "entities": ["Saptari"],
            "numbers": [{"value": 2000, "unit": "families"}],
            "dates": [],
        },
    ],
    "displaced 3,000 families": [
        {
            "text": "Floods in Saptari district displaced 3,000 families",
            "type": "reported",
            "excerpt": "Floods in Saptari district displaced 3,000 families",
            "entities": ["Saptari"],
            "numbers": [{"value": 3000, "unit": "families"}],
            "dates": ["Saturday"],
        },
    ],
}


@dataclass
class FakeWeb:
    pages: dict[str, bytes]
    robots: dict[str, bytes] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def fetch(self, url: str, allowed_domains: Iterable[str]) -> FetchResult:
        self.calls.append(url)
        if url.endswith("/robots.txt"):
            if url in self.robots:
                return FetchResult(url, url, 200, "text/plain", self.robots[url])
            raise FetchError("http_status", "HTTP 404", status=404)
        if url not in self.pages:
            raise FetchError("http_status", "HTTP 404", status=404)
        return FetchResult(url, url, 200, "text/html; charset=utf-8", self.pages[url])

    def close(self) -> None:
        pass


@dataclass
class FakeLLM:
    claims: dict[str, list[dict[str, Any]]] = field(default_factory=lambda: dict(CLAIMS))
    fail_after: int | None = None
    override: Callable[[str], dict[str, Any]] | None = None
    calls: list[str] = field(default_factory=list)
    name: str = "fake"
    model: str = "fake-model"

    def generate_json(self, *, system: str, user: str, max_output_tokens: int) -> LLMResult:
        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            raise AIError("rate_limited", "free quota reached", retryable=True)
        self.calls.append(user)
        if self.override:
            data = self.override(user)
        else:
            data = {"claims": next((v for k, v in self.claims.items() if k in user), [])}
        return LLMResult(json.loads(json.dumps(data)), self.name, self.model, 1000, 200)


def seed_event(
    tenant_id: uuid.UUID,
    domains: Iterable[str] = tuple(ART),
    pages: dict[str, tuple[str, bytes]] | None = None,
) -> uuid.UUID:
    pages = pages or ART
    with tenant_db(tenant_id) as db:
        ev = NewsEvent(
            tenant_id=tenant_id,
            title="Saptari floods displace families",
            keywords=["saptari", "flood"],
            title_simhash=1,
            language="en",
            first_seen_at=NOW,
            last_seen_at=NOW,
            item_count=0,
            publisher_count=0,
        )
        db.add(ev)
        db.flush()
        for d in domains:
            src = NewsSource(
                tenant_id=tenant_id,
                name=d,
                kind="rss",
                feed_url=f"https://{d}/rss?e={uuid.uuid4().hex[:8]}",
                allowed_domains=[d],
                language="en",
                credibility="high" if d.startswith("kathmandu") else "medium",
            )
            db.add(src)
            db.flush()
            url = pages[d][0]
            db.add(
                DiscoveredItem(
                    tenant_id=tenant_id,
                    source_id=src.id,
                    event_id=ev.id,
                    url=url,
                    canonical_url=url,
                    url_hash=dtext.sha256(url),
                    publisher_domain=d,
                    title="Saptari floods",
                    language="en",
                    retrieved_at=NOW,
                    content_fingerprint=dtext.sha256(url),
                    title_simhash=1,
                )
            )
            ev.item_count += 1
            ev.publisher_count += 1
        return ev.id


def web_for(domains: Iterable[str] = tuple(ART), **kw: Any) -> FakeWeb:
    return FakeWeb({ART[d][0]: ART[d][1] for d in domains}, **kw)


def research_run(
    tenant_id: uuid.UUID, event_id: uuid.UUID, *, web: FakeWeb, llm: FakeLLM | None, key: str = "r1"
) -> BackgroundJob | None:
    with tenant_db(tenant_id) as db:
        return research.run_research(
            db,
            tenant_id=tenant_id,
            event_id=event_id,
            idempotency_key=key,
            trigger="test",
            fetcher=web,  # type: ignore[arg-type]
            llm=llm,
            now=NOW,
        )


def claims_of(tenant_id: uuid.UUID, event_id: uuid.UUID) -> list[dict[str, Any]]:
    from app.modules.research.models import Claim, Evidence

    with tenant_db(tenant_id) as db:
        out = []
        for c in db.scalars(select(Claim).where(Claim.event_id == event_id)):
            ev = list(db.scalars(select(Evidence).where(Evidence.claim_id == c.id)))
            out.append(
                {
                    "text": c.text,
                    "status": c.status,
                    "n": c.independent_sources,
                    "evidence": sorted((e.publisher_domain, e.relationship) for e in ev),
                    "numbers": c.numbers,
                    "id": c.id,
                }
            )
        return out
