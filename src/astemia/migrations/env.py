"""Alembic environment. Migrations follow expand, backfill, verify, contract
(CEDA 11.3 step 4): never a destructive change in the same release as code
that still reads the old shape."""

from logging.config import fileConfig

from alembic import context

from astemia.adapters.db import models
from astemia.adapters.db.session import build_engine
from astemia.config import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = models.Base.metadata


def url() -> str:
    return config.attributes.get("url") or get_settings().database_url.get_secret_value()


def run_migrations_offline() -> None:
    context.configure(
        url=url(), target_metadata=target_metadata, literal_binds=True, compare_type=True
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = build_engine(url(), pool_size=1)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection, target_metadata=target_metadata, compare_type=True
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
