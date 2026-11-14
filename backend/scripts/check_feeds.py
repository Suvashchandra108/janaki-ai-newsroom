"""Check a list of RSS sources with the production fetcher (SSRF-safe, real DNS, robots.txt).

    python -m scripts.check_feeds ../deploy/feeds/proposed_feeds.json

For each source: does the feed load and parse, how many items, newest title and date, do item
links stay on the approved domains, and does robots.txt allow fetching the first article
(needed for fact-checking). Prints a Markdown table. Never exits non-zero for a bad feed: it is
a report for humans.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from app.modules.discovery import text as dtext
from app.modules.discovery.adapters import parse_feed
from app.modules.discovery.safe_fetch import FetchError, SafeFetcher, host_allowed
from app.modules.research.documents import RobotsCache


def check(src: dict[str, Any], fetcher: SafeFetcher, robots: RobotsCache) -> dict[str, str]:
    row = {
        "name": src["name"],
        "feed": "❌",
        "items": "0",
        "newest": "",
        "links": "",
        "robots": "",
        "note": "",
    }
    try:
        res = fetcher.fetch(src["feed_url"], src["allowed_domains"])
        leads = parse_feed(res.body)
    except (FetchError, ValueError) as exc:
        row["note"] = f"{getattr(exc, 'code', 'parse')}: {exc}"[:90]
        return row
    row["feed"] = "✅"
    row["items"] = str(len(leads))
    if not leads:
        row["note"] = "feed has no items"
        return row
    newest = max(leads, key=lambda le: le.published_at.timestamp() if le.published_at else 0)
    date = newest.published_at.strftime("%Y-%m-%d") if newest.published_at else "no date"
    row["newest"] = f"{date}: {newest.title[:60]}"
    on_domain = sum(host_allowed(dtext.domain_of(le.url), src["allowed_domains"]) for le in leads)
    row["links"] = f"{on_domain}/{len(leads)} on approved domains"
    ok, reason = robots.allowed(newest.url)
    row["robots"] = "✅ allowed" if ok else f"❌ {reason}"
    return row


def main() -> None:
    sources = json.loads(Path(sys.argv[1]).read_text())["sources"]
    fetcher = SafeFetcher(timeout=15)
    robots = RobotsCache(fetcher)
    rows = [check(s, fetcher, robots) for s in sources]
    fetcher.close()
    print("| Source | Feed | Items | Newest item | Links | Article fetch (robots.txt) | Note |")
    print("|---|---|---|---|---|---|---|")
    for r in rows:
        print(
            f"| {r['name']} | {r['feed']} | {r['items']} | {r['newest']} | {r['links']} "
            f"| {r['robots']} | {r['note']} |"
        )
    good = sum(r["feed"] == "✅" and r["robots"].startswith("✅") for r in rows)
    print(f"\nUsable for discovery + fact-checking: {good}/{len(rows)}")


if __name__ == "__main__":
    main()
