"""Registry-level tests for quota accounting and eviction policy (FR-063/FR-066/FR-068)."""

from __future__ import annotations

import unittest

from asset_store_core.errors import InvalidStateTransitionError, QuotaExceededError
from asset_store_core.models import AssetState, EvictionPolicy
from asset_store_core.registry import InMemoryAssetRegistry


class QuotaAccountingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = InMemoryAssetRegistry()

    def _commit(self, *, partition: str, alias: str, size: int, space: str = "cache") -> str:
        asset = self.registry.reserve_asset(
            space=space,
            partition_id=partition,
            aliases={alias: False},
            owner_service_id="bulk-loader",
        )
        self.registry.commit_asset(
            asset_id=asset.asset_id,
            size_bytes=size,
            checksum="sha256:abc",
            caller_service_id="bulk-loader",
        )
        return asset.asset_id

    def test_default_partition_sweep_flag_depends_on_space(self) -> None:
        cache = self.registry.get_partition_quota(space="cache", partition_id="p1")
        users = self.registry.get_partition_quota(space="users", partition_id="u1")
        self.assertTrue(cache.eviction_sweep_enabled)
        self.assertFalse(users.eviction_sweep_enabled)
        self.assertEqual(0, cache.used_bytes)

    def test_commit_increments_partition_and_bucket(self) -> None:
        self._commit(partition="gallica", alias="a.png", size=30)
        self._commit(partition="gallica", alias="b.png", size=12)

        partition = self.registry.get_partition_quota(space="cache", partition_id="gallica")
        bucket = self.registry.get_bucket_quota(space="cache")
        self.assertEqual(42, partition.used_bytes)
        self.assertEqual(2, partition.used_asset_count)
        self.assertEqual(42, bucket.used_bytes)

    def test_expire_releases_usage(self) -> None:
        asset_id = self._commit(partition="gallica", alias="a.png", size=30)
        self.registry.expire_asset(asset_id=asset_id, caller_service_id="admin")

        partition = self.registry.get_partition_quota(space="cache", partition_id="gallica")
        bucket = self.registry.get_bucket_quota(space="cache")
        self.assertEqual(0, partition.used_bytes)
        self.assertEqual(0, partition.used_asset_count)
        self.assertEqual(0, bucket.used_bytes)

    def test_delete_from_expired_does_not_double_release(self) -> None:
        asset_id = self._commit(partition="gallica", alias="a.png", size=30)
        self.registry.expire_asset(asset_id=asset_id, caller_service_id="admin")
        self.registry.delete_asset(asset_id=asset_id, caller_service_id="admin")

        partition = self.registry.get_partition_quota(space="cache", partition_id="gallica")
        self.assertEqual(0, partition.used_bytes)
        self.assertEqual(0, partition.used_asset_count)

    def test_partition_byte_ceiling_rejects_at_105_percent(self) -> None:
        self.registry.set_partition_quota(space="cache", partition_id="gallica", quota_bytes=100)
        # 100 bytes is below the 105% ceiling and is accepted.
        self._commit(partition="gallica", alias="a.png", size=100)

        with self.assertRaises(QuotaExceededError) as ctx:
            self._commit(partition="gallica", alias="b.png", size=10)
        self.assertEqual("partition", ctx.exception.scope)

    def test_partition_asset_count_ceiling(self) -> None:
        self.registry.set_partition_quota(
            space="cache", partition_id="gallica", quota_asset_count=1
        )
        self._commit(partition="gallica", alias="a.png", size=1)

        with self.assertRaises(QuotaExceededError) as ctx:
            self._commit(partition="gallica", alias="b.png", size=1)
        self.assertEqual("partition", ctx.exception.scope)

    def test_bucket_ceiling_rejects_at_hard_ceiling(self) -> None:
        self.registry.set_bucket_quota(space="cache", quota_bytes=100)

        with self.assertRaises(QuotaExceededError) as ctx:
            self._commit(partition="gallica", alias="a.png", size=100)
        self.assertEqual("bucket", ctx.exception.scope)

    def test_partition_checked_before_bucket(self) -> None:
        self.registry.set_partition_quota(space="cache", partition_id="gallica", quota_bytes=50)
        self.registry.set_bucket_quota(space="cache", quota_bytes=100)

        with self.assertRaises(QuotaExceededError) as ctx:
            self._commit(partition="gallica", alias="a.png", size=60)
        self.assertEqual("partition", ctx.exception.scope)

    def test_set_partition_quota_preserves_usage(self) -> None:
        self._commit(partition="gallica", alias="a.png", size=30)
        updated = self.registry.set_partition_quota(
            space="cache", partition_id="gallica", quota_bytes=1000
        )
        self.assertEqual(30, updated.used_bytes)
        self.assertEqual(1, updated.used_asset_count)

    def test_set_eviction_policy_audits_change(self) -> None:
        asset = self.registry.reserve_asset(
            space="cache",
            partition_id="gallica",
            aliases={"a.png": False},
            owner_service_id="bulk-loader",
            eviction_policy=EvictionPolicy.EXEMPT,
        )
        self.assertIs(EvictionPolicy.EXEMPT, asset.eviction_policy)

        updated = self.registry.set_eviction_policy(
            asset_id=asset.asset_id,
            eviction_policy=EvictionPolicy.INHERIT,
            caller_service_id="admin",
        )
        self.assertIs(EvictionPolicy.INHERIT, updated.eviction_policy)
        actions = [event.action for event in self.registry.audit_events]
        self.assertIn("asset.eviction_policy_set", actions)

    def test_set_eviction_policy_on_deleted_is_rejected(self) -> None:
        asset_id = self._commit(partition="gallica", alias="a.png", size=1)
        self.registry.delete_asset(asset_id=asset_id, caller_service_id="admin")

        with self.assertRaises(InvalidStateTransitionError):
            self.registry.set_eviction_policy(
                asset_id=asset_id,
                eviction_policy=EvictionPolicy.EXEMPT,
                caller_service_id="admin",
            )

    def test_exempt_asset_still_tracked_in_usage(self) -> None:
        asset = self.registry.reserve_asset(
            space="cache",
            partition_id="gallica",
            aliases={"a.png": False},
            owner_service_id="bulk-loader",
            eviction_policy=EvictionPolicy.EXEMPT,
        )
        self.registry.commit_asset(
            asset_id=asset.asset_id,
            size_bytes=10,
            checksum="sha256:abc",
            caller_service_id="bulk-loader",
        )
        committed = self.registry.get_partition_quota(space="cache", partition_id="gallica")
        self.assertEqual(10, committed.used_bytes)
        self.assertEqual(AssetState.AVAILABLE, self.registry.resolve_alias(
            space="cache", alias="gallica/a.png"
        ).state)


if __name__ == "__main__":
    unittest.main()
