"""Cryptographic primitives: passwords, tokens, API keys, TOTP."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet

from app.core.config import get_settings

_hasher = PasswordHasher()  # Argon2id with library defaults (RFC 9106 low-memory profile)
# Used to keep login timing similar whether or not the account exists.
_DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-real-password")


def utcnow() -> datetime:
    return datetime.now(UTC)


# --- passwords ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


# --- access tokens -----------------------------------------------------------------------


def create_access_token(
    *, user_id: uuid.UUID, session_id: uuid.UUID, tenant_id: uuid.UUID | None
) -> tuple[str, int]:
    s = get_settings()
    ttl = s.access_token_ttl_minutes * 60
    now = utcnow()
    payload = {
        "sub": str(user_id),
        "sid": str(session_id),
        "tid": str(tenant_id) if tenant_id else None,
        "typ": "access",
        "iss": s.jwt_issuer,
        "aud": s.jwt_audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256"), ttl


def decode_access_token(token: str) -> dict[str, Any]:
    s = get_settings()
    claims: dict[str, Any] = jwt.decode(
        token,
        s.jwt_secret,
        algorithms=["HS256"],
        audience=s.jwt_audience,
        issuer=s.jwt_issuer,
        options={"require": ["exp", "sub", "sid", "typ"]},
    )
    if claims.get("typ") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    return claims


# --- refresh tokens ----------------------------------------------------------------------


def new_refresh_secret() -> tuple[str, str]:
    """Return (secret, sha256 hex). Only the hash is stored."""
    secret = secrets.token_urlsafe(32)
    return secret, sha256_hex(secret)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def constant_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


# --- API keys ----------------------------------------------------------------------------

API_KEY_PREFIX = "jnk"


@dataclass(frozen=True)
class GeneratedApiKey:
    plaintext: str
    prefix: str
    secret_hash: str


def hash_api_key_secret(secret: str) -> str:
    pepper = get_settings().api_key_pepper.encode()
    return hmac.new(pepper, secret.encode(), hashlib.sha256).hexdigest()


def generate_api_key() -> GeneratedApiKey:
    prefix = secrets.token_hex(6)
    secret = secrets.token_urlsafe(32)
    return GeneratedApiKey(
        plaintext=f"{API_KEY_PREFIX}_{prefix}_{secret}",
        prefix=prefix,
        secret_hash=hash_api_key_secret(secret),
    )


def parse_api_key(value: str) -> tuple[str, str] | None:
    parts = value.split("_", 2)
    if len(parts) != 3 or parts[0] != API_KEY_PREFIX or not parts[1] or not parts[2]:
        return None
    return parts[1], parts[2]


# --- TOTP --------------------------------------------------------------------------------


def _fernet() -> Fernet:
    return Fernet(get_settings().mfa_encryption_key.encode())


def new_totp_secret() -> str:
    return pyotp.random_base32()


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def totp_uri(secret: str, account: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=get_settings().mfa_issuer)


def verify_totp(secret: str, code: str, *, last_counter: int | None) -> int | None:
    """Verify a TOTP code with ±1 step drift. Returns the matched counter, or None.

    Codes at or before ``last_counter`` are rejected to prevent replay.
    """
    if not code.isdigit() or len(code) != 6:
        return None
    totp = pyotp.TOTP(secret)
    now_counter = int(utcnow().timestamp()) // totp.interval
    for counter in (now_counter - 1, now_counter, now_counter + 1):
        if last_counter is not None and counter <= last_counter:
            continue
        if hmac.compare_digest(totp.generate_otp(counter), code):
            return counter
    return None
