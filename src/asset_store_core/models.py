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
