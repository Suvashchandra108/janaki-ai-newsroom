"""Database engine, sessions and tenant context.

Tenant context is stored in transaction-local PostgreSQL settings, read by RLS policies:

* ``app.tenant_id``  — the tenant whose rows are visible.
* ``app.bypass_rls`` — 'on' only inside :func:`system_scope` (see docs/SECURITY.md §3).

Because the settings are transaction-local, a request must not commit and then keep
querying tenant data; :func:`get_db` commits once, at the end of the request.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True, future=True)


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def new_session() -> Session:
    return _session_factory()()


def get_db() -> Iterator[Session]:
    db = new_session()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def set_tenant_context(db: Session, tenant_id: uuid.UUID | None) -> None:
    db.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"),
        {"t": str(tenant_id) if tenant_id else ""},
    )


@contextmanager
def system_scope(db: Session) -> Iterator[Session]:
    """Temporarily bypass RLS within the current transaction. Keep call sites minimal.

    Pending ORM changes are flushed *before* the bypass is switched off; otherwise
    autoflush=False would defer the UPDATE until after, and RLS would silently match 0 rows.
    """
    db.execute(text("SELECT set_config('app.bypass_rls', 'on', true)"))
    try:
        yield db
        db.flush()
    finally:
        if db.is_active:
            db.execute(text("SELECT set_config('app.bypass_rls', 'off', true)"))
