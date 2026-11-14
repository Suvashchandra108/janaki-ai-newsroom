"""Guards the model registry Alembic relies on (a lint auto-fix once removed an import here)."""

from __future__ import annotations

from app.db.models import Base

EXPECTED_TABLES = {
    "tenants",
    "users",
    "permissions",
    "roles",
    "role_permissions",
    "user_roles",
    "auth_sessions",
    "api_keys",
    "audit_logs",
    "news_sources",
    "news_events",
    "discovered_items",
    "background_jobs",
    "source_documents",
    "claims",
    "evidence",
    "usage_records",
    "articles",
    "article_versions",
}


def test_every_table_is_registered_for_migrations() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES
