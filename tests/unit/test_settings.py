"""Staging and production refuse to start with development secrets (security
review, 28 November 2026)."""

import pytest
from pydantic import SecretStr, ValidationError

from astemia.config import Settings

STRONG = SecretStr("s" * 32)


def test_development_and_test_keep_their_conveniences() -> None:
    for env in ("development", "test"):
        s = Settings(environment=env, dev_sign_in=True)
        assert s.is_development and s.dev_sign_in


@pytest.mark.parametrize("env", ["staging", "production"])
def test_real_secrets_outside_development(env: str) -> None:
    with pytest.raises(ValidationError, match="ASTEMIA_JWT_KEY"):
        Settings(environment=env)  # the shared development key
    with pytest.raises(ValidationError, match="ASTEMIA_JWT_KEY"):
        Settings(environment=env, jwt_key=SecretStr("short"))
    with pytest.raises(ValidationError, match="development sign-in"):
        Settings(environment=env, jwt_key=STRONG, dev_sign_in=True)
    ok = Settings(environment=env, jwt_key=STRONG)
    assert not ok.is_development


def test_an_unknown_environment_name_is_refused() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="prod")  # type: ignore[arg-type]
