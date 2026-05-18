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
    ValidationError,
)
from asset_store_core.ids import new_asset_id
from asset_store_core.models import AliasBinding, Asset, AssetState, AuditEvent
from asset_store_core.paths import qualified_alias, normalize_space, normalize_relative_alias
from asset_store_core.registry import InMemoryAssetRegistry

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
    "Operation",
    "SingleUseLedger",
    "ValidationError",
    "new_asset_id",
    "normalize_relative_alias",
    "normalize_space",
    "qualified_alias",
]
