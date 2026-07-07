"""Alembic migration environment for the asset-store registry schema (B-009).

The database URL comes from the ``ASSET_STORE_PG_DSN`` environment variable so
migrations share the exact DSN used by the application and the test suite. No URL
is stored in ``alembic.ini``.
"""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config


def _database_url() -> str:
    dsn = os.environ.get("ASSET_STORE_PG_DSN")
    if not dsn:
        raise RuntimeError(
            "ASSET_STORE_PG_DSN must be set to run asset-store migrations, e.g. "
            "ASSET_STORE_PG_DSN=postgresql://asset:asset@localhost:5432/asset_store"
        )
    # SQLAlchemy defaults the bare ``postgresql://`` scheme to the psycopg2 driver.
    # The project standardises on psycopg v3 (the ``pg`` extra), so pin the driver
    # explicitly while leaving an already-qualified scheme untouched.
    if dsn.startswith("postgresql://"):
        dsn = "postgresql+psycopg://" + dsn[len("postgresql://") :]
    return dsn


# The registry manages its own tables via hand-written SQL migrations; there is no
# SQLAlchemy model metadata to autogenerate against, so target_metadata stays None.
target_metadata = None


def run_migrations_offline() -> None:
    """Emit SQL for the configured DSN without a live connection."""

    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""

    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
