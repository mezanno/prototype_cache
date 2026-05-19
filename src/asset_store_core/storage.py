"""Physical storage layout (ADR-007): object keys and MinIO locations."""

from __future__ import annotations

from dataclasses import dataclass

from asset_store_core.errors import ValidationError
from asset_store_core.paths import STORAGE_BUCKETS, normalize_bucket, normalize_partition_id

# Re-export for callers that imported from storage historically.
__all__ = [
    "STORAGE_BUCKETS",
    "ObjectStoreLocation",
    "build_storage_key",
    "normalize_bucket",
    "normalize_partition_id",
]


def build_storage_key(*, partition_id: str, asset_id: str) -> str:
    """Return object-store key ``{partition_id}/assets/{asset_id}`` (NFR-012)."""

    pid = normalize_partition_id(partition_id)
    aid = asset_id.strip()
    if not aid:
        raise ValidationError("asset_id must be non-empty")
    return f"{pid}/assets/{aid}"


@dataclass(frozen=True, slots=True)
class ObjectStoreLocation:
    """Where bytes live in MinIO for an asset."""

    bucket: str
    key: str

    @classmethod
    def for_asset(cls, *, space: str, partition_id: str, asset_id: str) -> ObjectStoreLocation:
        bucket = normalize_bucket(space)
        return cls(bucket=bucket, key=build_storage_key(partition_id=partition_id, asset_id=asset_id))
