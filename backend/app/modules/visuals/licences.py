"""Licence classification (docs/IMAGE_LICENSING_POLICY.md).

Allow-list, conservative by default: anything not positively recognised is reference-only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PD_MARK = "https://creativecommons.org/publicdomain/mark/1.0/"
CC0_URL = "https://creativecommons.org/publicdomain/zero/1.0/"


@dataclass(frozen=True)
class Licence:
    name: str
    url: str | None
    commercial_use: bool
    modification_allowed: bool
    attribution_required: bool
    recognised: bool
    note: str


def classify(short_name: str | None, url: str | None) -> Licence:
    name = (short_name or "").strip()
    n = name.lower().replace("_", " ")
    url = (url or "").strip() or None
    if url and not url.startswith(("https://", "http://")):
        url = None
    if not n:
        return Licence(
            name or "unknown",
            url,
            False,
            False,
            True,
            False,
            "No licence information: reference only",
        )
    if "nc" in re.split(r"[\s\-/]+", n) or "noncommercial" in n.replace("-", ""):
        return Licence(name, url, False, False, True, True, "Non-commercial licence: not usable")
    if re.search(r"\bnd\b|noderiv", n):
        return Licence(
            name,
            url,
            True,
            False,
            True,
            True,
            "No-derivatives licence: resizing for web is not allowed by our policy",
        )
    if n in ("cc0", "cc-zero") or "cc0" in n:
        return Licence(name, url or CC0_URL, True, True, False, True, "Public domain dedication")
    if n.startswith("public domain") or n.startswith("pd"):
        return Licence(
            name,
            url or PD_MARK,
            True,
            True,
            False,
            True,
            "Public domain (credit given as courtesy)",
        )
    if re.match(r"^cc[ -]by(-sa)?[ -]\d", n) or re.match(r"^cc by(-sa)? \d", n):
        sa = "-sa" in n or " sa" in n
        return Licence(
            name,
            url,
            True,
            True,
            True,
            True,
            "Attribution required" + ("; adaptations must use the same licence" if sa else ""),
        )
    if "gfdl" in n:
        return Licence(
            name,
            url,
            True,
            True,
            True,
            True,
            "GFDL-only requires reproducing the licence text: not usable",
        )
    return Licence(name, url, False, False, True, False, f"Unrecognised licence '{name}'")


def publishable(lic: Licence, attribution_text: str | None) -> bool:
    if not lic.recognised or not lic.commercial_use or not lic.modification_allowed:
        return False
    if "gfdl" in lic.name.lower() and "cc" not in lic.name.lower():
        return False
    if not lic.url:
        return False
    return not (lic.attribution_required and not attribution_text)
