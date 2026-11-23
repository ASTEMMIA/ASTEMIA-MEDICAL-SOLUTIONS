"""Engine and session factory. One transaction per command (CEDA 10.2)."""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from astemia.config import get_settings


def build_engine(url: str, *, pool_size: int = 10, pool_recycle: int = 1800) -> Engine:
    engine = create_engine(
        url,
        pool_size=pool_size,
        pool_recycle=pool_recycle,
        pool_pre_ping=True,
        isolation_level="READ COMMITTED",
    )

    @event.listens_for(engine, "connect")
    def _session_settings(dbapi_conn, _record):  # type: ignore[no-untyped-def]
        cur = dbapi_conn.cursor()
        # Strict mode and UTC per connection, whatever the server defaults are.
        cur.execute(
            "SET SESSION sql_mode = 'STRICT_ALL_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,"
            "ERROR_FOR_DIVISION_BY_ZERO,ONLY_FULL_GROUP_BY,NO_ENGINE_SUBSTITUTION'"
        )
        cur.execute("SET SESSION time_zone = '+00:00'")
        cur.close()

    return engine


@lru_cache
def default_engine() -> Engine:
    s = get_settings()
    return build_engine(
        s.database_url.get_secret_value(),
        pool_size=s.db_pool_size,
        pool_recycle=s.db_pool_recycle_s,
    )


@lru_cache
def default_session_factory() -> sessionmaker[Session]:
    return sessionmaker(default_engine(), expire_on_commit=False)


@contextmanager
def transaction(factory: sessionmaker[Session]) -> Iterator[Session]:
    with factory() as session, session.begin():
        yield session
