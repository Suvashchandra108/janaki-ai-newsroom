"""AI illustrations (policy §5): only when no suitable licensed photo exists, always labelled,
never depicting identifiable real people or presented as documentary evidence.

No image-generation provider is configured yet: ``get_image_generator`` returns None and the
API answers 503. The prompt builder and labelling rules are in place for when one is added.
"""

from __future__ import annotations

import re
from typing import Protocol

from app.modules.visuals.models import AI_LABEL

LABEL = f"{AI_LABEL} — not a photograph of the event"
_BANNED = re.compile(r"\b(photo|photograph|realistic|portrait|face|selfie)\b", re.I)


class ImageGenerator(Protocol):
    name: str
    model: str

    def generate(self, prompt: str) -> bytes: ...


def build_prompt(*, category: str | None, location: str | None, topic_keywords: list[str]) -> str:
    """Symbolic editorial illustration. Uses topic words and place only — never people's names
    (event keywords may contain names, so only generic words are kept)."""
    words = [w for w in topic_keywords if w.isalpha() and w.islower() and len(w) > 3][:5]
    words = [w for w in words if not _BANNED.search(w)]
    subject = ", ".join(words) or (category or "news")
    place = f" in {location}" if location else ""
    return (
        f"Flat, symbolic editorial illustration about {subject}{place}. Clearly an "
        "illustration, not a photograph. No identifiable people, no faces, no text, no logos, "
        "no flags of real organisations."
    )


def get_image_generator() -> ImageGenerator | None:
    return None
