"""Bootstrap commands. Passwords are read from env vars or an interactive prompt, never argv.

    python -m scripts.bootstrap platform-admin --email ops@example.com --name "Ops"
    python -m scripts.bootstrap tenant --slug janaki-tv --name "Janaki Television" \
        --admin-email admin@janakitv.example.com --admin-name "Janaki Admin"
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

from app.db.session import new_session
from app.modules.identity.service import create_platform_admin
from app.modules.tenancy.service import provision_tenant


def _password(env: str) -> str:
    value = os.environ.get(env)
    if value:
        return value
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match.")
    return first


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
    args = parser.parse_args()

    db = new_session()
    try:
        if args.cmd == "platform-admin":
            user = create_platform_admin(
                db, email=args.email, full_name=args.name, password=_password("BOOTSTRAP_PASSWORD")
            )
            print(f"Platform admin created: {user.id}. Sign in and enrol MFA immediately.")
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
