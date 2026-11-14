from __future__ import annotations

from collections.abc import Iterable

import pytest

from app.modules.discovery.safe_fetch import FetchError, FetchResult
from app.modules.research import rules
from app.modules.research.claims import validate_claims
from app.modules.research.documents import RobotsCache, extract_main_text
from app.modules.research.rules import EvidenceView

ARTICLE = (
    "Floods in Saptari district have displaced 2,000 families, the Madhesh Province government "
    "said on Friday. The Chief Minister announced relief of NPR 50 million for affected "
    "households."
)


# --- text extraction -----------------------------------------------------------------------


def test_extract_main_text_prefers_article_and_skips_chrome() -> None:
    body = " ".join(["This is a long sentence of real reporting from the district."] * 6)
    html = f"""<html><head><script>var x = "<p>not text</p>";</script></head><body>
      <nav><p>Home | Politics | Sports | Entertainment menu entry</p></nav>
      <p>Subscribe to our newsletter for daily updates today!</p>
      <article><h1>Saptari floods displace families</h1><p>{body}</p>
        <aside><p>Related: unrelated story about something else entirely</p></aside></article>
      <footer><p>Copyright notice and contact details for the website</p></footer></body></html>"""
    text = extract_main_text(html, 10_000)
    assert "Saptari floods" in text and "real reporting" in text
    assert all(
        x not in text for x in ("newsletter", "menu entry", "Copyright", "Related:", "not text")
    )


# --- grounded claim validation ---------------------------------------------------------------


def _claim(**kw: object) -> dict:
    base = {
        "text": "Floods in Saptari displaced 2,000 families",
        "type": "official",
        "excerpt": "Floods in Saptari district have displaced 2,000 families",
        "entities": ["Saptari"],
        "numbers": [{"value": 2000, "unit": "Families"}],
        "dates": ["Friday"],
    }
    return {**base, **kw}


def test_grounded_claim_is_kept_and_normalised() -> None:
    out = validate_claims({"claims": [_claim()]}, ARTICLE, 8)
    assert len(out) == 1
    assert out[0].numbers == [{"value": 2000.0, "unit": "families"}]


def test_invented_excerpt_is_dropped() -> None:
    fake = _claim(
        excerpt="Floods killed 400 people in Saptari district",
        numbers=[{"value": 400, "unit": "people"}],
    )
    assert validate_claims({"claims": [fake]}, ARTICLE, 8) == []


def test_numbers_not_in_excerpt_are_dropped() -> None:
    c = _claim(
        excerpt="The Chief Minister announced relief of NPR 50 million",
        text="Chief Minister announced NPR 50 million relief",
        numbers=[{"value": 50000000, "unit": "NPR"}, {"value": 50, "unit": "NPR million"}],
    )
    out = validate_claims({"claims": [c]}, ARTICLE, 8)
    assert out[0].numbers == [{"value": 50.0, "unit": "npr million"}]


def test_whitespace_and_quote_differences_still_match() -> None:
    article = "The minister said: “Relief   will reach\n every family.”"
    c = _claim(
        text="Minister said relief will reach every family",
        numbers=[],
        excerpt='"Relief will reach every family."',
    )
    assert len(validate_claims({"claims": [c]}, article, 8)) == 1


def test_bad_types_shapes_duplicates_and_limits() -> None:
    raw = {
        "claims": [
            _claim(type="verified-by-ai"),
            _claim(),  # duplicate excerpt
            "not an object",
            {"text": "x"},  # missing fields
            _claim(
                text="Chief Minister announced relief",
                excerpt="The Chief Minister announced relief",
                numbers=[],
            ),
        ]
    }
    out = validate_claims(raw, ARTICLE, 8)
    assert [c.claim_type for c in out] == ["reported", "official"]
    assert len(validate_claims(raw, ARTICLE, 1)) == 1
    assert validate_claims({"wrong": True}, ARTICLE, 8) == []
    assert validate_claims({"claims": "nope"}, ARTICLE, 8) == []


# --- rules -----------------------------------------------------------------------------------


def test_same_claim_matching() -> None:
    a = rules.claim_keywords("Floods in Saptari district displaced 2,000 families")
    b = rules.claim_keywords("2,000 families were displaced by floods in Saptari district")
    c = rules.claim_keywords("Chief Minister announced NPR 50 million relief package")
    assert rules.same_claim(a, b) and not rules.same_claim(a, c)


def test_numbers_conflict() -> None:
    fam = lambda v: [{"value": v, "unit": "families"}]  # noqa: E731
    assert rules.numbers_conflict(fam(2000), fam(3000))
    assert not rules.numbers_conflict(fam(2000), fam(2010))  # within 2%
    assert not rules.numbers_conflict(fam(2000), [{"value": 5, "unit": "districts"}])
    assert not rules.numbers_conflict(fam(2000), [])
    assert rules.numbers_conflict(fam(2000), [{"value": 3000, "unit": "family"}])  # stemmed unit


def _ev(rel: str, dom: str, h: str | None = None) -> EvidenceView:
    return EvidenceView(rel, dom, h)


def test_independence_counts_syndicated_copies_once() -> None:
    assert (
        rules.independent_publishers(
            [_ev("supports", "a.com", "h1"), _ev("supports", "b.com", "h2")]
        )
        == 2
    )
    assert (
        rules.independent_publishers(
            [_ev("supports", "a.com", "same"), _ev("supports", "b.com", "same")]
        )
        == 1
    )
    assert (
        rules.independent_publishers(
            [_ev("supports", "a.com", "h1"), _ev("supports", "a.com", "h3")]
        )
        == 1
    )
    assert rules.independent_publishers([_ev("contradicts", "a.com")]) == 0


@pytest.mark.parametrize(
    "current,evidence,expected",
    [
        (
            "researching",
            [_ev("supports", "a.com", "1"), _ev("supports", "b.com", "2")],
            "corroborated",
        ),
        ("researching", [_ev("supports", "a.com", "1")], "insufficient"),
        ("researching", [], "insufficient"),
        (
            "researching",
            [
                _ev("supports", "a.com", "1"),
                _ev("supports", "b.com", "2"),
                _ev("contradicts", "c.com", "3"),
            ],
            "conflicting",
        ),
        ("editor_verified", [_ev("contradicts", "c.com", "3")], "editor_verified"),
        ("corroborated", [_ev("supports", "a.com", "1")], "insufficient"),
    ],
)
def test_compute_status(current: str, evidence: list[EvidenceView], expected: str) -> None:
    status, reason, _ = rules.compute_status(current, evidence)
    assert status == expected and reason


# --- robots.txt --------------------------------------------------------------------------------


class _RobotsFetcher:
    def __init__(self, robots: dict[str, bytes | int]) -> None:
        self.robots = robots

    def fetch(self, url: str, allowed: Iterable[str]) -> FetchResult:
        value = self.robots[url]
        if isinstance(value, int):
            raise FetchError(
                "http_status" if value else "network", f"HTTP {value}", status=value or None
            )
        return FetchResult(url, url, 200, "text/plain", value)


def test_robots_rules() -> None:
    cache = RobotsCache(
        _RobotsFetcher(
            {  # type: ignore[arg-type]
                "https://blocked.example.com/robots.txt": b"User-agent: *\nDisallow: /news/\n",
                "https://open.example.com/robots.txt": 404,
                "https://down.example.com/robots.txt": 503,
                "https://offline.example.com/robots.txt": 0,
            }
        )
    )
    assert cache.allowed("https://blocked.example.com/news/x")[0] is False
    assert cache.allowed("https://blocked.example.com/about")[0] is True
    assert cache.allowed("https://open.example.com/news/x")[0] is True
    assert cache.allowed("https://down.example.com/news/x")[0] is False
    assert cache.allowed("https://offline.example.com/news/x")[0] is False
