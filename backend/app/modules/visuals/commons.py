"""Wikimedia Commons image search (licence-first).

Uses the public MediaWiki API through ``SafeFetcher`` (approved hosts only). Results carry the
file's licence, author and attribution data from Commons' ``extmetadata``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urlencode

from app.modules.discovery.safe_fetch import SafeFetcher
from app.modules.discovery.text import clean_text
from app.modules.visuals.licences import Licence, classify

API = "https://commons.wikimedia.org/w/api.php"
# All Wikimedia Foundation media hosts (commons., upload., thumb., ...). Subdomains match.
DOMAINS = ["wikimedia.org"]
IMAGE_MIMES = ("image/jpeg", "image/png", "image/webp")


@dataclass(frozen=True)
class CommonsImage:
    title: str
    page_url: str
    original_url: str
    download_url: str  # a ~1600px rendition, so we never pull huge originals
    mime: str
    width: int
    height: int
    description: str | None
    creator: str | None
    credit: str | None
    licence: Licence
    attribution_text: str | None
    restrictions: list[str]


def search_url(query: str, limit: int = 8, width: int = 1600) -> str:
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "generator": "search",
        "gsrnamespace": "6",
        "gsrlimit": str(limit),
        "gsrsearch": f"{query} filetype:bitmap",
        "prop": "imageinfo",
        "iiprop": "url|extmetadata|size|mime",
        "iiurlwidth": str(width),
    }
    return f"{API}?{urlencode(params)}"


def _meta(ext: dict[str, dict[str, str]], key: str, limit: int = 500) -> str | None:
    value = (ext.get(key) or {}).get("value")
    text = clean_text(str(value), limit) if value else ""
    return text or None


def parse_search(payload: dict) -> list[CommonsImage]:
    out: list[CommonsImage] = []
    pages = sorted((payload.get("query") or {}).get("pages") or [], key=lambda p: p.get("index", 0))
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        mime = info.get("mime", "")
        if mime not in IMAGE_MIMES or not info.get("url"):
            continue
        ext = info.get("extmetadata") or {}
        lic = classify(_meta(ext, "LicenseShortName", 100), _meta(ext, "LicenseUrl", 500))
        creator = _meta(ext, "Artist", 300)
        title = re.sub(
            r"\.(jpe?g|png|webp|tiff?)$",
            "",
            page.get("title", "").removeprefix("File:"),
            flags=re.I,
        )
        attribution = None
        if lic.recognised:
            who = creator or _meta(ext, "Credit", 300) or "unknown author"
            attribution = (
                f"“{title}” by {who}, {lic.name}"
                + (f" ({lic.url})" if lic.url else "")
                + ", via Wikimedia Commons"
            )
        restrictions = [r for r in (_meta(ext, "Restrictions", 200) or "").split("|") if r]
        out.append(
            CommonsImage(
                title=title[:500],
                page_url=info.get("descriptionurl", "")[:2000],
                original_url=info["url"][:2000],
                download_url=(info.get("thumburl") or info["url"])[:2000],
                mime=mime,
                width=int(info.get("width") or 0),
                height=int(info.get("height") or 0),
                description=_meta(ext, "ImageDescription", 1000),
                creator=creator,
                credit=_meta(ext, "Credit", 500),
                licence=lic,
                attribution_text=attribution,
                restrictions=restrictions,
            )
        )
    return out


def search(fetcher: SafeFetcher, query: str, limit: int = 8) -> list[CommonsImage]:
    res = fetcher.fetch(search_url(query, limit), DOMAINS, content_types=("json",))
    return parse_search(json.loads(res.body))
