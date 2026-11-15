"""Seed a throwaway database for the dashboard's browser tests (frontend/tests/e2e).

    TEST_DATABASE_URL=...janaki_e2e TEST_DATABASE_OWNER_URL=...janaki_e2e \
    STORAGE_LOCAL_ROOT=/tmp/e2e-media python -m tests.e2e_seed > seed.json

Test fixtures only: fictional example.com publishers and a scripted model, never real news.
Refuses to run unless the database name contains "e2e" and the environment is not production.
It wipes that database first.
"""

from __future__ import annotations

import io
import json
import os
import sys
from datetime import UTC, datetime

if "e2e" not in os.environ.get("TEST_DATABASE_URL", "") or "e2e" not in os.environ.get(
    "TEST_DATABASE_OWNER_URL", ""
):
    sys.exit("Refusing: TEST_DATABASE_URL and TEST_DATABASE_OWNER_URL must point at an *e2e* DB.")

from alembic import command
from alembic.config import Config
from PIL import Image
from sqlalchemy import create_engine, func, select, text

import tests.conftest as cf
from app.core.config import get_settings
from app.modules.discovery.models import BackgroundJob, DiscoveredItem, NewsEvent
from app.modules.editorial.models import Article
from app.modules.visuals.models import MediaAsset
from app.modules.visuals.processing import process
from app.modules.visuals.storage import get_storage, media_key
from tests.test_discovery_run import tenant_db
from tests.test_editorial import WriterLLM, articles, researched, write

assert get_settings().environment != "production"


def main() -> None:
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    cfg.set_main_option("sqlalchemy.url", os.environ["DATABASE_OWNER_URL"])
    command.upgrade(cfg, "head")
    engine = create_engine(os.environ["DATABASE_OWNER_URL"])
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {cf.TABLES} RESTART IDENTITY CASCADE"))
    engine.dispose()

    t = cf.make_tenant("janaki-tv")
    editor = cf.make_user(t, "editor@janaki-tv.example.com", ["editor"])
    reporter = cf.make_user(t, "reporter@janaki-tv.example.com", ["reporter"])
    new_admin = cf.make_user(t, "newadmin@janaki-tv.example.com", ["tenant_admin"])
    eid = researched(t.tenant_id)
    write(t.tenant_id, eid, WriterLLM())
    arts = articles(t.tenant_id, eid)
    a_id = arts["straight"]["article"].id

    # One failed job, as a provider outage would leave it.
    with tenant_db(t.tenant_id) as db:
        db.add(
            BackgroundJob(
                tenant_id=t.tenant_id,
                job_type="research",
                idempotency_key="research:e2e-failure",
                trigger="schedule",
                status="failed",
                attempts=3,
                error="AI provider quota exceeded (e2e fixture)",
                result={"ai_error": "rate_limited"},
            )
        )

    # A selected, licensed hero photo with real derivative files.
    img = io.BytesIO()
    Image.new("RGB", (1200, 800), (40, 90, 160)).save(img, "JPEG")
    p = process(img.getvalue())
    storage = get_storage()
    with tenant_db(t.tenant_id) as db:
        m = MediaAsset(
            tenant_id=t.tenant_id,
            event_id=eid,
            article_id=a_id,
            role="hero",
            kind="photo",
            status="selected",
            provider="wikimedia_commons",
            source_page_url="https://commons.wikimedia.org/wiki/File:Example_flood.jpg",
            original_url="https://upload.wikimedia.org/example-flood.jpg",
            title="Flooded fields (e2e fixture)",
            creator="Example Photographer",
            retrieved_at=datetime.now(UTC),
            licence_name="CC BY-SA 4.0",
            licence_url="https://creativecommons.org/licenses/by-sa/4.0",
            attribution_required=True,
            attribution_text="“Flooded fields” by Example Photographer, CC BY-SA 4.0",
            commercial_use=True,
            modification_allowed=True,
            restrictions=[],
            publishable=True,
            caption="Flooded fields — Example Photographer",
            derivatives=[],
            processing_history=[],
            selected_at=datetime.now(UTC),
        )
        db.add(m)
        db.flush()
        derivs = []
        for name, data, info in p.derivatives:
            key = media_key(t.tenant_id, m.id, name)
            storage.put(key, data, info["mime"])
            derivs.append({"name": name, "key": key, **info, "bytes": len(data)})
        m.derivatives, m.mime, m.width, m.height = derivs, p.mime, p.width, p.height

    with tenant_db(t.tenant_id) as db:
        counts = {
            "items": db.scalar(select(func.count()).select_from(DiscoveredItem)),
            "events": db.scalar(select(func.count()).select_from(NewsEvent)),
            "articles": db.scalar(select(func.count()).select_from(Article)),
            "awaiting": db.scalar(
                select(func.count())
                .select_from(Article)
                .where(Article.status.in_(("draft", "needs_review")))
            ),
            "failed_jobs": db.scalar(
                select(func.count())
                .select_from(BackgroundJob)
                .where(BackgroundJob.status == "failed")
            ),
        }
    json.dump(
        {
            "password": cf.PASSWORD,
            "tenant": t.tenant_slug,
            "admin": {"email": t.email, "totp_secret": t.totp_secret},
            "editor": editor.email,
            "reporter": reporter.email,
            "new_admin": new_admin.email,
            "event_id": str(eid),
            "article_a": str(a_id),
            "article_b": str(arts["context"]["article"].id),
            "headline_a": arts["straight"]["v"].headline,
            "counts": counts,
        },
        sys.stdout,
        indent=2,
    )


if __name__ == "__main__":
    main()
