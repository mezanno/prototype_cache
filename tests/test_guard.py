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
    PresignNotSupportedError,
    SingleUseLedger,
    StorageGuard,
)
from asset_store_core.guard import MAX_PRESIGN_TTL_SECONDS
from asset_store_core.storage import ObjectStoreLocation


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

        self.assertEqual(
            b"payload", guard.read_bytes(capability=cap, alias="cache/gallica/img.png")
        )
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


class _PresigningStore(LocalObjectStore):
    """LocalObjectStore that can also mint fake presigned URLs, for guard tests."""

    def presign_get_url(self, location: ObjectStoreLocation, *, expires_in: int) -> str:
        return f"https://signed.example/{location.bucket}/{location.key}?ttl={expires_in}"


class PresignReadTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = InMemoryAssetRegistry()
        self.store = _PresigningStore()
        self.guard = StorageGuard(self.registry, self.store)
        self.guard.write_object(
            capability=_cap(
                service="bulk-loader", operation=Operation.WRITE, scope_prefix="cache/gallica"
            ),
            alias="cache/gallica/img.png",
            data=b"payload",
        )

    def _read_cap(self, **kwargs: object) -> Capability:
        return _cap(
            service="worker",
            operation=Operation.READ,
            scope_prefix="cache/gallica",
            **kwargs,  # type: ignore[arg-type]
        )

    def test_presign_read_returns_signed_url_and_asset(self) -> None:
        result = self.guard.presign_read(
            capability=self._read_cap(), alias="cache/gallica/img.png", expires_in=120
        )
        self.assertIn("signed.example", result.url)
        self.assertEqual("ttl=120", result.url.rsplit("?", 1)[1])
        self.assertEqual(120, result.expires_in)
        self.assertEqual(7, result.asset.size_bytes)

    def test_presign_ttl_capped_by_maximum(self) -> None:
        result = self.guard.presign_read(
            capability=self._read_cap(ttl=timedelta(hours=24)),
            alias="cache/gallica/img.png",
            expires_in=10_000,
        )
        self.assertEqual(MAX_PRESIGN_TTL_SECONDS, result.expires_in)

    def test_presign_ttl_capped_by_capability_remaining(self) -> None:
        result = self.guard.presign_read(
            capability=self._read_cap(ttl=timedelta(seconds=45)),
            alias="cache/gallica/img.png",
            expires_in=600,
        )
        self.assertLessEqual(result.expires_in, 45)
        self.assertGreater(result.expires_in, 0)

    def test_presign_rejects_single_use_capability(self) -> None:
        with self.assertRaises(CapabilityDeniedError):
            self.guard.presign_read(
                capability=self._read_cap(single_use=True),
                alias="cache/gallica/img.png",
            )

    def test_presign_denied_for_wrong_scope(self) -> None:
        with self.assertRaises(CapabilityDeniedError):
            self.guard.presign_read(
                capability=_cap(
                    service="worker", operation=Operation.READ, scope_prefix="cache/other"
                ),
                alias="cache/gallica/img.png",
            )

    def test_presign_unsupported_on_local_store(self) -> None:
        guard = StorageGuard(self.registry, LocalObjectStore())
        with self.assertRaises(PresignNotSupportedError):
            guard.presign_read(capability=self._read_cap(), alias="cache/gallica/img.png")


if __name__ == "__main__":
    unittest.main()
