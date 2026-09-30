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

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from prometheus_client import CollectorRegistry, Counter

from asset_store_core.capabilities import Capability, Operation, SingleUseLedger
from asset_store_core.errors import AssetExpiredError, CapabilityDeniedError, ValidationError
from asset_store_core.models import Asset, AssetState, utcnow
from asset_store_core.object_store import ObjectStoreBackend
from asset_store_core.paths import normalize_relative_alias, normalize_space, qualified_alias
from asset_store_core.registry_base import AssetRegistry
from asset_store_core.service_policy import assert_service_bucket_allowed
from asset_store_core.storage import ObjectStoreLocation, normalize_partition_id

# Presigned-read TTL bounds (ADR-003). The effective TTL is additionally capped by
# the minting capability's own remaining lifetime so a URL never outlives its grant.
DEFAULT_PRESIGN_TTL_SECONDS = 300
MAX_PRESIGN_TTL_SECONDS = 3600


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


@dataclass(frozen=True, slots=True)
class PresignedRead:
    """Result of an authorized presigned read (ADR-003 presigned mode)."""

    asset: Asset
    url: str
    expires_in: int
    expires_at: datetime


class StorageGuard:
    """Authorization facade over the registry and an object-store backend."""

    __slots__ = ("_ledger", "_registry", "_store", "_cleanup_total")

    def __init__(
        self,
        registry: AssetRegistry,
        store: ObjectStoreBackend,
        *,
        ledger: SingleUseLedger | None = None,
        metrics_registry: CollectorRegistry | None = None,
    ) -> None:
        self._cleanup_total = Counter(
            "asset_store_failed_upload_cleanup_total",
            "Failed upload cleanup attempts by bucket and outcome (SEC-06).",
            ["space", "outcome"],
            registry=metrics_registry or CollectorRegistry(),
        )
        self._registry = registry
        self._store = store
        self._ledger = ledger if ledger is not None else SingleUseLedger()

    def prune_consumed_capabilities(self) -> None:
        """Retire expired single-use state during capability minting (ADR-026)."""
        self._ledger.prune_expired()

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
        self._registry.record_read(guarded.asset.asset_id)
        self._ledger.record_successful_use(capability)
        return data

    def presign_read(
        self,
        *,
        capability: Capability,
        alias: str,
        expires_in: int = DEFAULT_PRESIGN_TTL_SECONDS,
    ) -> PresignedRead:
        """Authorize a read and mint a presigned GET URL (``ADR-003`` presigned mode).

        The effective TTL is ``min(expires_in, MAX_PRESIGN_TTL_SECONDS, capability
        remaining lifetime)`` so the URL never outlives the grant that minted it.
        Single-use capabilities are rejected: a presigned URL is fetched outside the
        guard, so single-use (``FR-013``) cannot be enforced on it.
        """

        if capability.single_use:
            raise CapabilityDeniedError(
                "single-use capability cannot mint a presigned URL (FR-013)"
            )
        if expires_in <= 0:
            raise ValidationError("expires_in must be a positive number of seconds")
        guarded = self.resolve_for_read(capability=capability, alias=alias)
        remaining = int((capability.expires_at - utcnow()).total_seconds())
        if remaining <= 0:
            raise CapabilityDeniedError("capability has expired")
        ttl = min(expires_in, MAX_PRESIGN_TTL_SECONDS, remaining)
        if guarded.asset.expires_at is not None:
            ttl = min(ttl, int((guarded.asset.expires_at - utcnow()).total_seconds()))
            if ttl <= 0:
                raise AssetExpiredError("asset lifetime is too short to presign")
        url = self._store.presign_get_url(guarded.location, expires_in=ttl)
        self._registry.record_read(guarded.asset.asset_id)
        return PresignedRead(
            asset=guarded.asset,
            url=url,
            expires_in=ttl,
            expires_at=utcnow() + timedelta(seconds=ttl),
        )

    def authorize_write(self, *, capability: Capability, alias: str) -> None:
        """Validate a write grant before buffering any HTTP body (FR-012, B-018)."""
        parsed = _parse_alias(alias)
        capability.require(operation=Operation.WRITE, qualified_alias=parsed.qualified)
        self._ledger.assert_unused(capability)
        assert_service_bucket_allowed(
            capability.caller_service_id, parsed.space, operation=Operation.WRITE
        )

    def write_object(
        self,
        *,
        capability: Capability,
        alias: str,
        data: bytes,
        mutable: bool = False,
        mime: str | None = None,
        expected_checksum: str | None = None,
        ttl_seconds: int | None = None,
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
            ttl_seconds=ttl_seconds,
        )
        location = ObjectStoreLocation.for_asset(
            space=pending.space, partition_id=pending.partition_id, asset_id=pending.asset_id
        )
        try:
            with self._registry.asset_lock(pending.asset_id) as locked:
                if locked.state.value != "pending":
                    raise ValidationError("upload reservation is no longer pending")
                stat = self._store.put_object(location, data)
                asset = self._registry.commit_asset(
                    asset_id=pending.asset_id,
                    size_bytes=stat.size_bytes,
                    checksum=stat.checksum,
                    caller_service_id=capability.caller_service_id,
                    mime=mime,
                    expected_checksum=expected_checksum,
                )
        except BaseException:
            self._cleanup_failed_upload(pending.asset_id, location)
            raise
        self._ledger.record_successful_use(capability)
        return asset

    def _cleanup_failed_upload(self, asset_id: str, location: ObjectStoreLocation) -> None:
        """Fence before byte deletion; retain failed cleanup for GC (FR-022/060)."""
        outcome = "deferred"
        try:
            # Persist the fence after the failed upload transaction has exited.
            with self._registry.asset_lock(asset_id) as current:
                if current.state is AssetState.PENDING:
                    self._registry.lifecycle_update(
                        current, state=AssetState.DELETED, now=utcnow(), reason="upload_failed"
                    )
                elif current.state is not AssetState.DELETED:
                    outcome = "preserved"
                    return
            with self._registry.asset_lock(asset_id) as fenced:
                if fenced.payload_deleted_at is not None:
                    outcome = "reclaimed"
                    return
                if fenced.state is not AssetState.DELETED:
                    outcome = "preserved"
                    return
                self._store.delete_object(location)
                self._registry.lifecycle_update(
                    fenced,
                    state=AssetState.DELETED,
                    now=utcnow(),
                    reason="upload_failed",
                    payload_deleted=True,
                )
            outcome = "reclaimed"
        except Exception:
            # Keep the original error; GC retries deleted or old pending assets.
            pass
        finally:
            self._cleanup_total.labels(location.bucket, outcome).inc()
            logging.getLogger("asset_store").log(
                logging.WARNING if outcome == "deferred" else logging.INFO,
                "Failed upload cleanup asset=%s outcome=%s",
                asset_id,
                outcome,
                extra={"event": "upload.cleanup", "space": location.bucket},
            )
