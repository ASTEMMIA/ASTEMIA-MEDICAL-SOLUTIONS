import os
import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.session import build_engine
from astemia.adapters.identity.tokens import issue_dev_token
from astemia.api.app import create_app
from astemia.config import Settings
from tests.fixtures.synthetic import SyntheticTenant, make_tenant

TEST_URL = os.environ.get(
    "ASTEMIA_TEST_DATABASE_URL",
    "mysql+mysqlconnector://astemia:astemia@127.0.0.1:3306/astemia_test",
)


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(environment="test", database_url=SecretStr(TEST_URL))


@pytest.fixture(scope="session")
def factory(settings: Settings) -> Iterator[sessionmaker[Session]]:
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.attributes["url"] = TEST_URL
    command.upgrade(cfg, "head")  # also proves the migrations apply cleanly
    engine = build_engine(TEST_URL, pool_size=5)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def tenant(factory: sessionmaker[Session]) -> SyntheticTenant:
    # A fresh tenant per test: isolation between tests is tenant isolation.
    return make_tenant(factory)


@pytest.fixture(scope="session")
def client(settings: Settings, factory: sessionmaker[Session]) -> TestClient:
    return TestClient(create_app(settings, factory), raise_server_exceptions=False)


class Api:
    def __init__(self, client: TestClient, settings: Settings, tenant: SyntheticTenant) -> None:
        self.client, self.settings, self.tenant = client, settings, tenant

    def headers(self, who: str, key: str | None = "auto", **extra: str) -> dict[str, str]:
        token = issue_dev_token(self.settings, self.tenant.subject(who), self.tenant.tenant_id)
        h = {"Authorization": f"Bearer {token}", **extra}
        if key == "auto":
            h["Idempotency-Key"] = uuid.uuid4().hex
        elif key is not None:
            h["Idempotency-Key"] = key
        return h

    def post(self, who: str, path: str, body: dict, key: str | None = "auto", **headers: str):  # type: ignore[no-untyped-def]
        return self.client.post(path, json=body, headers=self.headers(who, key, **headers))

    def get(self, who: str, path: str):  # type: ignore[no-untyped-def]
        return self.client.get(path, headers=self.headers(who, None))


@pytest.fixture
def api(client: TestClient, settings: Settings, tenant: SyntheticTenant) -> Api:
    return Api(client, settings, tenant)
