"""Capability prefix checks and single-use ledger."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from asset_store_core import (
    Capability,
    CapabilityAlreadyConsumedError,
    CapabilityDeniedError,
    Operation,
    SingleUseLedger,
    ValidationError,
)


class CapabilityTest(unittest.TestCase):
    def test_prefix_scope_is_path_segment_aware(self) -> None:
        capability = Capability(
            capability_id="cap-1",
            operation=Operation.READ,
            scope_prefix="users/42/uploads",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            caller_service_id="worker",
        )

        self.assertTrue(
            capability.allows(
                operation=Operation.READ,
                qualified_alias="users/42/uploads/image-1.jpg",
            )
        )
        self.assertTrue(
            capability.allows(
                operation=Operation.READ,
                qualified_alias="users/42/uploads",
            )
        )
        self.assertFalse(
            capability.allows(
                operation=Operation.READ,
                qualified_alias="users/42/uploads2/image-1.jpg",
            )
        )

    def test_operation_must_match(self) -> None:
        capability = Capability(
            capability_id="cap-2",
            operation=Operation.READ,
            scope_prefix="users/42/uploads",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            caller_service_id="worker",
        )

        with self.assertRaises(CapabilityDeniedError):
            capability.require(
                operation=Operation.WRITE,
                qualified_alias="users/42/uploads/image-1.jpg",
            )

    def test_expired_capability_denies(self) -> None:
        capability = Capability(
            capability_id="cap-3",
            operation=Operation.READ,
            scope_prefix="users/42/uploads",
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
            caller_service_id="worker",
        )

        self.assertFalse(
            capability.allows(
                operation=Operation.READ,
                qualified_alias="users/42/uploads/image-1.jpg",
            )
        )

    def test_naive_expires_at_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            Capability(
                capability_id="cap-bad",
                operation=Operation.READ,
                scope_prefix="users/42/uploads",
                expires_at=datetime.now(),
                caller_service_id="worker",
            )

    def test_single_use_ledger_enforces_once(self) -> None:
        cap = Capability(
            capability_id="cap-su",
            operation=Operation.READ,
            scope_prefix="users/42/uploads",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            caller_service_id="worker",
            single_use=True,
        )
        ledger = SingleUseLedger()
        ledger.record_successful_use(cap)
        with self.assertRaises(CapabilityAlreadyConsumedError):
            ledger.record_successful_use(cap)


if __name__ == "__main__":
    unittest.main()
