"""Permission catalogue and system roles.

This module is the single source of truth. Migration 0001 seeds the database from it, and
``tests/test_permissions.py`` checks the two stay in sync.
"""

from __future__ import annotations

from enum import StrEnum


class P(StrEnum):
    # Tenant administration
    TENANT_READ = "tenant.read"
    TENANT_UPDATE = "tenant.update"
    USERS_READ = "users.read"
    USERS_MANAGE = "users.manage"
    APIKEYS_MANAGE = "apikeys.manage"
    AUDIT_READ = "audit.read"
    # Newsroom (used from Phase 2 onwards)
    SOURCES_MANAGE = "sources.manage"
    DISCOVERY_RUN = "discovery.run"
    EVENTS_READ = "events.read"
    EVIDENCE_REVIEW = "evidence.review"
    ARTICLES_READ = "articles.read"
    ARTICLES_CREATE = "articles.create"
    ARTICLES_EDIT = "articles.edit"
    ARTICLES_REJECT = "articles.reject"
    ARTICLES_APPROVE = "articles.approve"
    ARTICLES_PUBLISH = "articles.publish"
    MEDIA_MANAGE = "media.manage"
    CMS_MANAGE = "cms.manage"
    USAGE_READ = "usage.read"
    BILLING_MANAGE = "billing.manage"


class PlatformP(StrEnum):
    """Permissions held only by SaaS super admins (users.is_platform_admin)."""

    TENANTS_MANAGE = "platform.tenants.manage"


DESCRIPTIONS: dict[str, str] = {
    P.TENANT_READ: "View own organisation settings",
    P.TENANT_UPDATE: "Change own organisation settings",
    P.USERS_READ: "View users",
    P.USERS_MANAGE: "Create, update and deactivate users",
    P.APIKEYS_MANAGE: "Create, rotate and revoke API keys",
    P.AUDIT_READ: "Read the audit log",
    P.SOURCES_MANAGE: "Manage approved news sources",
    P.DISCOVERY_RUN: "Run or pause discovery",
    P.EVENTS_READ: "Read discovered events",
    P.EVIDENCE_REVIEW: "Review and mark evidence",
    P.ARTICLES_READ: "Read articles and drafts",
    P.ARTICLES_CREATE: "Create drafts",
    P.ARTICLES_EDIT: "Edit drafts",
    P.ARTICLES_REJECT: "Reject or request correction",
    P.ARTICLES_APPROVE: "Approve articles (human only)",
    P.ARTICLES_PUBLISH: "Publish articles (human only)",
    P.MEDIA_MANAGE: "Manage media library",
    P.CMS_MANAGE: "Manage CMS and website settings",
    P.USAGE_READ: "View usage and spend",
    P.BILLING_MANAGE: "Manage subscription and billing",
}

# Editorial responsibility: these are never effective for service accounts or API keys,
# whatever role or scope they are given.
HUMAN_ONLY: frozenset[str] = frozenset({P.ARTICLES_APPROVE, P.ARTICLES_PUBLISH})

# API keys are for integrations; they may never administer identity or billing.
API_KEY_FORBIDDEN: frozenset[str] = HUMAN_ONLY | {
    P.USERS_MANAGE,
    P.APIKEYS_MANAGE,
    P.BILLING_MANAGE,
    P.TENANT_UPDATE,
}
API_KEY_ALLOWED: frozenset[str] = frozenset(p.value for p in P) - API_KEY_FORBIDDEN

ROLES: dict[str, dict[str, object]] = {
    "tenant_admin": {
        "name": "Tenant Admin",
        "description": "Full control of the organisation",
        "permissions": [p.value for p in P],
    },
    "editor": {
        "name": "Editor",
        "description": "Reviews, edits, approves and publishes",
        "permissions": [
            P.TENANT_READ,
            P.USERS_READ,
            P.EVENTS_READ,
            P.EVIDENCE_REVIEW,
            P.ARTICLES_READ,
            P.ARTICLES_CREATE,
            P.ARTICLES_EDIT,
            P.ARTICLES_REJECT,
            P.ARTICLES_APPROVE,
            P.ARTICLES_PUBLISH,
            P.MEDIA_MANAGE,
            P.USAGE_READ,
            P.DISCOVERY_RUN,
        ],
    },
    "reviewer": {
        "name": "Reviewer",
        "description": "Fact-checks evidence and requests corrections",
        "permissions": [
            P.TENANT_READ,
            P.EVENTS_READ,
            P.EVIDENCE_REVIEW,
            P.ARTICLES_READ,
            P.ARTICLES_REJECT,
        ],
    },
    "reporter": {
        "name": "Reporter",
        "description": "Writes and edits drafts",
        "permissions": [
            P.TENANT_READ,
            P.EVENTS_READ,
            P.ARTICLES_READ,
            P.ARTICLES_CREATE,
            P.ARTICLES_EDIT,
            P.MEDIA_MANAGE,
        ],
    },
}

ADMIN_ROLES: frozenset[str] = frozenset({"tenant_admin"})


def effective_user_permissions(granted: set[str], *, is_service: bool) -> frozenset[str]:
    perms = set(granted)
    if is_service:
        perms -= HUMAN_ONLY
    return frozenset(perms)


def effective_api_key_permissions(scopes: set[str]) -> frozenset[str]:
    return frozenset(scopes & API_KEY_ALLOWED)
