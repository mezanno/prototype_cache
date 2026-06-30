"""Storage-guard facade (FR-010..015).

Single authorization choke point that composes, in order:

1. **Capability** scope/operation/expiry checks (``FR-010``-``FR-012``) and
   single-use enforcement (``FR-013``).
2. **Service-to-bucket** allowlist (``FR-015``).
3. **Registry** and **object-store** calls.

Callers (workers, upload-api, ...) go through this facade so authorization is never
re-implemented per caller. Mirrors the conceptual ``storage-guard`` layer (``ADR-002``).

Aliases are passed in **qualified** form ``space/partition/name...`` (the same string
the capability scope is expressed in). The facade derives the partition-exclusive
form the registry's ``reserve_asset`` expects and the partition-inclusive form
``resolve_alias`` expects.
"""

from __future__ import annotations

from dataclasses import dataclass

from asset_store_core.capabilities import Capability, Operation, SingleUseLedger
from asset_store_core.errors import ValidationError
from asset_store_core.models import Asset
from asset_store_core.object_store import ObjectStoreBackend
from asset_store_core.paths import normalize_relative_alias, normalize_space, qualified_alias
from asset_store_core.registry import InMemoryAssetRegistry
from asset_store_core.service_policy import assert_service_bucket_allowed
from asset_store_core.storage import ObjectStoreLocation, normalize_partition_id


@dataclass(frozen=True, slots=True)
class _ParsedAlias:
    space: str
    relative: str  # 'partition/name...' — for resolve_alias
    partition_id: str  # for reserve_asset
    alias_in_partition: str  # 'name...' — for reserve_asset aliases
    qualified: str  # 'space/partition/name...' — for capability + scope


def _parse_alias(alias: str) -> _ParsedAlias:
    cleaned = alias.strip().strip("/")
    space_raw, sep, remainder = cleaned.partition("/")
    if not sep or not remainder:
        raise ValidationError("alias must be qualified: 'space/partition/name...'")
    space = normalize_space(space_raw)
    relative = normalize_relative_alias(remainder)
    partition_raw, psep, in_partition = relative.partition("/")
    if not psep or not in_partition:
        raise ValidationError("alias must include a partition and a name: 'space/partition/name'")
    return _ParsedAlias(
        space=space,
        relative=relative,
        partition_id=normalize_partition_id(partition_raw),
        alias_in_partition=normalize_relative_alias(in_partition),
        qualified=qualified_alias(space, relative),
    )


@dataclass(frozen=True, slots=True)
class GuardedRead:
    """Result of an authorized read: the asset plus where its bytes live."""

    asset: Asset
    location: ObjectStoreLocation


class StorageGuard:
    """Authorization facade over the registry and an object-store backend."""

    __slots__ = ("_ledger", "_registry", "_store")

    def __init__(
        self,
        registry: InMemoryAssetRegistry,
        store: ObjectStoreBackend,
        *,
        ledger: SingleUseLedger | None = None,
    ) -> None:
        self._registry = registry
        self._store = store
        self._ledger = ledger if ledger is not None else SingleUseLedger()

    def resolve_for_read(self, *, capability: Capability, alias: str) -> GuardedRead:
        """Authorize a read and resolve the alias without consuming bytes.

        Use this to mint a presigned URL (``ADR-003`` presigned mode); a single-use
        token is *not* consumed here because the guard does not observe the GET.
        """

        parsed = _parse_alias(alias)
        capability.require(operation=Operation.READ, qualified_alias=parsed.qualified)
        self._ledger.assert_unused(capability)
        assert_service_bucket_allowed(
            capability.caller_service_id, parsed.space, operation=Operation.READ
        )
        asset = self._registry.resolve_alias(space=parsed.space, alias=parsed.relative)
        location = ObjectStoreLocation.for_asset(
            space=asset.space, partition_id=asset.partition_id, asset_id=asset.asset_id
        )
        return GuardedRead(asset=asset, location=location)

    def read_bytes(self, *, capability: Capability, alias: str) -> bytes:
        """Authorize and return object bytes (``ADR-003`` proxy mode).

        Consumes a single-use capability only after a successful read.
        """

        guarded = self.resolve_for_read(capability=capability, alias=alias)
        data = self._store.get_object(guarded.location)
        self._ledger.record_successful_use(capability)
        return data

    def write_object(
        self,
        *,
        capability: Capability,
        alias: str,
        data: bytes,
        mutable: bool = False,
        mime: str | None = None,
        expected_checksum: str | None = None,
    ) -> Asset:
        """Authorize and perform reserve -> PUT -> commit for a new alias.

        Consumes a single-use capability only after a successful commit.
        """

        parsed = _parse_alias(alias)
        capability.require(operation=Operation.WRITE, qualified_alias=parsed.qualified)
        self._ledger.assert_unused(capability)
        assert_service_bucket_allowed(
            capability.caller_service_id, parsed.space, operation=Operation.WRITE
        )

        pending = self._registry.reserve_asset(
            space=parsed.space,
            partition_id=parsed.partition_id,
            aliases={parsed.alias_in_partition: mutable},
            owner_service_id=capability.caller_service_id,
            mime=mime,
        )
        location = ObjectStoreLocation.for_asset(
            space=pending.space, partition_id=pending.partition_id, asset_id=pending.asset_id
        )
        stat = self._store.put_object(location, data)
        asset = self._registry.commit_asset(
            asset_id=pending.asset_id,
            size_bytes=stat.size_bytes,
            checksum=stat.checksum,
            caller_service_id=capability.caller_service_id,
            mime=mime,
            expected_checksum=expected_checksum,
        )
        self._ledger.record_successful_use(capability)
        return asset
