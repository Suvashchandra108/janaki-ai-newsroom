"""Import every model so Alembic sees the full metadata."""

from app.db.base import Base
from app.modules.ai_gateway.models import UsageRecord
from app.modules.audit.models import AuditLog
from app.modules.cms.models import CmsConnection, CmsDelivery
from app.modules.discovery.models import BackgroundJob, DiscoveredItem, NewsEvent, NewsSource
from app.modules.editorial.models import Article, ArticleVersion
from app.modules.identity.models import (
    ApiKey,
    AuthSession,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
)
from app.modules.research.models import Claim, Evidence, SourceDocument
from app.modules.tenancy.models import Tenant
from app.modules.visuals.models import MediaAsset

__all__ = [
    "ApiKey",
    "Article",
    "ArticleVersion",
    "AuditLog",
    "AuthSession",
    "BackgroundJob",
    "Base",
    "Claim",
    "CmsConnection",
    "CmsDelivery",
    "DiscoveredItem",
    "Evidence",
    "MediaAsset",
    "NewsEvent",
    "NewsSource",
    "Permission",
    "Role",
    "RolePermission",
    "SourceDocument",
    "Tenant",
    "UsageRecord",
    "User",
    "UserRole",
]
