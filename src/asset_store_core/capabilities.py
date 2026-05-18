"""Capability checks shared by storage-guard adapters.

Implements prefix-scoped authorization from ``FR-010``–``FR-012`` and optional
single-use enforcement from ``FR-013`` via :class:`SingleUseLedger`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from asset_store_core.errors import (
    CapabilityAlreadyConsumedError,
    CapabilityDeniedError,
    ValidationError,
)
from asset_store_core.paths import normalize_relative_alias, normalize_space
from asset_store_core.models import utcnow


class Operation(StrEnum):
    """Operations a capability can authorize."""

    READ = "read"
    WRITE = "write"


@dataclass(frozen=True, slots=True)
class Capability:
    """Time-bounded, prefix-scoped authorization.

    Scope matching is path-segment aware: ``u-42/uploads`` matches
    ``u-42/uploads/a.jpg``, but not ``u-42/uploads2/a.jpg``.

    ``expires_at`` must be timezone-aware; naive datetimes are rejected to avoid
    ambiguous comparisons.
    """

    capability_id: str
    operation: Operation
    scope_prefix: str
    expires_at: datetime
    caller_service_id: str
    single_use: bool = False

    def __post_init__(self) -> None:
        if self.expires_at.tzinfo is None:
            raise ValidationError("expires_at must be timezone-aware (use UTC)")
        raw = self.scope_prefix.strip().strip("/")
        parts = raw.split("/")
        if len(parts) < 2:
            raise ValidationError(
                "scope_prefix must include space and at least one segment, e.g. 'u-42/uploads'"
            )
        try:
            normalize_space(parts[0])
            normalize_relative_alias("/".join(parts[1:]))
        except ValidationError as exc:
            raise ValidationError(f"invalid scope_prefix {self.scope_prefix!r}: {exc}") from exc

    def allows(
        self,
        *,
        operation: Operation,
        qualified_alias: str,
        now: datetime | None = None,
    ) -> bool:
        """Return true when this capability authorizes the operation."""

        now = self._coerce_now(now)
        return (
            operation is self.operation
            and now < self.expires_at
            and _is_same_path_or_child(qualified_alias, self.scope_prefix)
        )

    def require(self, *, operation: Operation, qualified_alias: str) -> None:
        """Raise if this capability does not authorize the operation."""

        if not self.allows(operation=operation, qualified_alias=qualified_alias):
            raise CapabilityDeniedError(
                f"capability {self.capability_id!r} does not authorize "
                f"{operation.value} on {qualified_alias!r}"
            )

    @staticmethod
    def _coerce_now(now: datetime | None) -> datetime:
        candidate = now if now is not None else utcnow()
        if candidate.tzinfo is None:
            return candidate.replace(tzinfo=UTC)
        return candidate


class SingleUseLedger:
    """Tracks consumed single-use capability ids (FR-013).

    Typical adapter flow:

    1. ``cap.require(...)`` — authorize prefix + op + expiry.
    2. Perform the object-store operation.
    3. ``ledger.record_successful_use(cap)`` — mark consumed if ``single_use``.
    """

    __slots__ = ("_consumed",)

    def __init__(self) -> None:
        self._consumed: set[str] = set()

    def record_successful_use(self, cap: Capability) -> None:
        """Record that ``cap`` has been used successfully once."""

        if not cap.single_use:
            return
        if cap.capability_id in self._consumed:
            raise CapabilityAlreadyConsumedError(cap.capability_id)
        self._consumed.add(cap.capability_id)

    def assert_unused(self, cap: Capability) -> None:
        """Raise if a single-use capability was already consumed."""

        if cap.single_use and cap.capability_id in self._consumed:
            raise CapabilityAlreadyConsumedError(cap.capability_id)


def _is_same_path_or_child(candidate: str, prefix: str) -> bool:
    """Return true when ``candidate`` equals ``prefix`` or is a strict child path."""

    normalized_candidate = candidate.strip("/")
    normalized_prefix = prefix.strip("/")
    return normalized_candidate == normalized_prefix or normalized_candidate.startswith(
        f"{normalized_prefix}/"
    )
