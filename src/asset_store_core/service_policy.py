"""Service identity → bucket allowlist (FR-015).

The storage-guard HTTP service is not implemented yet. Tests and local spikes call
:class:`~asset_store_core.registry.InMemoryAssetRegistry` directly and may skip
these checks. HTTP adapters and integration tests that simulate the guard should
call :func:`assert_service_bucket_allowed` before minting capabilities or writes.
"""

from __future__ import annotations

from asset_store_core.capabilities import Operation
from asset_store_core.errors import CapabilityDeniedError
from asset_store_core.paths import STORAGE_BUCKETS, normalize_bucket

# Mirrors docs/spec/03_ARCHITECTURE_AND_DECISIONS.md service matrix.
_SERVICE_READ_BUCKETS: dict[str, frozenset[str]] = {
    "fetcher": frozenset({"cache", "tmp"}),
    "upload-api": frozenset({"users", "tmp"}),
    "bulk-loader": frozenset({"cache"}),
    "worker": frozenset({"cache", "users", "tmp", "results"}),
    "task-api": frozenset({"cache", "users", "tmp"}),
    "admin": STORAGE_BUCKETS,
    "iiif-server": frozenset({"cache", "users"}),
}

_SERVICE_WRITE_BUCKETS: dict[str, frozenset[str]] = {
    "fetcher": frozenset({"cache", "tmp"}),
    "upload-api": frozenset({"users", "tmp"}),
    "bulk-loader": frozenset({"cache"}),
    "worker": frozenset({"results"}),
    "task-api": frozenset({"tmp"}),
    "admin": STORAGE_BUCKETS,
    "iiif-server": frozenset(),
}


def buckets_for_service(service_id: str, *, operation: Operation) -> frozenset[str]:
    """Return buckets the service may use for ``operation``."""

    sid = service_id.strip()
    table = _SERVICE_READ_BUCKETS if operation is Operation.READ else _SERVICE_WRITE_BUCKETS
    try:
        return table[sid]
    except KeyError as exc:
        raise CapabilityDeniedError(f"unknown service identity {service_id!r}") from exc


def assert_service_bucket_allowed(
    service_id: str,
    bucket: str,
    *,
    operation: Operation,
) -> None:
    """Raise :class:`CapabilityDeniedError` when ``service_id`` may not use ``bucket``."""

    allowed = buckets_for_service(service_id, operation=operation)
    norm = normalize_bucket(bucket)
    if norm not in allowed:
        raise CapabilityDeniedError(
            f"service {service_id!r} may not {operation.value} bucket {norm!r}"
        )
