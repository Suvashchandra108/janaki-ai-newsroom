"""Identity: users, roles, login, sessions, MFA and API keys."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import get_settings
from app.core.errors import AppError, Conflict, Forbidden, NotFound, Unauthorized
from app.core.permissions import (
    ADMIN_ROLES,
    API_KEY_ALLOWED,
    PlatformP,
    effective_api_key_permissions,
    effective_user_permissions,
)
from app.core.principal import Principal, RequestMeta
from app.db.session import set_tenant_context, system_scope
from app.modules.audit import service as audit
from app.modules.identity.models import ApiKey, AuthSession, Role, RolePermission, User, UserRole
from app.modules.tenancy.models import Tenant

GENERIC_LOGIN_ERROR = "Invalid credentials or account temporarily locked."


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "bearer"  # noqa: S105 - token type label, not a secret


# --- helpers ------------------------------------------------------------------------------


def normalise_email(email: str) -> str:
    return email.strip().lower()


def validate_password(password: str) -> None:
    s = get_settings()
    if len(password) < s.password_min_length:
        raise AppError(
            f"Password must be at least {s.password_min_length} characters.",
            code="weak_password",
            status_code=422,
        )
    if len(password) > 128:
        raise AppError("Password is too long.", code="weak_password", status_code=422)


def role_keys(db: Session, user_id: uuid.UUID) -> list[str]:
    q = (
        select(Role.key)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    )
    return sorted(db.scalars(q))


def _granted_permissions(db: Session, user_id: uuid.UUID) -> set[str]:
    q = (
        select(RolePermission.permission_key)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .where(UserRole.user_id == user_id)
    )
    return set(db.scalars(q))


def mfa_required(db: Session, user: User) -> bool:
    if not get_settings().mfa_required_for_admins:
        return False
    return user.is_platform_admin or bool(ADMIN_ROLES & set(role_keys(db, user.id)))


def _set_roles(db: Session, user: User, keys: list[str]) -> None:
    if user.tenant_id is None:
        raise AppError("Platform users have no tenant roles.")
    roles = list(db.scalars(select(Role).where(Role.key.in_(keys))))
    missing = set(keys) - {r.key for r in roles}
    if missing:
        raise AppError(
            f"Unknown roles: {', '.join(sorted(missing))}", code="unknown_role", status_code=422
        )
    db.execute(delete(UserRole).where(UserRole.user_id == user.id))
    for r in roles:
        db.add(UserRole(user_id=user.id, role_id=r.id, tenant_id=user.tenant_id))
    db.flush()


# --- user management ----------------------------------------------------------------------


def create_user(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    email: str,
    full_name: str,
    password: str | None,
    roles: list[str],
    kind: str = "human",
) -> User:
    if kind == "human":
        if not password:
            raise AppError("Password required for human users.", status_code=422)
        validate_password(password)
    elif password:
        raise AppError("Service accounts cannot have passwords.", status_code=422)
    user = User(
        tenant_id=tenant_id,
        email=normalise_email(email),
        full_name=full_name.strip(),
        password_hash=security.hash_password(password) if password else None,
        kind=kind,
        password_changed_at=security.utcnow() if password else None,
    )
    db.add(user)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError as exc:
        raise Conflict("A user with this email already exists in this organisation.") from exc
    _set_roles(db, user, roles)
    return user


def create_platform_admin(db: Session, *, email: str, full_name: str, password: str) -> User:
    validate_password(password)
    with system_scope(db):
        user = User(
            tenant_id=None,
            email=normalise_email(email),
            full_name=full_name.strip(),
            password_hash=security.hash_password(password),
            is_platform_admin=True,
            password_changed_at=security.utcnow(),
        )
        db.add(user)
        try:
            with db.begin_nested():
                db.flush()
        except IntegrityError as exc:
            raise Conflict("Platform admin already exists.") from exc
        audit.record(
            db,
            action="platform_admin.created",
            tenant_id=None,
            actor_type="system",
            target_type="user",
            target_id=user.id,
        )
    return user


def get_user(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User:
    user = db.scalar(select(User).where(User.id == user_id, User.tenant_id == tenant_id))
    if not user:
        raise NotFound("User not found.")
    return user


def _active_admin_count(db: Session, tenant_id: uuid.UUID) -> int:
    q = (
        select(func.count(func.distinct(User.id)))
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(User.tenant_id == tenant_id, User.is_active.is_(True), Role.key.in_(ADMIN_ROLES))
    )
    return int(db.scalar(q) or 0)


def update_user(
    db: Session,
    principal: Principal,
    user_id: uuid.UUID,
    *,
    full_name: str | None,
    roles: list[str] | None,
    is_active: bool | None,
    reset_mfa: bool,
) -> User:
    assert principal.tenant_id is not None
    user = get_user(db, principal.tenant_id, user_id)
    changes: dict[str, Any] = {}
    was_admin = bool(ADMIN_ROLES & set(role_keys(db, user.id))) and user.is_active
    if full_name is not None:
        user.full_name = full_name.strip()
        changes["full_name"] = True
    if roles is not None:
        _set_roles(db, user, roles)
        changes["roles"] = sorted(roles)
    if is_active is not None and is_active != user.is_active:
        if user.id == principal.user_id and not is_active:
            raise Forbidden("You cannot deactivate your own account.")
        user.is_active = is_active
        changes["is_active"] = is_active
        if not is_active:
            revoke_all_sessions(db, user.id, reason="deactivated")
    if reset_mfa:
        user.mfa_enabled = False
        user.mfa_secret_enc = None
        user.mfa_last_counter = None
        revoke_all_sessions(db, user.id, reason="mfa_reset")
        changes["mfa_reset"] = True
    db.flush()
    if was_admin and _active_admin_count(db, principal.tenant_id) == 0:
        raise Conflict("An organisation must keep at least one active tenant admin.")
    audit.record(
        db,
        principal=principal,
        action="user.updated",
        tenant_id=principal.tenant_id,
        target_type="user",
        target_id=user.id,
        details=changes,
    )
    return user


# --- sessions -----------------------------------------------------------------------------


def _new_session(db: Session, user: User, meta: RequestMeta) -> TokenPair:
    secret, digest = security.new_refresh_secret()
    sess = AuthSession(
        tenant_id=user.tenant_id,
        user_id=user.id,
        refresh_token_hash=digest,
        expires_at=security.utcnow() + timedelta(days=get_settings().refresh_token_ttl_days),
        ip=meta.ip,
        user_agent=(meta.user_agent or "")[:400] or None,
    )
    db.add(sess)
    db.flush()
    access, ttl = security.create_access_token(
        user_id=user.id, session_id=sess.id, tenant_id=user.tenant_id
    )
    return TokenPair(access_token=access, refresh_token=f"{sess.id}.{secret}", expires_in=ttl)


def revoke_all_sessions(
    db: Session, user_id: uuid.UUID, *, reason: str, except_session: uuid.UUID | None = None
) -> None:
    q = select(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
    for s in db.scalars(q):
        if s.id != except_session:
            s.revoked_at = security.utcnow()
            s.revoked_reason = reason
    db.flush()


def _register_failure(
    db: Session, user: User | None, tenant_id: uuid.UUID | None, meta: RequestMeta, reason: str
) -> None:
    s = get_settings()
    if user is not None:
        user.failed_login_count += 1
        if user.failed_login_count >= s.login_max_failures:
            user.locked_until = security.utcnow() + timedelta(minutes=s.login_lockout_minutes)
            user.failed_login_count = 0
            reason += "+locked"
    audit.record(
        db,
        action="auth.login_failed",
        tenant_id=tenant_id,
        meta=meta,
        actor_type="anon",
        actor_id=user.id if user else None,
        details={"reason": reason},
    )
    # Persist the failure even though the request will end in an error (rolled back).
    db.commit()


def login(
    db: Session,
    *,
    email: str,
    password: str,
    tenant_slug: str | None,
    totp_code: str | None,
    meta: RequestMeta,
) -> TokenPair:
    email = normalise_email(email)
    with system_scope(db):
        tenant: Tenant | None = None
        if tenant_slug:
            tenant = db.scalar(select(Tenant).where(Tenant.slug == tenant_slug.strip().lower()))
            if tenant is None:
                security.verify_password(password, None)  # equalise timing
                raise Unauthorized(GENERIC_LOGIN_ERROR, code="invalid_credentials")
            user = db.scalar(select(User).where(User.tenant_id == tenant.id, User.email == email))
        else:
            user = db.scalar(select(User).where(User.tenant_id.is_(None), User.email == email))
        tid = tenant.id if tenant else None

        now = security.utcnow()
        if user is not None and user.locked_until and user.locked_until > now:
            security.verify_password(password, None)
            _register_failure(db, None, tid, meta, "locked")
            raise Unauthorized(GENERIC_LOGIN_ERROR, code="invalid_credentials")

        ok = security.verify_password(password, user.password_hash if user else None)
        if not ok or user is None:
            _register_failure(db, user, tid, meta, "bad_password")
            raise Unauthorized(GENERIC_LOGIN_ERROR, code="invalid_credentials")
        if not user.is_active or user.kind != "human":
            _register_failure(db, user, tid, meta, "inactive_or_service")
            raise Unauthorized(GENERIC_LOGIN_ERROR, code="invalid_credentials")

        if user.mfa_enabled:
            if not totp_code:
                raise Unauthorized("Enter your authenticator code.", code="mfa_required")
            secret = security.decrypt_secret(user.mfa_secret_enc or "")
            counter = security.verify_totp(secret, totp_code, last_counter=user.mfa_last_counter)
            if counter is None:
                _register_failure(db, user, tid, meta, "bad_totp")
                raise Unauthorized("Invalid authenticator code.", code="invalid_mfa_code")
            user.mfa_last_counter = counter

        if tenant is not None and tenant.status != "active":
            raise Forbidden("This organisation's account is suspended.", code="tenant_suspended")

        if security.password_needs_rehash(user.password_hash or ""):
            user.password_hash = security.hash_password(password)
        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = now
        tokens = _new_session(db, user, meta)
        audit.record(
            db, action="auth.login", tenant_id=tid, meta=meta, actor_type="user", actor_id=user.id
        )
    return tokens


def refresh(db: Session, *, refresh_token: str, meta: RequestMeta) -> TokenPair:
    invalid = Unauthorized("Session expired. Please sign in again.", code="invalid_refresh_token")
    try:
        sid_str, secret = refresh_token.split(".", 1)
        sid = uuid.UUID(sid_str)
    except ValueError as exc:
        raise invalid from exc
    digest = security.sha256_hex(secret)
    with system_scope(db):
        sess = db.get(AuthSession, sid)
        if sess is None or sess.revoked_at is not None or sess.expires_at <= security.utcnow():
            raise invalid
        if not security.constant_eq(digest, sess.refresh_token_hash):
            if sess.previous_refresh_token_hash and security.constant_eq(
                digest, sess.previous_refresh_token_hash
            ):
                # A rotated token was replayed: assume theft, kill the session.
                sess.revoked_at = security.utcnow()
                sess.revoked_reason = "refresh_reuse"
                audit.record(
                    db,
                    action="auth.refresh_reuse_detected",
                    tenant_id=sess.tenant_id,
                    meta=meta,
                    actor_type="user",
                    actor_id=sess.user_id,
                )
                db.commit()
            raise invalid
        user = db.get(User, sess.user_id)
        tenant = db.get(Tenant, sess.tenant_id) if sess.tenant_id else None
        if user is None or not user.is_active or (tenant is not None and tenant.status != "active"):
            raise invalid
        new_secret, new_digest = security.new_refresh_secret()
        sess.previous_refresh_token_hash = sess.refresh_token_hash
        sess.refresh_token_hash = new_digest
        sess.last_used_at = security.utcnow()
        access, ttl = security.create_access_token(
            user_id=user.id, session_id=sess.id, tenant_id=user.tenant_id
        )
        db.flush()
    return TokenPair(access_token=access, refresh_token=f"{sess.id}.{new_secret}", expires_in=ttl)


def logout(db: Session, principal: Principal, *, everywhere: bool) -> None:
    assert principal.user_id and principal.session_id
    with system_scope(db) if principal.tenant_id is None else _noop(db):
        if everywhere:
            revoke_all_sessions(db, principal.user_id, reason="logout_all")
        else:
            sess = db.get(AuthSession, principal.session_id)
            if sess and sess.revoked_at is None:
                sess.revoked_at = security.utcnow()
                sess.revoked_reason = "logout"
        audit.record(
            db,
            principal=principal,
            action="auth.logout",
            tenant_id=principal.tenant_id,
            details={"everywhere": everywhere},
        )


class _noop:
    def __init__(self, db: Session) -> None:
        self.db = db

    def __enter__(self) -> Session:
        return self.db

    def __exit__(self, *exc: object) -> None:
        return None


def _load_self(db: Session, principal: Principal) -> User:
    assert principal.user_id
    user = db.get(User, principal.user_id)
    if user is None:
        raise NotFound("User not found.")
    return user


def change_password(db: Session, principal: Principal, *, current: str, new: str) -> None:
    with system_scope(db) if principal.tenant_id is None else _noop(db):
        user = _load_self(db, principal)
        if not security.verify_password(current, user.password_hash):
            raise Unauthorized("Current password is incorrect.", code="invalid_credentials")
        validate_password(new)
        user.password_hash = security.hash_password(new)
        user.password_changed_at = security.utcnow()
        revoke_all_sessions(
            db, user.id, reason="password_changed", except_session=principal.session_id
        )
        audit.record(
            db, principal=principal, action="auth.password_changed", tenant_id=principal.tenant_id
        )


# --- MFA ----------------------------------------------------------------------------------


def mfa_setup(db: Session, principal: Principal) -> tuple[str, str]:
    with system_scope(db) if principal.tenant_id is None else _noop(db):
        user = _load_self(db, principal)
        if user.mfa_enabled:
            raise Conflict("MFA is already enabled. Ask an admin to reset it.")
        secret = security.new_totp_secret()
        user.mfa_secret_enc = security.encrypt_secret(secret)
        db.flush()
        return secret, security.totp_uri(secret, user.email)


def mfa_enable(db: Session, principal: Principal, *, code: str) -> None:
    with system_scope(db) if principal.tenant_id is None else _noop(db):
        user = _load_self(db, principal)
        if user.mfa_enabled:
            raise Conflict("MFA is already enabled.")
        if not user.mfa_secret_enc:
            raise AppError("Start MFA setup first.", code="mfa_not_started")
        counter = security.verify_totp(
            security.decrypt_secret(user.mfa_secret_enc), code, last_counter=None
        )
        if counter is None:
            raise AppError("Invalid authenticator code.", code="invalid_mfa_code")
        user.mfa_enabled = True
        user.mfa_last_counter = counter
        revoke_all_sessions(db, user.id, reason="mfa_enabled", except_session=principal.session_id)
        audit.record(
            db, principal=principal, action="auth.mfa_enabled", tenant_id=principal.tenant_id
        )


# --- principals ---------------------------------------------------------------------------


def principal_from_access_token(db: Session, token: str, meta: RequestMeta) -> Principal:
    invalid = Unauthorized("Invalid or expired token.", code="invalid_token")
    try:
        claims = security.decode_access_token(token)
        user_id = uuid.UUID(claims["sub"])
        session_id = uuid.UUID(claims["sid"])
        tenant_id = uuid.UUID(claims["tid"]) if claims.get("tid") else None
    except Exception as exc:
        raise invalid from exc

    if tenant_id is not None:
        set_tenant_context(db, tenant_id)
        ctx: Any = _noop(db)
    else:
        ctx = system_scope(db)  # platform users have tenant_id NULL rows
    with ctx:
        sess = db.get(AuthSession, session_id)
        if (
            sess is None
            or sess.user_id != user_id
            or sess.revoked_at is not None
            or sess.expires_at <= security.utcnow()
            or sess.tenant_id != tenant_id
        ):
            raise invalid
        user = db.get(User, user_id)
        if user is None or not user.is_active or user.tenant_id != tenant_id:
            raise invalid
        if user.is_platform_admin:
            perms: frozenset[str] = frozenset({PlatformP.TENANTS_MANAGE.value})
        else:
            tenant = db.get(Tenant, tenant_id)
            if tenant is None or tenant.status != "active":
                raise Forbidden(
                    "This organisation's account is suspended.", code="tenant_suspended"
                )
            perms = effective_user_permissions(
                _granted_permissions(db, user.id), is_service=user.kind == "service"
            )
        needs_mfa = mfa_required(db, user) and not user.mfa_enabled
    return Principal(
        kind="user",
        tenant_id=tenant_id,
        permissions=perms,
        user_id=user.id,
        session_id=session_id,
        is_platform_admin=user.is_platform_admin,
        is_service=user.kind == "service",
        mfa_enrollment_required=needs_mfa,
        email=user.email,
        meta=meta,
    )


def principal_from_api_key(db: Session, raw: str, meta: RequestMeta) -> Principal:
    invalid = Unauthorized("Invalid API key.", code="invalid_api_key")
    parsed = security.parse_api_key(raw)
    if not parsed:
        raise invalid
    prefix, secret = parsed
    with system_scope(db):
        key = db.scalar(select(ApiKey).where(ApiKey.prefix == prefix))
    if key is None or not security.constant_eq(
        security.hash_api_key_secret(secret), key.secret_hash
    ):
        raise invalid
    now = security.utcnow()
    if key.revoked_at is not None or (key.expires_at is not None and key.expires_at <= now):
        raise invalid
    set_tenant_context(db, key.tenant_id)
    tenant = db.get(Tenant, key.tenant_id)
    if tenant is None or tenant.status != "active":
        raise Forbidden("This organisation's account is suspended.", code="tenant_suspended")
    if key.last_used_at is None or now - key.last_used_at > timedelta(minutes=5):
        key.last_used_at = now
    return Principal(
        kind="api_key",
        tenant_id=key.tenant_id,
        api_key_id=key.id,
        permissions=effective_api_key_permissions(set(key.scopes)),
        meta=meta,
    )


# --- API keys -----------------------------------------------------------------------------


def _validate_scopes(principal: Principal, scopes: list[str]) -> list[str]:
    bad = set(scopes) - API_KEY_ALLOWED
    if bad:
        raise AppError(
            f"Scopes not allowed for API keys: {', '.join(sorted(bad))}",
            code="invalid_scope",
            status_code=422,
        )
    beyond = set(scopes) - principal.permissions
    if beyond:
        raise Forbidden(f"You cannot grant scopes you do not hold: {', '.join(sorted(beyond))}")
    return sorted(set(scopes))


def create_api_key(
    db: Session,
    principal: Principal,
    *,
    name: str,
    scopes: list[str],
    expires_in_days: int | None,
    rotated_from: uuid.UUID | None = None,
) -> tuple[ApiKey, str]:
    assert principal.tenant_id
    scopes = _validate_scopes(principal, scopes)
    gen = security.generate_api_key()
    key = ApiKey(
        tenant_id=principal.tenant_id,
        name=name.strip(),
        prefix=gen.prefix,
        secret_hash=gen.secret_hash,
        scopes=scopes,
        created_by=principal.user_id,
        rotated_from_id=rotated_from,
        expires_at=(security.utcnow() + timedelta(days=expires_in_days))
        if expires_in_days
        else None,
    )
    db.add(key)
    db.flush()
    audit.record(
        db,
        principal=principal,
        action="api_key.created",
        tenant_id=principal.tenant_id,
        target_type="api_key",
        target_id=key.id,
        details={"scopes": scopes, "rotated_from": str(rotated_from or "")},
    )
    return key, gen.plaintext


def _get_key(db: Session, principal: Principal, key_id: uuid.UUID) -> ApiKey:
    key = db.scalar(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.tenant_id == principal.tenant_id)
    )
    if key is None:
        raise NotFound("API key not found.")
    return key


def revoke_api_key(db: Session, principal: Principal, key_id: uuid.UUID) -> ApiKey:
    key = _get_key(db, principal, key_id)
    if key.revoked_at is None:
        key.revoked_at = security.utcnow()
        audit.record(
            db,
            principal=principal,
            action="api_key.revoked",
            tenant_id=principal.tenant_id,
            target_type="api_key",
            target_id=key.id,
        )
    return key


def rotate_api_key(db: Session, principal: Principal, key_id: uuid.UUID) -> tuple[ApiKey, str]:
    old = _get_key(db, principal, key_id)
    if old.revoked_at is not None:
        raise Conflict("Cannot rotate a revoked key.")
    days = None
    if old.expires_at:
        days = max(1, (old.expires_at - old.created_at).days)
    old.revoked_at = security.utcnow()
    audit.record(
        db,
        principal=principal,
        action="api_key.rotated",
        tenant_id=principal.tenant_id,
        target_type="api_key",
        target_id=old.id,
    )
    return create_api_key(
        db,
        principal,
        name=old.name,
        scopes=list(old.scopes),
        expires_in_days=days,
        rotated_from=old.id,
    )


def list_api_keys(db: Session, principal: Principal) -> list[ApiKey]:
    return list(
        db.scalars(
            select(ApiKey)
            .where(ApiKey.tenant_id == principal.tenant_id)
            .order_by(ApiKey.created_at.desc())
        )
    )
