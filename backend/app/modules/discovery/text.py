"""URL canonicalisation, fingerprints and lightweight event clustering (v1).

Clustering v1 is deliberately simple and explainable: keyword overlap of headlines plus a
64-bit SimHash. Semantic embeddings (pgvector) are planned once the AI gateway exists.
"""

from __future__ import annotations

import hashlib
import html
import re
from collections.abc import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "igshid", "ref", "ref_src", "cmpid"}

STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "if",
        "of",
        "on",
        "in",
        "at",
        "to",
        "for",
        "from",
        "by",
        "with",
        "without",
        "into",
        "onto",
        "over",
        "under",
        "about",
        "after",
        "before",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "has",
        "have",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "shall",
        "should",
        "can",
        "could",
        "may",
        "might",
        "must",
        "not",
        "no",
        "yes",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "he",
        "she",
        "they",
        "them",
        "his",
        "her",
        "their",
        "we",
        "our",
        "you",
        "your",
        "i",
        "me",
        "my",
        "who",
        "whom",
        "which",
        "what",
        "when",
        "where",
        "why",
        "how",
        "than",
        "then",
        "there",
        "here",
        "also",
        "just",
        "more",
        "most",
        "less",
        "least",
        "very",
        "new",
        "says",
        "said",
        "say",
        "amid",
        "after",
        "over",
        "up",
        "down",
        "out",
        "off",
        "per",
        "via",
        "vs",
        "news",
        "update",
        "updates",
        "live",
        "latest",
        "report",
        "reports",
        "today",
        "yesterday",
        "breaking",
        "video",
        "photos",
        "watch",
    ]
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"\w+", re.UNICODE)


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    port = f":{parts.port}" if parts.port and parts.port not in (80, 443) else ""
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if len(path) > 1:
        path = path.rstrip("/")
    query = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
    )
    return urlunsplit(
        (
            "https" if scheme in ("http", "https") else scheme,
            host + port,
            path,
            urlencode(query),
            "",
        )
    )


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def domain_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def clean_text(value: str | None, limit: int) -> str:
    if not value:
        return ""
    # Strip, unescape, strip again: feeds often double-encode HTML (&lt;p&gt;).
    text = _TAG_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", value)))
    return _WS_RE.sub(" ", text).strip()[:limit]


def stem(word: str) -> str:
    """Very light English suffix stripping so 'displaced' and 'displaces' compare equal."""
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def tokens(text: str) -> list[str]:
    return [
        stem(w)
        for w in (m.group(0).lower() for m in _WORD_RE.finditer(text))
        if len(w) > 2 and w not in STOPWORDS and not w.isdigit()
    ]


def keywords(title: str) -> list[str]:
    return sorted(set(tokens(title)))[:40]


def simhash64(words: Iterable[str]) -> int:
    """Signed 64-bit SimHash (fits PostgreSQL BIGINT)."""
    vec = [0] * 64
    seen = False
    for w in words:
        seen = True
        h = int.from_bytes(hashlib.blake2b(w.encode(), digest_size=8).digest(), "big")
        for i in range(64):
            vec[i] += 1 if (h >> i) & 1 else -1
    if not seen:
        return 0
    value = sum(1 << i for i in range(64) if vec[i] > 0)
    return value - (1 << 64) if value >= (1 << 63) else value


def hamming(a: int, b: int) -> int:
    return bin((a ^ b) & ((1 << 64) - 1)).count("1")


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def same_event(kw_a: list[str], hash_a: int, kw_b: list[str], hash_b: int) -> bool:
    shared = len(set(kw_a) & set(kw_b))
    if shared >= 4 or (shared >= 3 and jaccard(kw_a, kw_b) >= 0.4):
        return True
    return shared >= 2 and hamming(hash_a, hash_b) <= 6
