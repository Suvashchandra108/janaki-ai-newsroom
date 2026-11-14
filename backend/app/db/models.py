"""Import every model so Alembic sees the full metadata."""

from app.db.base import Base
from app.modules.audit.models import AuditLog
from app.modules.discovery.models import BackgroundJob, DiscoveredItem, NewsEvent, NewsSource
from app.modules.identity.models import (
    ApiKey,
    AuthSession,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
)
from app.modules.tenancy.models import Tenant

__all__ = [
    "ApiKey",
    "AuditLog",
    "AuthSession",
    "BackgroundJob",
    "Base",
    "DiscoveredItem",
    "NewsEvent",
    "NewsSource",
    "Permission",
    "Role",
    "RolePermission",
    "Tenant",
    "User",
    "UserRole",
]
