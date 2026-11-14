"""Data charts from verified figures only (policy §6).

* Only corroborated or editor-verified claims; never AI-estimated or single-source numbers.
* At least two figures in the same unit; bar charts only (pie charts would imply a whole).
* The SVG carries title, unit, labels, sources and date; every label is XML-escaped.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from xml.sax.saxutils import escape

VERIFIED = ("corroborated", "editor_verified")


def chart_spec(
    claims: list[dict[str, Any]], *, title: str, as_of: datetime
) -> tuple[dict[str, Any] | None, str]:
    """claims: [{"id", "text", "status", "numbers", "publishers"}]. Returns (spec, reason)."""
    by_unit: dict[str, list[dict[str, Any]]] = {}
    for c in claims:
        if c["status"] not in VERIFIED:
            continue
        for n in c["numbers"]:
            unit = (n.get("unit") or "").strip().lower()
            if unit:
                by_unit.setdefault(unit, []).append(
                    {
                        "label": c["text"][:60],
                        "value": float(n["value"]),
                        "claim_id": c["id"],
                        "publishers": c["publishers"],
                    }
                )
    candidates = {
        u: pts
        for u, pts in by_unit.items()
        if len({p["value"] for p in pts}) >= 2 and len({p["label"] for p in pts}) >= 2
    }
    if not candidates:
        return None, (
            "A chart needs at least two verified figures in the same unit; this "
            "story does not have them"
        )
    unit, points = max(candidates.items(), key=lambda kv: len(kv[1]))
    sources = sorted({p for pt in points for p in pt["publishers"]})
    return {
        "type": "bar",
        "title": title[:120],
        "unit": unit,
        "data": [{k: pt[k] for k in ("label", "value", "claim_id")} for pt in points[:8]],
        "sources": sources,
        "as_of": as_of.date().isoformat(),
        "methodology": "Figures as reported by the listed publishers and verified by the "
        "newsroom's evidence rules; not adjusted or estimated.",
    }, "ok"


def _attr(value: str) -> str:
    return escape(value, {'"': "&quot;"})


def render_svg(spec: dict[str, Any]) -> bytes:
    w, row, top, left = 800, 44, 70, 260
    data = spec["data"]
    h = top + row * len(data) + 70
    peak = max(d["value"] for d in data) or 1.0
    bar_w = w - left - 120
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" role="img" aria-label="{_attr(spec["title"])}">',
        f'<rect width="{w}" height="{h}" fill="#ffffff"/>',
        f'<text x="20" y="34" font-family="sans-serif" font-size="20" font-weight="700" '
        f'fill="#111">{escape(spec["title"])}</text>',
        f'<text x="20" y="56" font-family="sans-serif" font-size="13" fill="#555">'
        f"Unit: {escape(spec['unit'])}</text>",
    ]
    for i, d in enumerate(data):
        y = top + i * row
        length = max(2, round(bar_w * d["value"] / peak))
        parts += [
            f'<text x="20" y="{y + 24}" font-family="sans-serif" font-size="13" '
            f'fill="#222">{escape(d["label"][:38])}</text>',
            f'<rect x="{left}" y="{y + 8}" width="{length}" height="24" fill="#1f5fa8"/>',
            f'<text x="{left + length + 8}" y="{y + 25}" font-family="sans-serif" '
            f'font-size="13" fill="#111">{d["value"]:,.10g}</text>',
        ]
    parts.append(
        f'<text x="20" y="{h - 20}" font-family="sans-serif" font-size="12" fill="#555">'
        f"Source: {escape(', '.join(spec['sources']))} · as of {escape(spec['as_of'])}</text>"
    )
    parts.append("</svg>")
    return "".join(parts).encode()
