"""Object-store backend seam and reserve -> PUT -> commit -> resolve round trip."""

from __future__ import annotations

import unittest

from asset_store_core import (
    Asset,
    AssetState,
    ChecksumMismatchError,
    InMemoryAssetRegistry,
    InvalidStateTransitionError,
    LocalObjectStore,
    ObjectNotFoundError,
    ObjectStoreLocation,
    compute_checksum,
)


def _location_for(asset: Asset) -> ObjectStoreLocation:
    return ObjectStoreLocation.for_asset(
        space=asset.space,
        partition_id=asset.partition_id,
        asset_id=asset.asset_id,
    )


class LocalObjectStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = LocalObjectStore()
        self.location = ObjectStoreLocation(bucket="cache", key="m/assets/a1")

    def test_put_returns_server_checksum_and_size(self) -> None:
        stat = self.store.put_object(self.location, b"hello")
        self.assertEqual(5, stat.size_bytes)
        self.assertEqual(compute_checksum(b"hello"), stat.checksum)
        self.assertEqual("sha256", stat.checksum_algo)

    def test_get_returns_stored_bytes(self) -> None:
        self.store.put_object(self.location, b"payload")
        self.assertEqual(b"payload", self.store.get_object(self.location))

    def test_get_missing_raises(self) -> None:
        with self.assertRaises(ObjectNotFoundError):
            self.store.get_object(self.location)

    def test_stat_missing_returns_none(self) -> None:
        self.assertIsNone(self.store.stat_object(self.location))

    def test_delete_is_idempotent(self) -> None:
        self.store.put_object(self.location, b"x")
        self.store.delete_object(self.location)
        self.store.delete_object(self.location)
        self.assertIsNone(self.store.stat_object(self.location))


class RegistryStorageIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = InMemoryAssetRegistry()
        self.store = LocalObjectStore()

    def test_reserve_put_commit_resolve_round_trip(self) -> None:
        payload = b"\x89PNG fake image bytes"
        client_checksum = compute_checksum(payload)

        pending = self.registry.reserve_asset(
            space="cache",
            partition_id="gallica",
            aliases=["bnf/example.png"],
            owner_service_id="bulk-loader",
            mime="image/png",
        )
        self.assertEqual(AssetState.PENDING, pending.state)

        location = _location_for(pending)
        stat = self.store.put_object(location, payload)

        available = self.registry.commit_asset(
            asset_id=pending.asset_id,
            size_bytes=stat.size_bytes,
            checksum=stat.checksum,
            caller_service_id="bulk-loader",
            expected_checksum=client_checksum,
        )
        self.assertEqual(AssetState.AVAILABLE, available.state)
        self.assertEqual(len(payload), available.size_bytes)
        self.assertEqual(stat.checksum, available.checksum)

        resolved = self.registry.resolve_alias(space="cache", alias="gallica/bnf/example.png")
        self.assertEqual(available.asset_id, resolved.asset_id)
        self.assertEqual(payload, self.store.get_object(_location_for(resolved)))

    def test_checksum_mismatch_rolls_back_and_leaves_asset_pending(self) -> None:
        payload = b"server-stored-bytes"

        pending = self.registry.reserve_asset(
            space="cache",
            partition_id="m",
            aliases=["doc"],
            owner_service_id="svc",
        )
        location = _location_for(pending)
        stat = self.store.put_object(location, payload)

        with self.assertRaises(ChecksumMismatchError):
            self.registry.commit_asset(
                asset_id=pending.asset_id,
                size_bytes=stat.size_bytes,
                checksum=stat.checksum,
                caller_service_id="svc",
                expected_checksum="sha256:client-claimed-different",
            )

        # Asset must remain unresolvable (still pending) after a rejected commit.
        with self.assertRaises(InvalidStateTransitionError):
            self.registry.resolve_alias(space="cache", alias="m/doc")

        # A subsequent commit with the correct server checksum still succeeds.
        available = self.registry.commit_asset(
            asset_id=pending.asset_id,
            size_bytes=stat.size_bytes,
            checksum=stat.checksum,
            caller_service_id="svc",
            expected_checksum=stat.checksum,
        )
        self.assertEqual(AssetState.AVAILABLE, available.state)


if __name__ == "__main__":
    unittest.main()
