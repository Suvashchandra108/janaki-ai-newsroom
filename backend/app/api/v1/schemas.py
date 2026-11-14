from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

Lang = Literal["ne", "en"]
Slug = Field(min_length=2, max_length=63, pattern=r"^[a-z0-9](-?[a-z0-9])*$")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- auth ---------------------------------------------------------------------------------


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    tenant_slug: str | None = Field(
        default=None, max_length=63, description="Omit only for platform administrators."
    )
    totp_code: str | None = Field(default=None, max_length=10)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=200)


class LogoutIn(BaseModel):
    everywhere: bool = False


class PasswordChangeIn(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class MfaSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class MfaCodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class MeOut(BaseModel):
    kind: str
    user_id: uuid.UUID | None
    email: str | None
    tenant_id: uuid.UUID | None
    is_platform_admin: bool
    permissions: list[str]
    mfa_enrollment_required: bool


# --- tenants ------------------------------------------------------------------------------


class TenantOut(ORM):
    id: uuid.UUID
    slug: str
    name: str
    status: str
    default_language: str
    settings: dict[str, Any]
    created_at: datetime


class TenantProvisionIn(BaseModel):
    slug: str = Slug
    name: str = Field(min_length=2, max_length=200)
    default_language: Lang = "en"
    admin_email: EmailStr
    admin_full_name: str = Field(min_length=1, max_length=200)
    admin_password: str = Field(max_length=256)


class TenantProvisionOut(BaseModel):
    tenant: TenantOut
    admin_user_id: uuid.UUID


class TenantPlatformUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    status: Literal["active", "suspended"] | None = None


class TenantUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    default_language: Lang | None = None


# --- users --------------------------------------------------------------------------------


class UserOut(ORM):
    id: uuid.UUID
    tenant_id: uuid.UUID | None
    email: str
    full_name: str
    kind: str
    is_active: bool
    mfa_enabled: bool
    last_login_at: datetime | None
    created_at: datetime
    roles: list[str] = []


class UserCreateIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    password: str | None = Field(default=None, max_length=256)
    roles: list[str] = Field(min_length=1)
    kind: Literal["human", "service"] = "human"


class UserUpdateIn(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    roles: list[str] | None = Field(default=None, min_length=1)
    is_active: bool | None = None
    reset_mfa: bool = False


class RoleOut(BaseModel):
    key: str
    name: str
    description: str
    permissions: list[str]


# --- API keys -----------------------------------------------------------------------------


class ApiKeyOut(ORM):
    id: uuid.UUID
    name: str
    prefix: str
    scopes: list[str]
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None
    rotated_from_id: uuid.UUID | None


class ApiKeyCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(min_length=1)
    expires_in_days: int | None = Field(default=90, ge=1, le=730)


class ApiKeyCreatedOut(BaseModel):
    api_key: ApiKeyOut
    key: str = Field(description="Shown once. Store it securely.")


# --- audit --------------------------------------------------------------------------------


class AuditLogOut(ORM):
    id: int
    actor_type: str
    actor_id: uuid.UUID | None
    action: str
    target_type: str | None
    target_id: str | None
    ip: str | None
    request_id: str | None
    details: dict[str, Any]
    created_at: datetime
