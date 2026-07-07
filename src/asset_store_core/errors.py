"""Domain errors for asset-store core invariants.

Each exception type maps cleanly to HTTP semantics when adapters wrap this layer:

- ``AliasNotFoundError`` → 404
- ``AssetNotFoundError`` → 404
- ``ObjectNotFoundError`` → 404
- ``AliasConflictError`` → 409
- ``AliasImmutableError`` → 409
- ``ChecksumMismatchError`` → 409 (FR-022)
- ``ValidationError`` → 400
- ``InvalidStateTransitionError`` → 409 or 410 depending on adapter policy
- ``ServiceAuthError`` → 401
- ``CapabilityDeniedError`` / ``CapabilityAlreadyConsumedError`` → 403
- ``PresignNotSupportedError`` → 501
"""


class AssetStoreError(Exception):
    """Base class for expected domain errors."""


class ServiceAuthError(AssetStoreError):
    """Raised when a calling service fails static-credential authentication (FR-014)."""


class ValidationError(AssetStoreError):
    """Raised when inputs violate structural rules (empty alias, bad path, etc.)."""


class AliasConflictError(AssetStoreError):
    """Raised when an alias name is already reserved, bound, or in grace tombstone."""


class AliasNotFoundError(AssetStoreError):
    """Raised when an alias is unknown."""


class AliasImmutableError(AssetStoreError):
    """Raised when attempting to rebind or mutate-alias an immutable binding."""


class AssetNotFoundError(AssetStoreError):
    """Raised when an asset id is unknown."""


class ObjectNotFoundError(AssetStoreError):
    """Raised when object-store bytes are missing for a given location."""


class PresignNotSupportedError(AssetStoreError):
    """Raised when the active object-store backend cannot mint presigned URLs.

    The in-memory :class:`~asset_store_core.object_store.LocalObjectStore` has no
    externally reachable URL, so presigned reads are only available on an
    S3-compatible backend (ADR-003 presigned mode).
    """


class ChecksumMismatchError(AssetStoreError):
    """Raised when caller-supplied checksum disagrees with committed payload (FR-022)."""


class CapabilityDeniedError(AssetStoreError):
    """Raised when a capability does not authorize an operation."""


class CapabilityAlreadyConsumedError(AssetStoreError):
    """Raised when a single-use capability is reused (FR-013)."""


class InvalidStateTransitionError(AssetStoreError):
    """Raised when an asset lifecycle transition is not allowed."""


class QuotaExceededError(AssetStoreError):
    """Raised when a commit would exceed a partition or bucket quota (FR-066/FR-068).

    ``scope`` is ``"partition"`` or ``"bucket"`` to tell the caller which limit was
    hit, mirroring the distinct ``413`` responses in the spec.
    """

    def __init__(self, message: str, *, scope: str) -> None:
        super().__init__(message)
        self.scope = scope
