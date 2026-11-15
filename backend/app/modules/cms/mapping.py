"""Turns a newsroom article version into a website CMS draft (Payload / Lexical).

Field limits match the JanakiTelevision Articles collection. Nothing is invented: unknown values
(byline, section when unmapped) are left empty for the editor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.editorial.models import ArticleVersion
from app.modules.editorial.writer import ClaimRef
from app.modules.visuals.models import MediaAsset

STATUS_LABEL = {
    "corroborated": "CORROBORATED",
    "editor_verified": "EDITOR-VERIFIED",
    "insufficient": "SINGLE SOURCE",
    "conflicting": "CONFLICTING",
    "unreviewed": "UNCHECKED",
}


def _cut(text: str | None, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def lexical(paragraphs: list[str]) -> dict[str, Any]:
    """Same structure as the website's ``paragraphsToLexical``."""
    return {
        "root": {
            "type": "root",
            "format": "",
            "indent": 0,
            "version": 1,
            "direction": "ltr",
            "children": [
                {
                    "type": "paragraph",
                    "format": "",
                    "indent": 0,
                    "version": 1,
                    "direction": "ltr",
                    "textFormat": 0,
                    "textStyle": "",
                    "children": [
                        {
                            "type": "text",
                            "text": text,
                            "format": 0,
                            "style": "",
                            "mode": "normal",
                            "detail": 0,
                            "version": 1,
                        }
                    ],
                }
                for text in paragraphs
                if text.strip()
            ],
        }
    }


@dataclass(frozen=True)
class EvidenceLink:
    publisher: str
    url: str


def editorial_notes(
    *,
    ref: str,
    version: ArticleVersion,
    angle: str,
    claims: list[ClaimRef],
    links: dict[str, list[EvidenceLink]],
    photo: MediaAsset | None,
) -> str:
    """Internal notes for the editor: what to check, and where every fact came from."""
    lines = [
        "AI NEWSROOM DRAFT — not yet checked by a person. Verify before publishing.",
        f"Reference: {ref} · version {version.version} · "
        f"{'straight report' if angle == 'straight' else 'context / impact'}"
        + (f" · model {version.model}" if version.model else ""),
        version.attribution,
    ]
    warnings = [f for f in version.flags if f.get("severity") == "warning"]
    infos = [f for f in version.flags if f.get("severity") != "warning"]
    if warnings:
        lines += ["", "⚠ RESOLVE BEFORE PUBLISHING:"]
        lines += [
            f"- {f.get('code')}"
            + (f" (paragraph {int(f['paragraph']) + 1})" if f.get("paragraph") is not None else "")
            + f": {f.get('message', '')}"
            for f in warnings
        ]
    if infos:
        lines += ["", "Notes:"]
        lines += [f"- {f.get('code')}: {f.get('message', '')}" for f in infos]
    if version.alt_headline:
        lines += ["", f"Alternative headline: {version.alt_headline}"]
    cited = {cid for p in version.paragraphs for cid in p.get("claim_ids", [])}
    used = [c for c in claims if c.claim_id in cited]
    if used:
        lines += ["", "Facts used and their sources:"]
        for c in used:
            lines.append(f"[{STATUS_LABEL.get(c.status, c.status.upper())}] {c.text}")
            for link in links.get(c.claim_id, [])[:4]:
                lines.append(f"    — {link.publisher}: {link.url}")
    if photo is not None:
        lines += [
            "",
            "Photo: "
            + "; ".join(
                x
                for x in (
                    photo.title,
                    photo.licence_name,
                    photo.attribution_text or photo.credit,
                    photo.source_page_url,
                )
                if x
            ),
        ]
    return "\n".join(lines)[:20_000]


def article_payload(
    *,
    ref: str,
    slug: str,
    language: str,
    version: ArticleVersion,
    notes: str,
    category_id: int | str | None,
    hero_media_id: int | str | None,
    photo: MediaAsset | None,
) -> dict[str, Any]:
    social = version.social or {}
    data: dict[str, Any] = {
        "title": _cut(version.headline, 200),
        "summary": _cut(version.summary, 400),
        "body": lexical([str(p.get("text", "")) for p in version.paragraphs]),
        "language": language,
        "slug": slug[:120],
        "tags": [_cut(k, 60) for k in version.keywords if k.strip()][:15],
        "seo": {
            "title": _cut(version.seo_title, 70),
            "description": _cut(version.seo_description, 170),
        },
        "distribution": {
            "socialHeadline": _cut(version.headline, 120),
            "socialSummary": _cut(
                social.get("facebook") or social.get("x") or version.summary, 280
            ),
        },
        "editorialNotes": notes,
        "newsroomRef": ref,
        "status": "draft",
    }
    if category_id is not None:
        data["categories"] = [category_id]
    if hero_media_id is not None and photo is not None:
        data["heroImage"] = hero_media_id
        data["heroImageAlt"] = _cut(version.image_caption or photo.description or photo.title, 300)
        data["heroImageCredit"] = _cut(photo.attribution_text or photo.credit or photo.creator, 160)
    return data


def media_fields(photo: MediaAsset, version: ArticleVersion) -> dict[str, Any]:
    alt = version.image_caption or photo.description or photo.title
    usage = "; ".join(
        x
        for x in (
            f"Licence: {photo.licence_name}" if photo.licence_name else None,
            photo.licence_url,
            f"Source: {photo.source_page_url}" if photo.source_page_url else None,
            f"Attribution: {photo.attribution_text}" if photo.attribution_text else None,
            photo.label,
            "Delivered by the AI newsroom",
        )
        if x
    )
    return {
        "alt": _cut(alt, 300),
        "caption": _cut(photo.caption, 300) or None,
        "credit": _cut(photo.attribution_text or photo.credit or photo.creator, 160) or None,
        "usageNotes": usage[:2000],
    }
