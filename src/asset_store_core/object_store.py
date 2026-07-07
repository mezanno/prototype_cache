"""Object-store backend seam (FR-020..022).

Defines the byte-level interface the registry's data plane depends on, plus an
in-memory implementation for tests and single-process spikes. The real
S3-compatible backend (OVH S3 / Garage, ``ADR-001``) is a separate adapter that
satisfies the same :class:`ObjectStoreBackend` protocol.

The asset layer stays authoritative (``ADR-011``): this backend only stores
opaque bytes and reports a server-side checksum at write time. Lifecycle,
quota, and deletion truth live in the registry, never here.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

from asset_store_core.errors import ObjectNotFoundError, PresignNotSupportedError
from asset_store_core.storage import ObjectStoreLocation

CHECKSUM_ALGO = "sha256"


def compute_checksum(data: bytes) -> str:
    """Return the canonical server-side checksum string ``sha256:<hex>`` (FR-022)."""

    return f"{CHECKSUM_ALGO}:{hashlib.sha256(data).hexdigest()}"


@dataclass(frozen=True, slots=True)
class StoredObjectStat:
    """Server-side metadata the registry records at commit time (FR-022)."""

    size_bytes: int
    checksum: str
    checksum_algo: str = CHECKSUM_ALGO


class ObjectStoreBackend(Protocol):
    """Byte-level object-store operations the data plane relies on.

    Implementations MUST compute the server-side checksum themselves on write so
    the registry never has to trust a caller-supplied value (FR-022).
    """

    def put_object(self, location: ObjectStoreLocation, data: bytes) -> StoredObjectStat: ...

    def get_object(self, location: ObjectStoreLocation) -> bytes: ...

    def stat_object(self, location: ObjectStoreLocation) -> StoredObjectStat | None: ...

    def delete_object(self, location: ObjectStoreLocation) -> None: ...

    def presign_get_url(self, location: ObjectStoreLocation, *, expires_in: int) -> str:
        """Return a time-limited URL a client can GET directly (ADR-003 presigned mode).

        Backends without an externally reachable URL raise
        :class:`~asset_store_core.errors.PresignNotSupportedError`.
        """


class LocalObjectStore:
    """In-memory :class:`ObjectStoreBackend` for tests and single-process spikes.

    Computes a server-side sha256 checksum on write, mirroring the real backend's
    behaviour (FR-022). Not thread-safe and not durable; never a deployment target.
    """

    __slots__ = ("_objects",)

    def __init__(self) -> None:
        self._objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, location: ObjectStoreLocation, data: bytes) -> StoredObjectStat:
        payload = bytes(data)
        self._objects[(location.bucket, location.key)] = payload
        return StoredObjectStat(size_bytes=len(payload), checksum=compute_checksum(payload))

    def get_object(self, location: ObjectStoreLocation) -> bytes:
        try:
            return self._objects[(location.bucket, location.key)]
        except KeyError as exc:
            raise ObjectNotFoundError(f"{location.bucket}/{location.key}") from exc

    def stat_object(self, location: ObjectStoreLocation) -> StoredObjectStat | None:
        payload = self._objects.get((location.bucket, location.key))
        if payload is None:
            return None
        return StoredObjectStat(size_bytes=len(payload), checksum=compute_checksum(payload))

    def delete_object(self, location: ObjectStoreLocation) -> None:
        self._objects.pop((location.bucket, location.key), None)

    def presign_get_url(self, location: ObjectStoreLocation, *, expires_in: int) -> str:
        """Unsupported: the in-memory store has no externally reachable URL."""
        raise PresignNotSupportedError(
            "LocalObjectStore cannot mint presigned URLs; use an S3 backend"
        )
