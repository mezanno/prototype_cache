"""Domain errors for asset-store core invariants.

Each exception type maps cleanly to HTTP semantics when adapters wrap this layer:

- ``AliasNotFoundError`` → 404
- ``AssetNotFoundError`` → 404
- ``AliasConflictError`` → 409
- ``AliasImmutableError`` → 409
- ``ChecksumMismatchError`` → 409 (FR-022)
- ``ValidationError`` → 400
- ``InvalidStateTransitionError`` → 409 or 410 depending on adapter policy
- ``CapabilityDeniedError`` / ``CapabilityAlreadyConsumedError`` → 403
"""


class AssetStoreError(Exception):
    """Base class for expected domain errors."""


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


class ChecksumMismatchError(AssetStoreError):
    """Raised when caller-supplied checksum disagrees with committed payload (FR-022)."""


class CapabilityDeniedError(AssetStoreError):
    """Raised when a capability does not authorize an operation."""


class CapabilityAlreadyConsumedError(AssetStoreError):
    """Raised when a single-use capability is reused (FR-013)."""


class InvalidStateTransitionError(AssetStoreError):
    """Raised when an asset lifecycle transition is not allowed."""
