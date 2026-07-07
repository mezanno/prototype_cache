"""Alembic migration certification for the Postgres registry schema (B-009).

Proves that the versioned migration history in ``migrations/`` produces a schema
the durable registry works against *without* its dev-only ``bootstrap_schema``
DDL, and that the initial migration is reversible.

Skipped unless ``ASSET_STORE_PG_DSN`` points at a reachable Postgres (same gate
as ``tests/test_pg_registry.py``). Bring one up:

    cd deploy/compose
    docker compose -f docker-compose.postgres.yml up -d
    export ASSET_STORE_PG_DSN=postgresql://asset:asset@127.0.0.1:5432/asset_store
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

from asset_store_core.models import AssetState
from asset_store_core.pg_registry import PostgresAssetRegistry

if TYPE_CHECKING:
    from alembic.config import Config

_DSN = os.environ.get("ASSET_STORE_PG_DSN")
_REPO_ROOT = Path(__file__).resolve().parent.parent


def _pg_available() -> bool:
    if not _DSN:
        return False
    try:
        import psycopg

        with psycopg.connect(_DSN, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
    except Exception:
        return False
    return True


def _alembic_config() -> Config:
    from alembic.config import Config

    config = Config(str(_REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_REPO_ROOT / "migrations"))
    return config


def _reset_public_schema() -> None:
    import psycopg

    assert _DSN is not None
    with psycopg.connect(_DSN) as conn:
        conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
        conn.commit()


_SKIP_REASON = "Postgres not reachable; export ASSET_STORE_PG_DSN to run these tests"

_EXPECTED_TABLES = {
    "assets",
    "aliases",
    "alias_tombstones",
    "partition_quotas",
    "bucket_quotas",
    "audit_events",
}


@unittest.skipUnless(_pg_available(), _SKIP_REASON)
class MigrationTest(unittest.TestCase):
    def setUp(self) -> None:
        assert _DSN is not None
        _reset_public_schema()

    def tearDown(self) -> None:
        # Leave the schema in place so other Postgres tests (which rely on the
        # bootstrap DDL) find a clean, working database.
        _reset_public_schema()

    def _public_tables(self) -> set[str]:
        import psycopg

        assert _DSN is not None
        with psycopg.connect(_DSN) as conn:
            rows = conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            ).fetchall()
        return {row[0] for row in rows}

    def test_upgrade_head_creates_registry_schema(self) -> None:
        from alembic import command

        command.upgrade(_alembic_config(), "head")

        tables = self._public_tables()
        self.assertTrue(_EXPECTED_TABLES.issubset(tables))
        self.assertIn("alembic_version", tables)

    def test_migrated_schema_supports_registry_round_trip(self) -> None:
        from alembic import command

        command.upgrade(_alembic_config(), "head")

        # bootstrap_schema=False proves the migration alone provisions everything
        # the registry needs — no runtime DDL fallback.
        assert _DSN is not None
        registry = PostgresAssetRegistry.connect(_DSN, bootstrap_schema=False)
        try:
            asset = registry.reserve_asset(
                space="cache",
                partition_id="gallica",
                aliases={"migrated.png": False},
                owner_service_id="bulk-loader",
            )
            committed = registry.commit_asset(
                asset_id=asset.asset_id,
                size_bytes=3,
                checksum="sha256:" + "0" * 64,
                caller_service_id="bulk-loader",
            )
            self.assertEqual(committed.state, AssetState.AVAILABLE)
            resolved = registry.resolve_alias(space="cache", alias="gallica/migrated.png")
            self.assertEqual(resolved.asset_id, asset.asset_id)
            self.assertEqual([e.action for e in registry.audit_events][-1], "asset.commit")
        finally:
            registry.close()

    def test_downgrade_base_is_reversible(self) -> None:
        from alembic import command

        command.upgrade(_alembic_config(), "head")
        command.downgrade(_alembic_config(), "base")

        tables = self._public_tables()
        self.assertFalse(_EXPECTED_TABLES & tables)


if __name__ == "__main__":
    unittest.main()
