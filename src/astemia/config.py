"""Runtime settings. Secrets come from the environment, never from source control."""

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_KEY = "dev-only-change-me-dev-only-change-me"
# Where development conveniences (the shared default key, development sign-in)
# are allowed. Anywhere else the service refuses to start without real secrets.
DEVELOPMENT = frozenset({"development", "test"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ASTEMIA_", env_file=".env", extra="ignore")

    # A fixed list, so a misspelt name ("prod") fails at startup instead of
    # silently counting as a development environment.
    environment: Literal["development", "test", "staging", "production"] = "development"
    # mysql+mysqlconnector://user:password@host:3306/astemia
    database_url: SecretStr = SecretStr(
        "mysql+mysqlconnector://astemia:astemia@127.0.0.1:3306/astemia"
    )
    db_pool_size: int = 10
    db_pool_recycle_s: int = 1800

    # Token verification (API-01). Production uses the identity provider's
    # asymmetric keys; HS256 with a shared secret is for development only.
    jwt_algorithm: str = "HS256"
    jwt_key: SecretStr = SecretStr(DEV_JWT_KEY)
    jwt_issuer: str = "https://identity.astemia.local"
    jwt_audience: str = "astemia-api"

    # PACS viewer (HS07, WF05): the viewer's address, and the key that signs
    # the short-lived, patient-bound tokens the viewer opens a study with.
    pacs_viewer_url: str = "https://pacs.astemia.local/viewer"
    pacs_token_key: SecretStr = SecretStr(DEV_JWT_KEY)
    pacs_token_seconds: int = Field(default=300, ge=30, le=3600)

    policy_version: str = "policy-2026.11-pilot"
    # The staff web app: served at /app/ from this directory (the built web/dist).
    web_dir: str | None = None
    # Development sign-in for the web app: pick a seeded account and get a token.
    # Off unless set, and only in development and test.
    dev_sign_in: bool = False
    idempotency_retention_hours: int = Field(default=72, ge=1)

    @property
    def is_development(self) -> bool:
        return self.environment in DEVELOPMENT

    @model_validator(mode="after")
    def _real_secrets_outside_development(self) -> Self:
        """Staging and production never start with the shared development key,
        a short key, or development sign-in (security review, 28 November 2026)."""
        if self.is_development:
            return self
        key = self.jwt_key.get_secret_value()
        if key == DEV_JWT_KEY or len(key) < 32:
            raise ValueError(
                f"ASTEMIA_JWT_KEY must be set to a secret of at least 32 characters "
                f"in {self.environment}"
            )
        pacs = self.pacs_token_key.get_secret_value()
        if pacs == DEV_JWT_KEY or len(pacs) < 32:
            raise ValueError(
                f"ASTEMIA_PACS_TOKEN_KEY must be set to a secret of at least 32 characters "
                f"in {self.environment}"
            )
        if self.dev_sign_in:
            raise ValueError(f"development sign-in cannot be enabled in {self.environment}")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
