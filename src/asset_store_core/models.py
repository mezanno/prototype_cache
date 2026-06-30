"""Data structures shared by the core registry and guard logic."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType

from asset_store_core.paths import qualified_alias as build_qualified_alias


class AssetState(StrEnum):
    """Lifecycle states from ADR-005."""

    PENDING = "pending"
    AVAILABLE = "available"
    EXPIRED = "expired"
    DELETED = "deleted"


class EvictionPolicy(StrEnum):
    """Per-asset eviction posture (FR-063, ADR-009).

    ``inherit``: the asset follows the per-space eviction sweep policy.
    ``exempt``: the asset is excluded from all capacity- and quota-triggered
    eviction sweeps; TTL expiry (FR-006/FR-060) still applies normally.
    """

    INHERIT = "inherit"
    EXEMPT = "exempt"


def utcnow() -> datetime:
    """Return timezone-aware UTC time."""

    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class AliasBinding:
    """Binding between a public alias and an internal asset id.

    ``asset_id`` may be ``None`` only for a **mutable** alias that has been
    explicitly detached and is awaiting ``rebind_alias`` (FR-003 / FR-008).
    ``previous_asset_id`` retains the last-bound asset id while detached so the
    next ``alias.rebind`` audit event can record both before and after ids (FR-008).
    """

    space: str
    alias: str
    asset_id: str | None
    mutable: bool = False
    previous_asset_id: str | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    created_by_service_id: str = "system"

    @property
    def qualified_alias(self) -> str:
        """Return the namespace-qualified alias used by guard capabilities."""

        return build_qualified_alias(self.space, self.alias)


@dataclass(frozen=True, slots=True)
class Asset:
    """Payload metadata object + lifecycle state.

    Binary bytes live in object-store; this record is registry truth.
    """

    asset_id: str
    space: str
    partition_id: str
    storage_key: str
    state: AssetState
    aliases: frozenset[str]
    mime: str | None = None
    size_bytes: int | None = None
    checksum_algo: str = "sha256"
    checksum: str | None = None
    annotations: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    expires_at: datetime | None = None
    owner_service_id: str = "system"
    eviction_policy: EvictionPolicy = EvictionPolicy.INHERIT

    @property
    def is_resolvable(self) -> bool:
        """Whether this asset may be returned by alias resolution (FR-002)."""

        return self.state is AssetState.AVAILABLE


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Append-only-style audit record emitted by registry operations."""

    action: str
    target: str
    caller_service_id: str
    outcome: str
    before: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    after: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    ts: datetime = field(default_factory=utcnow)


@dataclass(frozen=True, slots=True)
class PartitionQuota:
    """Per-``(space, partition_id)`` quota counters (FR-066/FR-067, ADR-009).

    ``used_bytes`` / ``used_asset_count`` track only ``available`` assets and are
    maintained incrementally by the registry on commit and on every transition
    out of ``available``. ``quota_bytes`` / ``quota_asset_count`` are ``None``
    when no limit is configured.
    """

    space: str
    partition_id: str
    quota_bytes: int | None = None
    quota_asset_count: int | None = None
    used_bytes: int = 0
    used_asset_count: int = 0
    eviction_sweep_enabled: bool = False


@dataclass(frozen=True, slots=True)
class BucketQuota:
    """Per-``space`` aggregate quota counters (FR-068, ADR-009).

    ``used_bytes`` mirrors the sum of the space's ``PartitionQuota.used_bytes``
    and is maintained atomically alongside per-partition updates.
    """

    space: str
    quota_bytes: int | None = None
    used_bytes: int = 0
    warn_threshold: float = 0.80
    hard_ceiling: float = 1.00
