from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RequestMeta:
    ip: str | None = None
    user_agent: str | None = None
    request_id: str | None = None


@dataclass(frozen=True)
class Principal:
    """The authenticated caller. Built only from server-verified credentials."""

    kind: str  # "user" | "api_key"
    tenant_id: uuid.UUID | None
    permissions: frozenset[str]
    user_id: uuid.UUID | None = None
    api_key_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    is_platform_admin: bool = False
    is_service: bool = False
    mfa_enrollment_required: bool = False
    email: str | None = None
    meta: RequestMeta = field(default_factory=RequestMeta)

    @property
    def actor_id(self) -> uuid.UUID | None:
        return self.user_id if self.kind == "user" else self.api_key_id
