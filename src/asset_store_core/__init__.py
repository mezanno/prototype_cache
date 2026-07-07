"""Core domain model for the asset-store prototype.

The package is intentionally infrastructure-free. HTTP, Postgres, and MinIO
adapters should depend on these rules, not reimplement them.
"""

from asset_store_core.capabilities import Capability, Operation, SingleUseLedger
from asset_store_core.errors import (
    AliasConflictError,
    AliasImmutableError,
    AliasNotFoundError,
    AssetNotFoundError,
    AssetStoreError,
    CapabilityAlreadyConsumedError,
    CapabilityDeniedError,
    ChecksumMismatchError,
    InvalidStateTransitionError,
    ObjectNotFoundError,
    PresignNotSupportedError,
    ValidationError,
)
from asset_store_core.guard import GuardedRead, PresignedRead, StorageGuard
from asset_store_core.ids import new_asset_id
from asset_store_core.models import AliasBinding, Asset, AssetState, AuditEvent
from asset_store_core.object_store import (
    CHECKSUM_ALGO,
    LocalObjectStore,
    ObjectStoreBackend,
    StoredObjectStat,
    compute_checksum,
)
from asset_store_core.paths import (
    normalize_relative_alias,
    normalize_space,
    qualified_alias,
    qualified_alias_for_partition,
)
from asset_store_core.registry import InMemoryAssetRegistry
from asset_store_core.service_policy import assert_service_bucket_allowed, buckets_for_service
from asset_store_core.storage import (
    STORAGE_BUCKETS,
    ObjectStoreLocation,
    build_storage_key,
    normalize_bucket,
    normalize_partition_id,
)

__all__ = [
    "AliasBinding",
    "AliasConflictError",
    "AliasImmutableError",
    "AliasNotFoundError",
    "Asset",
    "AssetNotFoundError",
    "AssetState",
    "AssetStoreError",
    "AuditEvent",
    "Capability",
    "CapabilityAlreadyConsumedError",
    "CapabilityDeniedError",
    "ChecksumMismatchError",
    "InMemoryAssetRegistry",
    "InvalidStateTransitionError",
    "LocalObjectStore",
    "ObjectNotFoundError",
    "ObjectStoreBackend",
    "Operation",
    "SingleUseLedger",
    "StoredObjectStat",
    "ValidationError",
    "new_asset_id",
    "CHECKSUM_ALGO",
    "GuardedRead",
    "PresignNotSupportedError",
    "PresignedRead",
    "StorageGuard",
    "STORAGE_BUCKETS",
    "ObjectStoreLocation",
    "assert_service_bucket_allowed",
    "buckets_for_service",
    "build_storage_key",
    "compute_checksum",
    "normalize_bucket",
    "normalize_partition_id",
    "normalize_relative_alias",
    "normalize_space",
    "qualified_alias",
    "qualified_alias_for_partition",
]
