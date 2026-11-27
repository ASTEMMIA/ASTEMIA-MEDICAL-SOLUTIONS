"""Runtime settings. Secrets come from the environment, never from source control."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ASTEMIA_", env_file=".env", extra="ignore")

    environment: str = "development"
    # mysql+mysqlconnector://user:password@host:3306/astemia
    database_url: SecretStr = SecretStr(
        "mysql+mysqlconnector://astemia:astemia@127.0.0.1:3306/astemia"
    )
    db_pool_size: int = 10
    db_pool_recycle_s: int = 1800

    # Token verification (API-01). Production uses the identity provider's
    # asymmetric keys; HS256 with a shared secret is for development only.
    jwt_algorithm: str = "HS256"
    jwt_key: SecretStr = SecretStr("dev-only-change-me-dev-only-change-me")
    jwt_issuer: str = "https://identity.astemia.local"
    jwt_audience: str = "astemia-api"

    policy_version: str = "policy-2026.11-pilot"
    idempotency_retention_hours: int = Field(default=72, ge=1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
