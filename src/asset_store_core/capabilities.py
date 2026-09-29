"""Capability checks shared by storage-guard adapters.

Implements prefix-scoped authorization from ``FR-010``–``FR-012`` and optional
single-use enforcement from ``FR-013`` via :class:`SingleUseLedger`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock

from asset_store_core.errors import (
    CapabilityAlreadyConsumedError,
    CapabilityCapacityError,
    CapabilityDeniedError,
    ValidationError,
)
from asset_store_core.models import utcnow
from asset_store_core.paths import normalize_relative_alias, normalize_space


class Operation(StrEnum):
    """Operations a capability can authorize."""

    READ = "read"
    WRITE = "write"


@dataclass(frozen=True, slots=True)
class Capability:
    """Time-bounded, prefix-scoped authorization.

    Scope matching is path-segment aware: ``users/42/uploads`` matches
    ``users/42/uploads/a.jpg``, but not ``users/42/uploads2/a.jpg``.

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
                "scope_prefix must include bucket and at least one segment, e.g. 'users/42/uploads'"
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
                f"capability does not authorize {operation.value} on {qualified_alias!r}"
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

    __slots__ = ("_clock", "_consumed", "_lock")

    def __init__(self, *, clock: Callable[[], datetime] = utcnow) -> None:
        self._clock = clock
        self._consumed: dict[str, datetime] = {}
        self._lock = Lock()

    def prune_expired(self) -> None:
        """Retire expired consumed identifiers, including during reusable mints."""
        with self._lock:
            self._prune_locked(self._clock())

    def _prune_locked(self, now: datetime) -> None:
        for capability_id, expires_at in tuple(self._consumed.items()):
            if expires_at <= now:
                del self._consumed[capability_id]

    def record_successful_use(self, cap: Capability) -> None:
        """Record that ``cap`` has been used successfully once."""

        with self._lock:
            self._prune_locked(self._clock())
            if not cap.single_use:
                return
            if cap.capability_id in self._consumed:
                raise CapabilityAlreadyConsumedError("single-use capability already consumed")
            self._consumed[cap.capability_id] = cap.expires_at

    def assert_unused(self, cap: Capability) -> None:
        """Raise if a single-use capability was already consumed."""

        with self._lock:
            self._prune_locked(self._clock())
            if cap.single_use and cap.capability_id in self._consumed:
                raise CapabilityAlreadyConsumedError("single-use capability already consumed")


class CapabilityStore:
    """Bounded process-local bearer store with atomic audit-before-publication (ADR-026)."""

    __slots__ = ("_capabilities", "_clock", "_lock", "max_capabilities")

    def __init__(self, max_capabilities: int, *, clock: Callable[[], datetime] = utcnow) -> None:
        if max_capabilities <= 0:
            raise ValidationError("ASSET_STORE_MAX_CAPABILITIES must be a positive integer")
        self.max_capabilities = max_capabilities
        self._clock = clock
        self._capabilities: dict[str, Capability] = {}
        self._lock = Lock()

    def _prune_locked(self, now: datetime) -> None:
        for capability_id, cap in tuple(self._capabilities.items()):
            if cap.expires_at <= now:
                del self._capabilities[capability_id]

    def issue(self, cap: Capability, *, on_grant: Callable[[], None]) -> None:
        """Audit then publish one valid grant while holding the admission lock."""
        with self._lock:
            now = self._clock()
            self._prune_locked(now)
            if cap.expires_at <= now:
                raise ValidationError("capability must expire in the future")
            if len(self._capabilities) >= self.max_capabilities:
                raise CapabilityCapacityError("capability capacity temporarily unavailable")
            on_grant()
            self._capabilities[cap.capability_id] = cap

    def get(self, capability_id: str) -> Capability | None:
        """Look up a live bearer, retiring expired entries first."""
        with self._lock:
            self._prune_locked(self._clock())
            return self._capabilities.get(capability_id)

    def __len__(self) -> int:
        with self._lock:
            self._prune_locked(self._clock())
            return len(self._capabilities)


def _is_same_path_or_child(candidate: str, prefix: str) -> bool:
    """Return true when ``candidate`` equals ``prefix`` or is a strict child path."""

    normalized_candidate = candidate.strip("/")
    normalized_prefix = prefix.strip("/")
    return normalized_candidate == normalized_prefix or normalized_candidate.startswith(
        f"{normalized_prefix}/"
    )
