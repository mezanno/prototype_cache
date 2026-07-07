"""Backend-agnostic registry interface (B-009).

The control-plane surface shared by the in-memory reference registry
(:class:`~asset_store_core.registry.InMemoryAssetRegistry`) and the durable
Postgres adapter (:class:`~asset_store_core.pg_registry.PostgresAssetRegistry`).
Callers — the :class:`~asset_store_core.guard.StorageGuard` facade and the HTTP
app — depend on this :class:`typing.Protocol` rather than a concrete class so the
object-store/registry backends stay swappable (ADR-002).

Only the methods the guard and HTTP app actually invoke are declared here; both
implementations may expose additional helpers.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Protocol, runtime_checkable

from asset_store_core.models import (
    AliasBinding,
    Asset,
    AuditEvent,
    BucketQuota,
    EvictionPolicy,
    PartitionQuota,
)


@runtime_checkable
class AssetRegistry(Protocol):
    """Control-plane operations required by the guard and HTTP app."""

    @property
    def audit_events(self) -> tuple[AuditEvent, ...]:
        """Recorded audit events in insertion order (FR-008/FR-016)."""

    def record_capability_issue(
        self,
        *,
        caller_service_id: str,
        operation: str,
        scope_prefix: str,
        ttl_seconds: int,
        outcome: str,
        capability_id: str | None = ...,
    ) -> None:
        """Append a capability-issuance audit event (FR-050, granted/denied)."""

    def reserve_asset(
        self,
        *,
        space: str,
        partition_id: str,
        aliases: Iterable[str] | Mapping[str, bool],
        owner_service_id: str,
        mime: str | None = ...,
        annotations: Mapping[str, str] | None = ...,
        eviction_policy: EvictionPolicy = ...,
    ) -> Asset: ...

    def commit_asset(
        self,
        *,
        asset_id: str,
        size_bytes: int,
        checksum: str,
        caller_service_id: str,
        mime: str | None = ...,
        expected_checksum: str | None = ...,
    ) -> Asset: ...

    def resolve_alias(self, *, space: str, alias: str) -> Asset: ...

    def update_annotations(
        self,
        *,
        asset_id: str,
        patch: Mapping[str, str],
        caller_service_id: str,
        overwrite: bool = ...,
    ) -> Asset: ...

    def expire_asset(self, *, asset_id: str, caller_service_id: str) -> Asset: ...

    def delete_asset(self, *, asset_id: str, caller_service_id: str) -> Asset: ...

    def detach_alias(self, *, space: str, alias: str, caller_service_id: str) -> None: ...

    def detach_mutable_alias(
        self, *, space: str, alias: str, caller_service_id: str
    ) -> AliasBinding: ...

    def rebind_alias(
        self, *, space: str, alias: str, new_asset_id: str, caller_service_id: str
    ) -> AliasBinding: ...

    def set_eviction_policy(
        self, *, asset_id: str, eviction_policy: EvictionPolicy, caller_service_id: str
    ) -> Asset: ...

    def set_partition_quota(
        self,
        *,
        space: str,
        partition_id: str,
        quota_bytes: int | None = ...,
        quota_asset_count: int | None = ...,
        eviction_sweep_enabled: bool | None = ...,
    ) -> PartitionQuota: ...

    def get_partition_quota(self, *, space: str, partition_id: str) -> PartitionQuota: ...

    def set_bucket_quota(
        self,
        *,
        space: str,
        quota_bytes: int | None = ...,
        warn_threshold: float = ...,
        hard_ceiling: float = ...,
    ) -> BucketQuota: ...

    def get_bucket_quota(self, *, space: str) -> BucketQuota: ...
