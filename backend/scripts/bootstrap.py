"""Bootstrap commands. Passwords are read from env vars or an interactive prompt, never argv.

    python -m scripts.bootstrap platform-admin --email ops@example.com --name "Ops"
    python -m scripts.bootstrap tenant --slug janaki-tv --name "Janaki Television" \
        --admin-email admin@janakitv.example.com --admin-name "Janaki Admin"
    python -m scripts.bootstrap sources --tenant janaki-tv --file ../deploy/feeds/approved.json
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import new_session, set_tenant_context, system_scope
from app.modules.audit import service as audit
from app.modules.discovery.models import NewsSource
from app.modules.discovery.service import SOURCE_FIELDS, validate_source
from app.modules.identity.service import create_platform_admin
from app.modules.tenancy.models import Tenant
from app.modules.tenancy.service import provision_tenant


def _password(env: str) -> str:
    value = os.environ.get(env)
    if value:
        return value
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match.")
    return first


def import_sources(db: Session, tenant_slug: str, path: str) -> None:
    with system_scope(db):
        tenant = db.scalar(select(Tenant).where(Tenant.slug == tenant_slug))
    if tenant is None:
        sys.exit(f"No tenant {tenant_slug!r}")
    set_tenant_context(db, tenant.id)
    added = skipped = 0
    for raw in json.loads(Path(path).read_text())["sources"]:
        data = {k: v for k, v in raw.items() if k in SOURCE_FIELDS}
        if db.scalar(select(NewsSource.id).where(NewsSource.feed_url == data.get("feed_url"))):
            skipped += 1
            continue
        validate_source("rss", data)
        src = NewsSource(tenant_id=tenant.id, kind="rss", **data)
        db.add(src)
        db.flush()
        audit.record(
            db,
            action="source.imported",
            tenant_id=tenant.id,
            actor_type="system",
            target_type="news_source",
            target_id=src.id,
            details={"name": src.name},
        )
        added += 1
    print(f"Imported {added} sources into {tenant_slug} ({skipped} already present).")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    pa = sub.add_parser("platform-admin")
    pa.add_argument("--email", required=True)
    pa.add_argument("--name", required=True)
    t = sub.add_parser("tenant")
    t.add_argument("--slug", required=True)
    t.add_argument("--name", required=True)
    t.add_argument("--language", default="en", choices=["ne", "en"])
    t.add_argument("--admin-email", required=True)
    t.add_argument("--admin-name", required=True)
    so = sub.add_parser("sources", help="import approved RSS sources (skips existing feeds)")
    so.add_argument("--tenant", required=True)
    so.add_argument("--file", required=True)
    args = parser.parse_args()

    db = new_session()
    try:
        if args.cmd == "platform-admin":
            user = create_platform_admin(
                db, email=args.email, full_name=args.name, password=_password("BOOTSTRAP_PASSWORD")
            )
            print(f"Platform admin created: {user.id}. Sign in and enrol MFA immediately.")
        elif args.cmd == "sources":
            import_sources(db, args.tenant, args.file)
        else:
            tenant, admin = provision_tenant(
                db,
                None,
                slug=args.slug,
                name=args.name,
                default_language=args.language,
                admin_email=args.admin_email,
                admin_full_name=args.admin_name,
                admin_password=_password("BOOTSTRAP_PASSWORD"),
            )
            print(f"Tenant {tenant.slug} ({tenant.id}) created; admin user {admin.id}.")
        db.commit()
    except Exception as exc:
        db.rollback()
        sys.exit(f"Failed: {exc}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
