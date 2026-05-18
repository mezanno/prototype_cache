"""In-memory registry behaviour."""

from __future__ import annotations

import unittest
from datetime import timedelta

from asset_store_core import (
    AliasConflictError,
    AliasImmutableError,
    AssetState,
    ChecksumMismatchError,
    InMemoryAssetRegistry,
    InvalidStateTransitionError,
    ValidationError,
)


class InMemoryAssetRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = InMemoryAssetRegistry()

    def test_reserves_commits_and_resolves_asset(self) -> None:
        pending = self.registry.reserve_asset(
            space="cache",
            aliases=["bnf/ark-12148/example/full/full/0/default.jpg"],
            owner_service_id="bulk-loader",
            mime="image/jpeg",
        )

        self.assertEqual(AssetState.PENDING, pending.state)

        available = self.registry.commit_asset(
            asset_id=pending.asset_id,
            size_bytes=123,
            checksum="sha256:abc",
            caller_service_id="bulk-loader",
        )

        resolved = self.registry.resolve_alias(
            space="cache",
            alias="bnf/ark-12148/example/full/full/0/default.jpg",
        )
        self.assertEqual(available.asset_id, resolved.asset_id)
        self.assertEqual(AssetState.AVAILABLE, resolved.state)

    def test_alias_conflict_does_not_overwrite_existing_binding(self) -> None:
        first = self.registry.reserve_asset(
            space="cache",
            aliases=["same-name"],
            owner_service_id="bulk-loader",
        )

        with self.assertRaises(AliasConflictError):
            self.registry.reserve_asset(
                space="cache",
                aliases=["same-name"],
                owner_service_id="bulk-loader",
            )

        self.assertEqual(first.asset_id, self.registry.audit_events[0].after["asset_id"])

    def test_pending_and_expired_assets_do_not_resolve(self) -> None:
        pending = self.registry.reserve_asset(
            space="cache",
            aliases=["pending-image"],
            owner_service_id="bulk-loader",
        )
        with self.assertRaises(InvalidStateTransitionError):
            self.registry.resolve_alias(space="cache", alias="pending-image")

        committed = self.registry.commit_asset(
            asset_id=pending.asset_id,
            size_bytes=1,
            checksum="sha256:abc",
            caller_service_id="bulk-loader",
        )
        self.registry.expire_asset(asset_id=committed.asset_id, caller_service_id="admin")

        with self.assertRaises(InvalidStateTransitionError):
            self.registry.resolve_alias(space="cache", alias="pending-image")

    def test_immutable_alias_rebind_is_rejected_by_default(self) -> None:
        first = self.registry.reserve_asset(
            space="u-42",
            aliases=["uploads/file.jpg"],
            owner_service_id="upload-api",
        )
        first = self.registry.commit_asset(
            asset_id=first.asset_id,
            size_bytes=1,
            checksum="sha256:first",
            caller_service_id="upload-api",
        )
        second = self.registry.reserve_asset(
            space="u-42",
            aliases=["uploads/replacement.jpg"],
            owner_service_id="upload-api",
        )
        second = self.registry.commit_asset(
            asset_id=second.asset_id,
            size_bytes=1,
            checksum="sha256:second",
            caller_service_id="upload-api",
        )

        with self.assertRaises(AliasImmutableError):
            self.registry.rebind_alias(
                space="u-42",
                alias="uploads/file.jpg",
                new_asset_id=second.asset_id,
                caller_service_id="admin",
            )

        resolved = self.registry.resolve_alias(space="u-42", alias="uploads/file.jpg")
        self.assertEqual(first.asset_id, resolved.asset_id)

    def test_mutable_alias_detach_then_rebind(self) -> None:
        first = self.registry.reserve_asset(
            space="u-42",
            aliases={"mutable-pointer": True},
            owner_service_id="upload-api",
        )
        first = self.registry.commit_asset(
            asset_id=first.asset_id,
            size_bytes=1,
            checksum="sha256:first",
            caller_service_id="upload-api",
        )
        second = self.registry.reserve_asset(
            space="u-42",
            aliases=["immutable-target-name"],
            owner_service_id="upload-api",
        )
        second = self.registry.commit_asset(
            asset_id=second.asset_id,
            size_bytes=1,
            checksum="sha256:second",
            caller_service_id="upload-api",
        )

        self.registry.detach_mutable_alias(
            space="u-42",
            alias="mutable-pointer",
            caller_service_id="admin",
        )
        with self.assertRaises(InvalidStateTransitionError):
            self.registry.resolve_alias(space="u-42", alias="mutable-pointer")

        binding = self.registry.rebind_alias(
            space="u-42",
            alias="mutable-pointer",
            new_asset_id=second.asset_id,
            caller_service_id="admin",
        )

        self.assertEqual(second.asset_id, binding.asset_id)
        self.assertEqual(
            second.asset_id,
            self.registry.resolve_alias(space="u-42", alias="mutable-pointer").asset_id,
        )
        rebind_events = [
            event for event in self.registry.audit_events if event.action == "alias.rebind"
        ]
        self.assertEqual(1, len(rebind_events))
        self.assertEqual(second.asset_id, rebind_events[0].after["asset_id"])

    def test_rebind_requires_available_target(self) -> None:
        first = self.registry.reserve_asset(
            space="u-42",
            aliases={"ptr": True},
            owner_service_id="svc",
        )
        first = self.registry.commit_asset(
            asset_id=first.asset_id,
            size_bytes=1,
            checksum="sha256:a",
            caller_service_id="svc",
        )
        pending_target = self.registry.reserve_asset(
            space="u-42",
            aliases=["pending-target"],
            owner_service_id="svc",
        )
        self.registry.detach_mutable_alias(space="u-42", alias="ptr", caller_service_id="svc")

        with self.assertRaises(InvalidStateTransitionError):
            self.registry.rebind_alias(
                space="u-42",
                alias="ptr",
                new_asset_id=pending_target.asset_id,
                caller_service_id="svc",
            )

    def test_commit_validates_checksum_and_size(self) -> None:
        asset = self.registry.reserve_asset(
            space="cache",
            aliases=["x"],
            owner_service_id="svc",
        )
        with self.assertRaises(ValidationError):
            self.registry.commit_asset(
                asset_id=asset.asset_id,
                size_bytes=-1,
                checksum="sha256:x",
                caller_service_id="svc",
            )
        with self.assertRaises(ValidationError):
            self.registry.commit_asset(
                asset_id=asset.asset_id,
                size_bytes=1,
                checksum="   ",
                caller_service_id="svc",
            )
        with self.assertRaises(ChecksumMismatchError):
            self.registry.commit_asset(
                asset_id=asset.asset_id,
                size_bytes=1,
                checksum="sha256:server",
                caller_service_id="svc",
                expected_checksum="sha256:client",
            )

    def test_detach_immutable_sets_tombstone(self) -> None:
        reg = InMemoryAssetRegistry(alias_name_grace_period=timedelta(0))
        a = reg.reserve_asset(space="cache", aliases=["gone"], owner_service_id="svc")
        reg.commit_asset(
            asset_id=a.asset_id,
            size_bytes=1,
            checksum="sha256:x",
            caller_service_id="svc",
        )
        reg.detach_alias(space="cache", alias="gone", caller_service_id="svc")

        b = reg.reserve_asset(space="cache", aliases=["gone"], owner_service_id="svc")
        self.assertNotEqual(a.asset_id, b.asset_id)

    def test_detach_routes_mutable_vs_immutable(self) -> None:
        reg = InMemoryAssetRegistry()
        reg.reserve_asset(space="s", aliases={"m": True}, owner_service_id="svc")
        with self.assertRaises(AliasImmutableError):
            reg.detach_alias(space="s", alias="m", caller_service_id="svc")

        reg.reserve_asset(space="s", aliases=["i"], owner_service_id="svc")
        with self.assertRaises(AliasImmutableError):
            reg.detach_mutable_alias(space="s", alias="i", caller_service_id="svc")

    def test_update_annotations_merge(self) -> None:
        a = self.registry.reserve_asset(
            space="cache",
            aliases=["doc"],
            owner_service_id="svc",
            annotations={"k1": "v1"},
        )
        self.registry.commit_asset(
            asset_id=a.asset_id,
            size_bytes=1,
            checksum="sha256:x",
            caller_service_id="svc",
        )
        updated = self.registry.update_annotations(
            asset_id=a.asset_id,
            patch={"k2": "v2"},
            caller_service_id="svc",
        )
        self.assertEqual("v1", updated.annotations["k1"])
        self.assertEqual("v2", updated.annotations["k2"])

    def test_delete_asset_blocks_resolve(self) -> None:
        a = self.registry.reserve_asset(space="cache", aliases=["z"], owner_service_id="svc")
        self.registry.commit_asset(
            asset_id=a.asset_id,
            size_bytes=1,
            checksum="sha256:x",
            caller_service_id="svc",
        )
        self.registry.delete_asset(asset_id=a.asset_id, caller_service_id="svc")
        with self.assertRaises(InvalidStateTransitionError):
            self.registry.resolve_alias(space="cache", alias="z")

    def test_attach_alias_to_existing_asset(self) -> None:
        a = self.registry.reserve_asset(space="cache", aliases=["primary"], owner_service_id="svc")
        self.registry.commit_asset(
            asset_id=a.asset_id,
            size_bytes=1,
            checksum="sha256:x",
            caller_service_id="svc",
        )
        self.registry.attach_alias(
            asset_id=a.asset_id,
            alias="secondary",
            mutable=False,
            caller_service_id="svc",
        )
        self.assertEqual(
            a.asset_id,
            self.registry.resolve_alias(space="cache", alias="secondary").asset_id,
        )


if __name__ == "__main__":
    unittest.main()
