"""Phase 1 API routes: auth, tenants, users, roles, API keys, audit."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import (
    get_user_principal,
    request_meta,
    require,
    require_platform_admin,
)
from app.api.v1 import schemas as s
from app.core.permissions import P
from app.core.principal import Principal
from app.db.session import get_db
from app.modules.audit import service as audit
from app.modules.identity import service as identity
from app.modules.identity.models import Role, RolePermission, User
from app.modules.tenancy import service as tenancy

auth = APIRouter(prefix="/auth", tags=["auth"])
tenants = APIRouter(prefix="/tenants", tags=["tenants"])
users = APIRouter(prefix="/users", tags=["users"])
roles = APIRouter(prefix="/roles", tags=["users"])
api_keys = APIRouter(prefix="/api-keys", tags=["api-keys"])
audit_logs = APIRouter(prefix="/audit-logs", tags=["audit"])


def _tokens(t: identity.TokenPair) -> s.TokenOut:
    return s.TokenOut(
        access_token=t.access_token,
        refresh_token=t.refresh_token,
        token_type=t.token_type,
        expires_in=t.expires_in,
    )


# --- auth ---------------------------------------------------------------------------------


@auth.post("/login", response_model=s.TokenOut)
def login(body: s.LoginIn, request: Request, db: Session = Depends(get_db)) -> s.TokenOut:
    return _tokens(
        identity.login(
            db,
            email=body.email,
            password=body.password,
            tenant_slug=body.tenant_slug,
            totp_code=body.totp_code,
            meta=request_meta(request),
        )
    )


@auth.post("/refresh", response_model=s.TokenOut)
def refresh(body: s.RefreshIn, request: Request, db: Session = Depends(get_db)) -> s.TokenOut:
    return _tokens(
        identity.refresh(db, refresh_token=body.refresh_token, meta=request_meta(request))
    )


@auth.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    body: s.LogoutIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_user_principal),
) -> None:
    identity.logout(db, principal, everywhere=body.everywhere)


@auth.get("/me", response_model=s.MeOut)
def me(principal: Principal = Depends(get_user_principal)) -> s.MeOut:
    return s.MeOut(
        kind=principal.kind,
        user_id=principal.user_id,
        email=principal.email,
        tenant_id=principal.tenant_id,
        is_platform_admin=principal.is_platform_admin,
        permissions=sorted(principal.permissions),
        mfa_enrollment_required=principal.mfa_enrollment_required,
    )


@auth.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: s.PasswordChangeIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_user_principal),
) -> None:
    identity.change_password(db, principal, current=body.current_password, new=body.new_password)


@auth.post("/mfa/setup", response_model=s.MfaSetupOut)
def mfa_setup(
    db: Session = Depends(get_db), principal: Principal = Depends(get_user_principal)
) -> s.MfaSetupOut:
    secret, uri = identity.mfa_setup(db, principal)
    return s.MfaSetupOut(secret=secret, otpauth_uri=uri)


@auth.post("/mfa/enable", status_code=status.HTTP_204_NO_CONTENT)
def mfa_enable(
    body: s.MfaCodeIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_user_principal),
) -> None:
    identity.mfa_enable(db, principal, code=body.code)


# --- tenants ------------------------------------------------------------------------------


@tenants.post("", response_model=s.TenantProvisionOut, status_code=status.HTTP_201_CREATED)
def provision_tenant(
    body: s.TenantProvisionIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_platform_admin),
) -> s.TenantProvisionOut:
    tenant, admin = tenancy.provision_tenant(
        db,
        principal,
        slug=body.slug,
        name=body.name,
        default_language=body.default_language,
        admin_email=body.admin_email,
        admin_full_name=body.admin_full_name,
        admin_password=body.admin_password,
    )
    return s.TenantProvisionOut(tenant=s.TenantOut.model_validate(tenant), admin_user_id=admin.id)


@tenants.get("", response_model=list[s.TenantOut])
def list_tenants(
    db: Session = Depends(get_db), _: Principal = Depends(require_platform_admin)
) -> list[s.TenantOut]:
    return [s.TenantOut.model_validate(t) for t in tenancy.list_tenants(db)]


@tenants.get("/current", response_model=s.TenantOut)
def current_tenant(
    db: Session = Depends(get_db), principal: Principal = Depends(require(P.TENANT_READ))
) -> s.TenantOut:
    return s.TenantOut.model_validate(tenancy.get_current(db, principal))


@tenants.patch("/current", response_model=s.TenantOut)
def update_current_tenant(
    body: s.TenantUpdateIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.TENANT_UPDATE)),
) -> s.TenantOut:
    return s.TenantOut.model_validate(
        tenancy.update_current(
            db, principal, name=body.name, default_language=body.default_language
        )
    )


@tenants.patch("/{tenant_id}", response_model=s.TenantOut)
def platform_update_tenant(
    tenant_id: uuid.UUID,
    body: s.TenantPlatformUpdateIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_platform_admin),
) -> s.TenantOut:
    return s.TenantOut.model_validate(
        tenancy.platform_update_tenant(db, principal, tenant_id, name=body.name, status=body.status)
    )


# --- users & roles ------------------------------------------------------------------------


def _user_out(db: Session, u: User) -> s.UserOut:
    out = s.UserOut.model_validate(u)
    out.roles = identity.role_keys(db, u.id)
    return out


@users.get("", response_model=list[s.UserOut])
def list_users(
    db: Session = Depends(get_db), principal: Principal = Depends(require(P.USERS_READ))
) -> list[s.UserOut]:
    rows = db.scalars(
        select(User).where(User.tenant_id == principal.tenant_id).order_by(User.created_at)
    )
    return [_user_out(db, u) for u in rows]


@users.post("", response_model=s.UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    body: s.UserCreateIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.USERS_MANAGE)),
) -> s.UserOut:
    assert principal.tenant_id
    u = identity.create_user(
        db,
        tenant_id=principal.tenant_id,
        email=body.email,
        full_name=body.full_name,
        password=body.password,
        roles=body.roles,
        kind=body.kind,
    )
    audit.record(
        db,
        principal=principal,
        action="user.created",
        tenant_id=principal.tenant_id,
        target_type="user",
        target_id=u.id,
        details={"roles": sorted(body.roles), "kind": body.kind},
    )
    return _user_out(db, u)


@users.get("/{user_id}", response_model=s.UserOut)
def get_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.USERS_READ)),
) -> s.UserOut:
    assert principal.tenant_id
    return _user_out(db, identity.get_user(db, principal.tenant_id, user_id))


@users.patch("/{user_id}", response_model=s.UserOut)
def update_user(
    user_id: uuid.UUID,
    body: s.UserUpdateIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.USERS_MANAGE)),
) -> s.UserOut:
    u = identity.update_user(
        db,
        principal,
        user_id,
        full_name=body.full_name,
        roles=body.roles,
        is_active=body.is_active,
        reset_mfa=body.reset_mfa,
    )
    return _user_out(db, u)


@roles.get("", response_model=list[s.RoleOut])
def list_roles(
    db: Session = Depends(get_db), _: Principal = Depends(require(P.USERS_READ))
) -> list[s.RoleOut]:
    out = []
    for r in db.scalars(select(Role).order_by(Role.key)):
        perms = sorted(
            db.scalars(select(RolePermission.permission_key).where(RolePermission.role_id == r.id))
        )
        out.append(s.RoleOut(key=r.key, name=r.name, description=r.description, permissions=perms))
    return out


# --- API keys -----------------------------------------------------------------------------


@api_keys.get("", response_model=list[s.ApiKeyOut])
def list_keys(
    db: Session = Depends(get_db), principal: Principal = Depends(require(P.APIKEYS_MANAGE))
) -> list[s.ApiKeyOut]:
    return [s.ApiKeyOut.model_validate(k) for k in identity.list_api_keys(db, principal)]


@api_keys.post("", response_model=s.ApiKeyCreatedOut, status_code=status.HTTP_201_CREATED)
def create_key(
    body: s.ApiKeyCreateIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.APIKEYS_MANAGE)),
) -> s.ApiKeyCreatedOut:
    key, plaintext = identity.create_api_key(
        db, principal, name=body.name, scopes=body.scopes, expires_in_days=body.expires_in_days
    )
    return s.ApiKeyCreatedOut(api_key=s.ApiKeyOut.model_validate(key), key=plaintext)


@api_keys.post("/{key_id}/rotate", response_model=s.ApiKeyCreatedOut)
def rotate_key(
    key_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.APIKEYS_MANAGE)),
) -> s.ApiKeyCreatedOut:
    key, plaintext = identity.rotate_api_key(db, principal, key_id)
    return s.ApiKeyCreatedOut(api_key=s.ApiKeyOut.model_validate(key), key=plaintext)


@api_keys.delete("/{key_id}", response_model=s.ApiKeyOut)
def revoke_key(
    key_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.APIKEYS_MANAGE)),
) -> s.ApiKeyOut:
    return s.ApiKeyOut.model_validate(identity.revoke_api_key(db, principal, key_id))


# --- audit --------------------------------------------------------------------------------


@audit_logs.get("", response_model=list[s.AuditLogOut])
def list_audit(
    action: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require(P.AUDIT_READ)),
) -> list[s.AuditLogOut]:
    assert principal.tenant_id
    rows = audit.list_logs(
        db, tenant_id=principal.tenant_id, action=action, limit=limit, offset=offset
    )
    return [s.AuditLogOut.model_validate(r) for r in rows]


ALL_ROUTERS = [auth, tenants, users, roles, api_keys, audit_logs]
