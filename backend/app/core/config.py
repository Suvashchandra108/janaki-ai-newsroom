"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_DEFAULT = "dev-only-change-me-dev-only-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "test", "staging", "production"] = "development"
    app_name: str = "Janaki AI Newsroom"

    # Runtime connection uses the non-owner, RLS-enforced role.
    database_url: str = "postgresql+psycopg://janaki_app:app_dev_pw@localhost:5432/janaki"
    # Migrations use the schema owner role.
    database_owner_url: str = "postgresql+psycopg://janaki_owner:owner_dev_pw@localhost:5432/janaki"
    db_app_role: str = "janaki_app"

    jwt_secret: str = _DEV_DEFAULT
    jwt_issuer: str = "janaki-newsroom"
    jwt_audience: str = "janaki-newsroom-api"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 14

    api_key_pepper: str = _DEV_DEFAULT
    # Fernet key (urlsafe base64, 32 bytes). Generate: python -c "from cryptography.fernet
    # import Fernet; print(Fernet.generate_key().decode())"
    mfa_encryption_key: str = "pZxQ0mJ6m7oV2s1Gm1y8k3hJ9nB4cR5tW6uY7iO8pAs="
    mfa_required_for_admins: bool = True
    mfa_issuer: str = "Janaki AI Newsroom"

    login_max_failures: int = 5
    login_lockout_minutes: int = 15
    password_min_length: int = 12

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    @model_validator(mode="after")
    def _refuse_weak_secrets_outside_dev(self) -> Settings:
        if self.environment in {"staging", "production"}:
            weak = [
                name
                for name in ("jwt_secret", "api_key_pepper")
                if getattr(self, name) == _DEV_DEFAULT or len(getattr(self, name)) < 32
            ]
            if self.mfa_encryption_key == Settings.model_fields["mfa_encryption_key"].default:
                weak.append("mfa_encryption_key")
            if weak:
                raise ValueError(f"Insecure secrets for {self.environment}: {', '.join(weak)}")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
