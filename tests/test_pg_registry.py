"""Postgres registry certification tests (S-002, thin reserve/commit/resolve slice).

Skipped unless ``ASSET_STORE_PG_DSN`` points at a reachable Postgres. Bring one up:

    cd deploy/compose
    docker compose -f docker-compose.postgres.yml up -d
    export ASSET_STORE_PG_DSN=postgresql://asset:asset@127.0.0.1:5432/asset_store

Then run: ``uv run pytest tests/test_pg_registry.py -q``. Without the env var the
default ``uv run pytest`` run skips this module, staying Docker-free.
"""

from __future__ import annotations

import os
import unittest
import uuid

from asset_store_core.errors import (
    AliasConflictError,
    AliasNotFoundError,
    ChecksumMismatchError,
    InvalidStateTransitionError,
)
from asset_store_core.models import AssetState
from asset_store_core.pg_registry import PostgresAssetRegistry

_DSN = os.environ.get("ASSET_STORE_PG_DSN")


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


_SKIP_REASON = "Postgres not reachable; export ASSET_STORE_PG_DSN to run these tests"


@unittest.skipUnless(_pg_available(), _SKIP_REASON)
class PostgresRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        assert _DSN is not None
        self.registry = PostgresAssetRegistry.connect(_DSN)
        with self.registry._conn.transaction():
            self.registry._conn.execute(
                "TRUNCATE assets, aliases, audit_events RESTART IDENTITY CASCADE"
            )

    def tearDown(self) -> None:
        self.registry.close()

    def test_reserve_creates_pending_asset_with_aliases(self) -> None:
        asset = self.registry.reserve_asset(
            space="cache",
            partition_id="gallica",
            aliases={"img.png": False},
            owner_service_id="bulk-loader",
            annotations={"source": "test"},
        )
        self.assertEqual(AssetState.PENDING, asset.state)
        self.assertIn("cache/gallica/img.png", asset.aliases)
        self.assertEqual("test", asset.annotations["source"])
        actions = [event.action for event in self.registry.audit_events()]
        self.assertEqual(["alias.create"], actions)

    def test_commit_then_resolve_round_trip(self) -> None:
        asset = self.registry.reserve_asset(
            space="cache",
            partition_id="gallica",
            aliases={"img.png": False},
            owner_service_id="bulk-loader",
        )
        committed = self.registry.commit_asset(
            asset_id=asset.asset_id,
            size_bytes=11,
            checksum="sha256:abc",
            caller_service_id="bulk-loader",
        )
        self.assertEqual(AssetState.AVAILABLE, committed.state)
        self.assertEqual(11, committed.size_bytes)

        resolved = self.registry.resolve_alias(space="cache", alias="gallica/img.png")
        self.assertEqual(asset.asset_id, resolved.asset_id)
        self.assertEqual(AssetState.AVAILABLE, resolved.state)
        actions = [event.action for event in self.registry.audit_events()]
        self.assertEqual(["alias.create", "asset.commit"], actions)

    def test_resolve_pending_asset_is_rejected(self) -> None:
        self.registry.reserve_asset(
            space="cache",
            partition_id="gallica",
            aliases={"img.png": False},
            owner_service_id="bulk-loader",
        )
        with self.assertRaises(InvalidStateTransitionError):
            self.registry.resolve_alias(space="cache", alias="gallica/img.png")

    def test_duplicate_alias_reserve_conflicts(self) -> None:
        self.registry.reserve_asset(
            space="cache",
            partition_id="gallica",
            aliases={"img.png": False},
            owner_service_id="bulk-loader",
        )
        with self.assertRaises(AliasConflictError):
            self.registry.reserve_asset(
                space="cache",
                partition_id="gallica",
                aliases={"img.png": False},
                owner_service_id="bulk-loader",
            )

    def test_commit_with_mismatched_expected_checksum(self) -> None:
        asset = self.registry.reserve_asset(
            space="cache",
            partition_id="gallica",
            aliases={"img.png": False},
            owner_service_id="bulk-loader",
        )
        with self.assertRaises(ChecksumMismatchError):
            self.registry.commit_asset(
                asset_id=asset.asset_id,
                size_bytes=11,
                checksum="sha256:abc",
                caller_service_id="bulk-loader",
                expected_checksum="sha256:does-not-match",
            )

    def test_resolve_unknown_alias_raises(self) -> None:
        with self.assertRaises(AliasNotFoundError):
            self.registry.resolve_alias(space="cache", alias=f"gallica/{uuid.uuid4().hex}.png")

    def test_state_persists_across_connections(self) -> None:
        asset = self.registry.reserve_asset(
            space="cache",
            partition_id="gallica",
            aliases={"img.png": False},
            owner_service_id="bulk-loader",
        )
        self.registry.commit_asset(
            asset_id=asset.asset_id,
            size_bytes=11,
            checksum="sha256:abc",
            caller_service_id="bulk-loader",
        )
        assert _DSN is not None
        with PostgresAssetRegistry.connect(_DSN, bootstrap_schema=False) as other:
            resolved = other.resolve_alias(space="cache", alias="gallica/img.png")
        self.assertEqual(asset.asset_id, resolved.asset_id)
        self.assertEqual(AssetState.AVAILABLE, resolved.state)


if __name__ == "__main__":
    unittest.main()
