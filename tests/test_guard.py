"""Storage-guard facade: capability + service-policy + registry composition."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from asset_store_core import (
    Capability,
    CapabilityAlreadyConsumedError,
    CapabilityDeniedError,
    InMemoryAssetRegistry,
    LocalObjectStore,
    Operation,
    SingleUseLedger,
    StorageGuard,
)


def _cap(
    *,
    service: str,
    operation: Operation,
    scope_prefix: str,
    ttl: timedelta = timedelta(minutes=5),
    single_use: bool = False,
    capability_id: str = "cap",
) -> Capability:
    return Capability(
        capability_id=capability_id,
        operation=operation,
        scope_prefix=scope_prefix,
        expires_at=datetime.now(UTC) + ttl,
        caller_service_id=service,
        single_use=single_use,
    )


class StorageGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = InMemoryAssetRegistry()
        self.store = LocalObjectStore()
        self.guard = StorageGuard(self.registry, self.store)

    def _ingest(self, alias: str, payload: bytes, *, service: str = "bulk-loader") -> None:
        space_prefix = "/".join(alias.split("/")[:2])
        self.guard.write_object(
            capability=_cap(service=service, operation=Operation.WRITE, scope_prefix=space_prefix),
            alias=alias,
            data=payload,
        )

    def test_write_then_read_round_trip_through_guard(self) -> None:
        payload = b"image-bytes"
        self._ingest("cache/gallica/img.png", payload)

        data = self.guard.read_bytes(
            capability=_cap(
                service="worker", operation=Operation.READ, scope_prefix="cache/gallica"
            ),
            alias="cache/gallica/img.png",
        )
        self.assertEqual(payload, data)

    def test_capability_scope_mismatch_is_denied(self) -> None:
        self._ingest("cache/gallica/img.png", b"x")
        with self.assertRaises(CapabilityDeniedError):
            self.guard.read_bytes(
                capability=_cap(
                    service="worker", operation=Operation.READ, scope_prefix="cache/other"
                ),
                alias="cache/gallica/img.png",
            )

    def test_wrong_operation_is_denied(self) -> None:
        # A READ capability cannot authorize a write.
        with self.assertRaises(CapabilityDeniedError):
            self.guard.write_object(
                capability=_cap(
                    service="bulk-loader", operation=Operation.READ, scope_prefix="cache/gallica"
                ),
                alias="cache/gallica/new.png",
                data=b"x",
            )

    def test_expired_capability_is_denied(self) -> None:
        self._ingest("cache/gallica/img.png", b"x")
        with self.assertRaises(CapabilityDeniedError):
            self.guard.read_bytes(
                capability=_cap(
                    service="worker",
                    operation=Operation.READ,
                    scope_prefix="cache/gallica",
                    ttl=timedelta(seconds=-1),
                ),
                alias="cache/gallica/img.png",
            )

    def test_service_policy_blocks_disallowed_write_bucket(self) -> None:
        # worker may write only `results`; a users write must be denied even with
        # a validly-scoped capability.
        with self.assertRaises(CapabilityDeniedError):
            self.guard.write_object(
                capability=_cap(
                    service="worker", operation=Operation.WRITE, scope_prefix="users/42"
                ),
                alias="users/42/uploads/file.jpg",
                data=b"x",
            )

    def test_service_policy_blocks_disallowed_read_bucket(self) -> None:
        # bulk-loader may read only `cache`; reading tmp is denied before resolve.
        with self.assertRaises(CapabilityDeniedError):
            self.guard.read_bytes(
                capability=_cap(
                    service="bulk-loader", operation=Operation.READ, scope_prefix="tmp/p"
                ),
                alias="tmp/p/x",
            )

    def test_single_use_read_consumed_after_first_success(self) -> None:
        ledger = SingleUseLedger()
        guard = StorageGuard(self.registry, self.store, ledger=ledger)
        self._ingest("cache/gallica/img.png", b"payload")
        cap = _cap(
            service="worker",
            operation=Operation.READ,
            scope_prefix="cache/gallica",
            single_use=True,
            capability_id="cap-su",
        )

        self.assertEqual(b"payload", guard.read_bytes(capability=cap, alias="cache/gallica/img.png"))
        with self.assertRaises(CapabilityAlreadyConsumedError):
            guard.read_bytes(capability=cap, alias="cache/gallica/img.png")

    def test_write_records_owner_and_resolves(self) -> None:
        asset = self.guard.write_object(
            capability=_cap(
                service="bulk-loader", operation=Operation.WRITE, scope_prefix="cache/gallica"
            ),
            alias="cache/gallica/doc.bin",
            data=b"abc",
        )
        self.assertEqual("bulk-loader", asset.owner_service_id)
        self.assertEqual("cache", asset.space)
        self.assertIn("cache/gallica/doc.bin", asset.aliases)


if __name__ == "__main__":
    unittest.main()
