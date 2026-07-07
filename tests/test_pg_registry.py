"""Postgres registry certification tests (B-009, full AssetRegistry parity).

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
from datetime import timedelta

from asset_store_core.errors import (
    AliasConflictError,
    AliasImmutableError,
    AliasNotFoundError,
    ChecksumMismatchError,
    InvalidStateTransitionError,
    QuotaExceededError,
)
from asset_store_core.models import AssetState, EvictionPolicy
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
                "TRUNCATE assets, aliases, audit_events, alias_tombstones, "
                "partition_quotas, bucket_quotas RESTART IDENTITY CASCADE"
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
        actions = [event.action for event in self.registry.audit_events]
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
        actions = [event.action for event in self.registry.audit_events]
        self.assertEqual(["alias.create", "asset.commit"], actions)

    def test_record_capability_issue_persists_outcome(self) -> None:
        self.registry.record_capability_issue(
            caller_service_id="upload-api",
            operation="write",
            scope_prefix="users/42/uploads",
            ttl_seconds=300,
            outcome="granted",
            capability_id="cap-abc",
        )
        self.registry.record_capability_issue(
            caller_service_id="worker",
            operation="write",
            scope_prefix="users/42/uploads",
            ttl_seconds=300,
            outcome="denied",
        )
        events = [e for e in self.registry.audit_events if e.action == "capability.issue"]
        by_outcome = {e.outcome: e for e in events}
        self.assertEqual({"granted", "denied"}, set(by_outcome))
        granted = by_outcome["granted"]
        self.assertEqual("upload-api", granted.caller_service_id)
        self.assertEqual("users/42/uploads", granted.target)
        self.assertEqual("write", granted.after["operation"])
        self.assertEqual("300", granted.after["ttl_seconds"])
        self.assertEqual("cap-abc", granted.after["capability_id"])
        self.assertNotIn("capability_id", by_outcome["denied"].after)

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


@unittest.skipUnless(_pg_available(), _SKIP_REASON)
class PostgresRegistryLifecycleTest(unittest.TestCase):
    """Durable parity for the lifecycle, alias, and quota surface (B-009)."""

    def setUp(self) -> None:
        assert _DSN is not None
        self.registry = PostgresAssetRegistry.connect(_DSN)
        with self.registry._conn.transaction():
            self.registry._conn.execute(
                "TRUNCATE assets, aliases, audit_events, alias_tombstones, "
                "partition_quotas, bucket_quotas RESTART IDENTITY CASCADE"
            )

    def tearDown(self) -> None:
        self.registry.close()

    def _commit(self, alias: str, *, mutable: bool = False, size: int = 10) -> str:
        asset = self.registry.reserve_asset(
            space="cache",
            partition_id="gallica",
            aliases={alias: mutable},
            owner_service_id="bulk-loader",
        )
        self.registry.commit_asset(
            asset_id=asset.asset_id,
            size_bytes=size,
            checksum="sha256:abc",
            caller_service_id="bulk-loader",
        )
        return asset.asset_id

    def test_annotations_merge_and_overwrite(self) -> None:
        asset_id = self._commit("a.png")
        merged = self.registry.update_annotations(
            asset_id=asset_id, patch={"k": "v"}, caller_service_id="admin"
        )
        self.assertEqual("v", merged.annotations["k"])
        replaced = self.registry.update_annotations(
            asset_id=asset_id, patch={"only": "1"}, caller_service_id="admin", overwrite=True
        )
        self.assertEqual({"only": "1"}, dict(replaced.annotations))

    def test_expire_then_delete_and_quota_release(self) -> None:
        asset_id = self._commit("b.png", size=100)
        self.assertEqual(
            100, self.registry.get_partition_quota(space="cache", partition_id="gallica").used_bytes
        )
        self.registry.expire_asset(asset_id=asset_id, caller_service_id="admin")
        self.assertEqual(
            0, self.registry.get_partition_quota(space="cache", partition_id="gallica").used_bytes
        )
        deleted = self.registry.delete_asset(asset_id=asset_id, caller_service_id="admin")
        self.assertEqual(AssetState.DELETED, deleted.state)
        with self.assertRaises(InvalidStateTransitionError):
            self.registry.expire_asset(asset_id=asset_id, caller_service_id="admin")

    def test_immutable_detach_blocks_name_reuse_within_grace(self) -> None:
        self._commit("c.png")
        self.registry.detach_alias(space="cache", alias="gallica/c.png", caller_service_id="admin")
        with self.assertRaises(AliasConflictError):
            self.registry.reserve_asset(
                space="cache",
                partition_id="gallica",
                aliases={"c.png": False},
                owner_service_id="bulk-loader",
            )

    def test_detach_immutable_marks_orphan_for_gc(self) -> None:
        asset_id = self._commit("d.png")
        self.registry.detach_alias(space="cache", alias="gallica/d.png", caller_service_id="admin")
        actions = [e.action for e in self.registry.audit_events]
        self.assertIn("asset.gc_mark", actions)
        with self.assertRaises(AliasNotFoundError):
            self.registry.resolve_alias(space="cache", alias="gallica/d.png")
        _ = asset_id

    def test_mutable_detach_and_rebind(self) -> None:
        first = self._commit("live.png", mutable=True)
        second = self._commit("other.png")
        # rebind target must share partition; reserve a fresh available asset alias.
        self.registry.detach_mutable_alias(
            space="cache", alias="gallica/live.png", caller_service_id="admin"
        )
        with self.assertRaises(InvalidStateTransitionError):
            self.registry.resolve_alias(space="cache", alias="gallica/live.png")
        binding = self.registry.rebind_alias(
            space="cache",
            alias="gallica/live.png",
            new_asset_id=second,
            caller_service_id="admin",
        )
        self.assertEqual(second, binding.asset_id)
        resolved = self.registry.resolve_alias(space="cache", alias="gallica/live.png")
        self.assertEqual(second, resolved.asset_id)
        rebind = [e for e in self.registry.audit_events if e.action == "alias.rebind"][0]
        self.assertEqual(first, rebind.before["asset_id"])
        self.assertEqual(second, rebind.after["asset_id"])

    def test_wrong_detach_helper_rejected(self) -> None:
        self._commit("imm.png")
        with self.assertRaises(AliasImmutableError):
            self.registry.detach_mutable_alias(
                space="cache", alias="gallica/imm.png", caller_service_id="admin"
            )

    def test_partition_byte_quota_ceiling(self) -> None:
        self.registry.set_partition_quota(space="cache", partition_id="gallica", quota_bytes=100)
        asset = self.registry.reserve_asset(
            space="cache",
            partition_id="gallica",
            aliases={"big.bin": False},
            owner_service_id="bulk-loader",
        )
        with self.assertRaises(QuotaExceededError):
            self.registry.commit_asset(
                asset_id=asset.asset_id,
                size_bytes=200,
                checksum="sha256:abc",
                caller_service_id="bulk-loader",
            )

    def test_set_quota_preserves_usage(self) -> None:
        self._commit("used.bin", size=50)
        updated = self.registry.set_partition_quota(
            space="cache", partition_id="gallica", quota_bytes=1000
        )
        self.assertEqual(50, updated.used_bytes)
        self.assertEqual(1000, updated.quota_bytes)

    def test_eviction_policy_set(self) -> None:
        asset_id = self._commit("pol.png")
        updated = self.registry.set_eviction_policy(
            asset_id=asset_id,
            eviction_policy=EvictionPolicy.EXEMPT,
            caller_service_id="admin",
        )
        self.assertEqual(EvictionPolicy.EXEMPT, updated.eviction_policy)

    def test_tombstone_grace_zero_allows_immediate_reuse(self) -> None:
        assert _DSN is not None
        reg = PostgresAssetRegistry.connect(
            _DSN, bootstrap_schema=False, alias_name_grace_period=timedelta(0)
        )
        try:
            asset = reg.reserve_asset(
                space="cache",
                partition_id="gallica",
                aliases={"reuse.png": False},
                owner_service_id="bulk-loader",
            )
            reg.commit_asset(
                asset_id=asset.asset_id,
                size_bytes=1,
                checksum="sha256:abc",
                caller_service_id="bulk-loader",
            )
            reg.detach_alias(space="cache", alias="gallica/reuse.png", caller_service_id="admin")
            reg.reserve_asset(
                space="cache",
                partition_id="gallica",
                aliases={"reuse.png": False},
                owner_service_id="bulk-loader",
            )
        finally:
            reg.close()


if __name__ == "__main__":
    unittest.main()
