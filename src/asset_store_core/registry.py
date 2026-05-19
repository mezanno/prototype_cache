"""In-memory asset registry.

Executable specification for core invariants the Postgres adapter must preserve.

Requirement mapping (subset implemented here):

- ``FR-001``, ``FR-004`` — reserve aliases + pending asset shell.
- ``FR-002`` — resolve only ``available`` assets; detached mutable aliases do not resolve.
- ``FR-003`` — immutable detach + tombstone grace; mutable detach before rebind.
- ``FR-005`` — annotation updates without touching payload metadata beyond timestamps.
- ``FR-006`` / ``FR-007`` — expire and delete transitions.
- ``FR-008`` — mutable alias rebind after explicit detach.
- ``FR-022`` — optional expected checksum verification on commit.
- ``FR-015`` — bucket allowlist lives in :mod:`service_policy` (not invoked here).

This module intentionally does **not** implement HTTP, Postgres, MinIO IO, or
storage-guard. Call :class:`~asset_store_core.registry.InMemoryAssetRegistry`
directly in unit tests; enforce :mod:`service_policy` in integration tests when
the guard adapter exists.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace as dc_replace
from datetime import datetime, timedelta
from types import MappingProxyType

from asset_store_core.errors import (
    AliasConflictError,
    AliasImmutableError,
    AliasNotFoundError,
    AssetNotFoundError,
    ChecksumMismatchError,
    InvalidStateTransitionError,
    ValidationError,
)
from asset_store_core.ids import new_asset_id
from asset_store_core.models import AliasBinding, Asset, AssetState, AuditEvent, utcnow
from asset_store_core.paths import (
    normalize_relative_alias,
    normalize_space,
    qualified_alias,
    qualified_alias_for_partition,
)
from asset_store_core.storage import build_storage_key, normalize_partition_id


class InMemoryAssetRegistry:
    """Thread-unsafe in-memory registry for tests and spike adapters."""

    __slots__ = (
        "_alias_grace",
        "_aliases",
        "_assets",
        "_audit_events",
        "_tombstones",
    )

    def __init__(self, *, alias_name_grace_period: timedelta | None = None) -> None:
        """Create a registry.

        ``alias_name_grace_period`` controls FR-003 name reuse after immutable detach
        (default: 7 days).
        """

        self._assets: dict[str, Asset] = {}
        self._aliases: dict[str, AliasBinding] = {}
        self._audit_events: list[AuditEvent] = []
        self._tombstones: dict[str, datetime] = {}
        if alias_name_grace_period is None:
            self._alias_grace = timedelta(days=7)
        else:
            if alias_name_grace_period < timedelta(0):
                raise ValidationError("alias_name_grace_period must not be negative")
            self._alias_grace = alias_name_grace_period

    @property
    def audit_events(self) -> tuple[AuditEvent, ...]:
        """Immutable view of recorded audit events."""

        return tuple(self._audit_events)

    def reserve_asset(
        self,
        *,
        space: str,
        partition_id: str,
        aliases: Iterable[str] | Mapping[str, bool],
        owner_service_id: str,
        mime: str | None = None,
        annotations: Mapping[str, str] | None = None,
    ) -> Asset:
        """Reserve aliases and create a pending asset shell (FR-004)."""

        norm_space = normalize_space(space)
        norm_partition = normalize_partition_id(partition_id)
        alias_specs = _normalize_alias_specs(aliases)

        for alias in alias_specs:
            scoped = _alias_under_partition(norm_partition, alias)
            self._require_alias_name_available(norm_space, scoped)

        asset_id = new_asset_id()
        now = utcnow()
        qualified_aliases = frozenset(
            qualified_alias_for_partition(norm_space, norm_partition, alias_name)
            for alias_name in alias_specs
        )
        asset = Asset(
            asset_id=asset_id,
            space=norm_space,
            partition_id=norm_partition,
            storage_key=build_storage_key(partition_id=norm_partition, asset_id=asset_id),
            state=AssetState.PENDING,
            aliases=qualified_aliases,
            mime=mime,
            annotations=MappingProxyType(dict(annotations or {})),
            created_at=now,
            updated_at=now,
            owner_service_id=owner_service_id,
        )
        self._assets[asset_id] = asset

        for alias_name, mutable in alias_specs.items():
            scoped = _alias_under_partition(norm_partition, alias_name)
            binding = AliasBinding(
                space=norm_space,
                alias=scoped,
                asset_id=asset_id,
                mutable=mutable,
                created_at=now,
                updated_at=now,
                created_by_service_id=owner_service_id,
            )
            key = binding.qualified_alias
            self._aliases[key] = binding
            self._audit(
                action="alias.create",
                target=key,
                caller_service_id=owner_service_id,
                outcome="success",
                after={"asset_id": asset_id, "mutable": str(mutable).lower()},
            )

        return asset

    def attach_alias(
        self,
        *,
        asset_id: str,
        alias: str,
        mutable: bool,
        caller_service_id: str,
    ) -> AliasBinding:
        """Attach a new alias to an existing asset (FR-003 partial — add alias)."""

        asset = self._get_asset(asset_id)
        if asset.state is AssetState.DELETED:
            raise InvalidStateTransitionError(
                f"cannot attach alias to deleted asset {asset_id!r}"
            )

        norm_space = normalize_space(asset.space)
        alias_name = _alias_under_partition(asset.partition_id, alias)
        self._require_alias_name_available(norm_space, alias_name)

        key = qualified_alias(norm_space, alias_name)
        now = utcnow()
        binding = AliasBinding(
            space=norm_space,
            alias=alias_name,
            asset_id=asset_id,
            mutable=mutable,
            created_at=now,
            updated_at=now,
            created_by_service_id=caller_service_id,
        )
        self._aliases[key] = binding
        self._add_alias_to_asset(asset_id, key)

        self._audit(
            action="alias.attach",
            target=key,
            caller_service_id=caller_service_id,
            outcome="success",
            after={"asset_id": asset_id, "mutable": str(mutable).lower()},
        )
        return binding

    def commit_asset(
        self,
        *,
        asset_id: str,
        size_bytes: int,
        checksum: str,
        caller_service_id: str,
        mime: str | None = None,
        expected_checksum: str | None = None,
    ) -> Asset:
        """Transition ``pending`` → ``available`` after payload commit (FR-022)."""

        if size_bytes < 0:
            raise ValidationError("size_bytes must be >= 0")
        server_checksum = checksum.strip()
        if not server_checksum:
            raise ValidationError("checksum must be non-empty")

        if expected_checksum is not None and expected_checksum != server_checksum:
            raise ChecksumMismatchError(
                f"checksum mismatch: expected {expected_checksum!r}, got {server_checksum!r}"
            )

        asset = self._get_asset(asset_id)
        if asset.state is not AssetState.PENDING:
            raise InvalidStateTransitionError(
                f"asset {asset_id!r} cannot be committed from state {asset.state.value!r}"
            )

        updated = dc_replace(
            asset,
            state=AssetState.AVAILABLE,
            size_bytes=size_bytes,
            checksum=server_checksum,
            mime=mime or asset.mime,
            updated_at=utcnow(),
        )
        self._assets[asset_id] = updated
        self._audit(
            action="asset.commit",
            target=asset_id,
            caller_service_id=caller_service_id,
            outcome="success",
            before={"state": asset.state.value},
            after={"state": updated.state.value},
        )
        return updated

    def update_annotations(
        self,
        *,
        asset_id: str,
        patch: Mapping[str, str],
        caller_service_id: str,
        overwrite: bool = False,
    ) -> Asset:
        """Merge or replace annotation map (FR-005)."""

        asset = self._get_asset(asset_id)
        if asset.state is AssetState.DELETED:
            raise InvalidStateTransitionError(
                f"cannot update annotations on deleted asset {asset_id!r}"
            )

        if overwrite:
            merged = dict(patch)
        else:
            merged = dict(asset.annotations)
            merged.update(patch)

        updated = dc_replace(
            asset,
            annotations=MappingProxyType(merged),
            updated_at=utcnow(),
        )
        self._assets[asset_id] = updated
        self._audit(
            action="asset.annotations_update",
            target=asset_id,
            caller_service_id=caller_service_id,
            outcome="success",
            before=dict(asset.annotations),
            after=dict(updated.annotations),
        )
        return updated

    def resolve_alias(self, *, space: str, alias: str) -> Asset:
        """Resolve an alias to an ``available`` asset (FR-002)."""

        binding = self._get_binding(space, alias)
        if binding.asset_id is None:
            raise InvalidStateTransitionError(
                f"alias {binding.qualified_alias!r} is detached pending rebind"
            )

        asset = self._get_asset(binding.asset_id)
        if not asset.is_resolvable:
            raise InvalidStateTransitionError(
                f"asset {asset.asset_id!r} is not resolvable in state {asset.state.value!r}"
            )
        return asset

    def detach_alias(
        self,
        *,
        space: str,
        alias: str,
        caller_service_id: str,
    ) -> None:
        """Detach an **immutable** alias (FR-003).

        Removes the binding and blocks reuse of the qualified name until the grace
        period elapses.
        """

        binding = self._get_binding(space, alias)
        if binding.mutable:
            raise AliasImmutableError(
                f"use detach_mutable_alias for mutable alias {binding.qualified_alias!r}"
            )

        key = binding.qualified_alias
        asset_id = binding.asset_id
        if asset_id is None:
            raise InvalidStateTransitionError(f"alias {key!r} is not bound")

        del self._aliases[key]
        self._remove_alias_from_asset(asset_id, key)
        if self._alias_grace > timedelta(0):
            self._tombstones[key] = utcnow() + self._alias_grace

        self._audit(
            action="alias.detach",
            target=key,
            caller_service_id=caller_service_id,
            outcome="success",
            before={"asset_id": asset_id},
            after={},
        )

    def detach_mutable_alias(
        self,
        *,
        space: str,
        alias: str,
        caller_service_id: str,
    ) -> AliasBinding:
        """Detach a **mutable** alias in preparation for ``rebind_alias`` (FR-003)."""

        binding = self._get_binding(space, alias)
        if not binding.mutable:
            raise AliasImmutableError(
                f"use detach_alias for immutable alias {binding.qualified_alias!r}"
            )

        old_asset_id = binding.asset_id
        if old_asset_id is None:
            raise InvalidStateTransitionError(
                f"mutable alias {binding.qualified_alias!r} is already detached"
            )

        key = binding.qualified_alias
        self._remove_alias_from_asset(old_asset_id, key)
        updated_binding = dc_replace(binding, asset_id=None, updated_at=utcnow())
        self._aliases[key] = updated_binding

        self._audit(
            action="alias.detach_mutable",
            target=key,
            caller_service_id=caller_service_id,
            outcome="success",
            before={"asset_id": old_asset_id},
            after={"asset_id": ""},
        )
        return updated_binding

    def rebind_alias(
        self,
        *,
        space: str,
        alias: str,
        new_asset_id: str,
        caller_service_id: str,
    ) -> AliasBinding:
        """Rebind a **mutable** alias after ``detach_mutable_alias`` (FR-008)."""

        binding = self._get_binding(space, alias)
        if not binding.mutable:
            raise AliasImmutableError(f"alias {binding.qualified_alias!r} is immutable")

        if binding.asset_id is not None:
            raise InvalidStateTransitionError(
                f"mutable alias {binding.qualified_alias!r} must be detached before rebind"
            )

        new_asset = self._get_asset(new_asset_id)
        if new_asset.space != binding.space:
            raise AliasConflictError("cannot rebind an alias across buckets")
        if new_asset.partition_id != _partition_from_scoped_alias(binding.alias):
            raise AliasConflictError("cannot rebind an alias across partitions")
        if new_asset.state is not AssetState.AVAILABLE:
            raise InvalidStateTransitionError(
                f"rebind target asset {new_asset_id!r} must be available, "
                f"got {new_asset.state.value!r}"
            )

        key = binding.qualified_alias
        updated_binding = dc_replace(binding, asset_id=new_asset_id, updated_at=utcnow())
        self._aliases[key] = updated_binding
        self._add_alias_to_asset(new_asset_id, key)

        self._audit(
            action="alias.rebind",
            target=key,
            caller_service_id=caller_service_id,
            outcome="success",
            before={"asset_id": ""},
            after={"asset_id": new_asset_id},
        )
        return updated_binding

    def expire_asset(self, *, asset_id: str, caller_service_id: str) -> Asset:
        """Transition ``available`` → ``expired`` (FR-006)."""

        asset = self._get_asset(asset_id)
        if asset.state is not AssetState.AVAILABLE:
            raise InvalidStateTransitionError(
                f"asset {asset_id!r} cannot expire from state {asset.state.value!r}"
            )

        updated = dc_replace(asset, state=AssetState.EXPIRED, updated_at=utcnow())
        self._assets[asset_id] = updated
        self._audit(
            action="asset.expire",
            target=asset_id,
            caller_service_id=caller_service_id,
            outcome="success",
            before={"state": asset.state.value},
            after={"state": updated.state.value},
        )
        return updated

    def delete_asset(self, *, asset_id: str, caller_service_id: str) -> Asset:
        """Transition to ``deleted`` from ``available`` or ``expired`` (FR-007)."""

        asset = self._get_asset(asset_id)
        if asset.state not in (AssetState.AVAILABLE, AssetState.EXPIRED):
            raise InvalidStateTransitionError(
                f"asset {asset_id!r} cannot be deleted from state {asset.state.value!r}"
            )

        updated = dc_replace(asset, state=AssetState.DELETED, updated_at=utcnow())
        self._assets[asset_id] = updated
        self._audit(
            action="asset.delete",
            target=asset_id,
            caller_service_id=caller_service_id,
            outcome="success",
            before={"state": asset.state.value},
            after={"state": updated.state.value},
        )
        return updated

    def _get_asset(self, asset_id: str) -> Asset:
        try:
            return self._assets[asset_id]
        except KeyError as exc:
            raise AssetNotFoundError(asset_id) from exc

    def _get_binding(self, space: str, alias: str) -> AliasBinding:
        key = qualified_alias(normalize_space(space), normalize_relative_alias(alias))
        try:
            return self._aliases[key]
        except KeyError as exc:
            raise AliasNotFoundError(key) from exc

    def _alias_name_is_blocked(self, norm_space: str, alias_name: str) -> bool:
        key = qualified_alias(norm_space, alias_name)
        if key in self._aliases:
            return True

        grace_until = self._tombstones.get(key)
        if grace_until is None:
            return False
        now = utcnow()
        if now >= grace_until:
            del self._tombstones[key]
            return False
        return True

    def _require_alias_name_available(self, norm_space: str, alias_name: str) -> None:
        if self._alias_name_is_blocked(norm_space, alias_name):
            key = qualified_alias(norm_space, alias_name)
            raise AliasConflictError(f"alias {key!r} already exists or is within grace period")

    def _add_alias_to_asset(self, asset_id: str, qualified_key: str) -> None:
        asset = self._get_asset(asset_id)
        self._assets[asset_id] = dc_replace(
            asset,
            aliases=frozenset({*asset.aliases, qualified_key}),
            updated_at=utcnow(),
        )

    def _remove_alias_from_asset(self, asset_id: str, qualified_key: str) -> None:
        asset = self._get_asset(asset_id)
        aliases = frozenset(a for a in asset.aliases if a != qualified_key)
        self._assets[asset_id] = dc_replace(asset, aliases=aliases, updated_at=utcnow())

    def _audit(
        self,
        *,
        action: str,
        target: str,
        caller_service_id: str,
        outcome: str,
        before: Mapping[str, str] | None = None,
        after: Mapping[str, str] | None = None,
    ) -> None:
        self._audit_events.append(
            AuditEvent(
                action=action,
                target=target,
                caller_service_id=caller_service_id,
                outcome=outcome,
                before=MappingProxyType(dict(before or {})),
                after=MappingProxyType(dict(after or {})),
            )
        )


def _normalize_alias_specs(aliases: Iterable[str] | Mapping[str, bool]) -> dict[str, bool]:
    if isinstance(aliases, Mapping):
        return {
            normalize_relative_alias(alias): bool(mutable) for alias, mutable in aliases.items()
        }
    return {normalize_relative_alias(alias): False for alias in aliases}


def _alias_under_partition(partition_id: str, relative_alias: str) -> str:
    """Return alias path under ``partition_id`` (idempotent if already prefixed)."""

    rel = normalize_relative_alias(relative_alias)
    prefix = normalize_partition_id(partition_id)
    if rel == prefix or rel.startswith(f"{prefix}/"):
        return rel
    return f"{prefix}/{rel}"


def _partition_from_scoped_alias(scoped_alias: str) -> str:
    """First path segment of a bucket-relative alias path."""

    return normalize_partition_id(scoped_alias.split("/", 1)[0])
