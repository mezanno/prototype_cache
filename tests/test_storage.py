"""Storage layout (ADR-007)."""

from __future__ import annotations

import unittest

from asset_store_core import (
    ObjectStoreLocation,
    ValidationError,
    build_storage_key,
    normalize_bucket,
    normalize_partition_id,
)


class StorageLayoutTest(unittest.TestCase):
    def test_normalize_bucket_accepts_mvp_buckets(self) -> None:
        for name in ("cache", "tmp", "users", "results"):
            self.assertEqual(name, normalize_bucket(name))

    def test_rejects_legacy_space_names(self) -> None:
        with self.assertRaises(ValidationError):
            normalize_bucket("u-42")

    def test_build_storage_key(self) -> None:
        self.assertEqual(
            "42/assets/asset-1",
            build_storage_key(partition_id="42", asset_id="asset-1"),
        )

    def test_object_store_location(self) -> None:
        loc = ObjectStoreLocation.for_asset(
            space="users",
            partition_id="42",
            asset_id="a1",
        )
        self.assertEqual("users", loc.bucket)
        self.assertEqual("42/assets/a1", loc.key)

    def test_normalize_partition_id_rejects_traversal(self) -> None:
        with self.assertRaises(ValidationError):
            normalize_partition_id("..")
