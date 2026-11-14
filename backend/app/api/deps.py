from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.errors import Forbidden, Unauthorized
from app.core.permissions import PlatformP
from app.core.principal import Principal, RequestMeta
from app.db.session import get_db
from app.modules.identity import service as identity


def request_meta(request: Request) -> RequestMeta:
    return RequestMeta(
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        request_id=getattr(request.state, "request_id", None),
    )


def get_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    meta = request_meta(request)
    auth = request.headers.get("authorization", "")
    api_key = request.headers.get("x-api-key")
    if auth.lower().startswith("bearer "):
        return identity.principal_from_access_token(db, auth[7:].strip(), meta)
    if api_key:
        return identity.principal_from_api_key(db, api_key.strip(), meta)
    raise Unauthorized("Authentication required.")


def get_user_principal(principal: Principal = Depends(get_principal)) -> Principal:
    """Any signed-in human/service user, even if MFA enrolment is still pending."""
    if principal.kind != "user":
        raise Forbidden("This endpoint requires a user session, not an API key.")
    return principal


def require(*permissions: str) -> Callable[..., Principal]:
    def checker(principal: Principal = Depends(get_principal)) -> Principal:
        if principal.mfa_enrollment_required:
            raise Forbidden(
                "Set up two-factor authentication to continue.", code="mfa_enrollment_required"
            )
        if principal.tenant_id is None:
            raise Forbidden("This endpoint is for organisation users.")
        missing = [p for p in permissions if p not in principal.permissions]
        if missing:
            raise Forbidden(
                "You do not have permission for this action.", details={"missing": missing}
            )
        return principal

    return checker


def require_platform_admin(principal: Principal = Depends(get_principal)) -> Principal:
    if not principal.is_platform_admin or PlatformP.TENANTS_MANAGE not in principal.permissions:
        raise Forbidden("Platform administrator access required.")
    if principal.mfa_enrollment_required:
        raise Forbidden(
            "Set up two-factor authentication to continue.", code="mfa_enrollment_required"
        )
    return principal
