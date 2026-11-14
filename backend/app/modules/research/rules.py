"""Deterministic matching and verification rules. No AI involved, no AI confidence used."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.modules.discovery import text as dtext

MIN_INDEPENDENT_SOURCES = 2
NUMBER_TOLERANCE = 0.02  # values within 2% are treated as the same figure


def claim_keywords(text: str) -> list[str]:
    return sorted({t for t in dtext.tokens(text) if not re.fullmatch(r"[\d.,]+", t)})


def same_claim(kw_a: Iterable[str], kw_b: Iterable[str]) -> bool:
    a, b = set(kw_a), set(kw_b)
    shared = len(a & b)
    return shared >= 3 and dtext.jaccard(a, b) >= 0.3


def _unit(u: str) -> str:
    """Singularise a unit so 'families'/'family' and 'people'/'person' compare equal."""
    u = re.sub(r"\s+", " ", u.strip().lower())
    irregular = {"people": "person", "persons": "person", "children": "child"}
    if u in irregular:
        return irregular[u]
    if u.endswith("ies") and len(u) > 4:
        return u[:-3] + "y"
    if u.endswith("s") and not u.endswith("ss") and len(u) > 3:
        return u[:-1]
    return u


def numbers_conflict(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> bool:
    """True when both claims give a figure in the same unit and the figures disagree."""
    by_unit_a: dict[str, set[float]] = {}
    for n in a:
        if n.get("unit"):
            by_unit_a.setdefault(_unit(n["unit"]), set()).add(float(n["value"]))
    for n in b:
        unit = _unit(n.get("unit") or "")
        if not unit or unit not in by_unit_a:
            continue
        value = float(n["value"])
        if not any(abs(value - v) <= NUMBER_TOLERANCE * max(abs(v), 1.0) for v in by_unit_a[unit]):
            return True
    return False


@dataclass(frozen=True)
class EvidenceView:
    relationship: str
    publisher_domain: str
    content_hash: str | None


def independent_publishers(evidence: Iterable[EvidenceView]) -> int:
    """Distinct publishers among supporting evidence; syndicated copies count once."""
    supports = [e for e in evidence if e.relationship == "supports"]
    groups: dict[str, set[str]] = {}  # identical article text -> publishers
    for e in supports:
        key = e.content_hash or f"domain:{e.publisher_domain}"
        groups.setdefault(key, set()).add(e.publisher_domain)
    # Union publishers that share a text; count connected groups.
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            x = parent[x]
        return x

    for domains in groups.values():
        first, *rest = sorted(domains)
        for d in rest:
            parent[find(d)] = find(first)
    return len({find(e.publisher_domain) for e in supports})


def compute_status(current: str, evidence: list[EvidenceView]) -> tuple[str, str, int]:
    """Return (status, reason, independent_sources). Editor verification is never overridden,
    but its reason notes any later contradicting evidence."""
    n = independent_publishers(evidence)
    contradicting = sorted(
        {e.publisher_domain for e in evidence if e.relationship == "contradicts"}
    )
    if current == "editor_verified":
        if contradicting:
            return current, f"Editor verified; later contradicted by {', '.join(contradicting)}", n
        return current, "Verified by an editor", n
    if contradicting:
        return "conflicting", f"Contradicted by {', '.join(contradicting)}", n
    if n >= MIN_INDEPENDENT_SOURCES:
        return "corroborated", f"Supported by {n} independent publishers", n
    if n == 1:
        return "insufficient", "Only one publisher reports this", n
    return "insufficient", "No supporting evidence", n
