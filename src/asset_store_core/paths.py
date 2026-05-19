"""Canonical alias path rules shared by registry and capability checks.

Qualified aliases are ``{bucket}/{partition_id}/…`` where ``bucket`` is the registry
``space`` field (``cache``, ``tmp``, ``users``, ``results``).

See ``FR-001`` / ``FR-012`` (prefix scoping assumes stable string keys).
"""

from __future__ import annotations

from asset_store_core.errors import ValidationError

STORAGE_BUCKETS: frozenset[str] = frozenset({"cache", "tmp", "users", "results"})


def normalize_bucket(bucket: str) -> str:
    """Validate and return a storage bucket name (registry ``space`` field)."""

    name = bucket.strip().strip("/")
    if not name:
        raise ValidationError("bucket must be non-empty")
    if "/" in name:
        raise ValidationError(f"bucket must not contain '/': {bucket!r}")
    if name in {".", ".."}:
        raise ValidationError(f"invalid bucket: {bucket!r}")
    if name not in STORAGE_BUCKETS:
        raise ValidationError(
            f"unknown bucket {name!r}; expected one of {sorted(STORAGE_BUCKETS)}"
        )
    return name


def normalize_space(space: str) -> str:
    """Return a storage bucket name (alias for :func:`normalize_bucket`)."""

    return normalize_bucket(space)


def normalize_partition_id(partition_id: str) -> str:
    """Return a partition id (mirror id, user id, task id, tmp id, …)."""

    return normalize_relative_alias(partition_id)


def normalize_relative_alias(alias: str) -> str:
    """Return a relative alias path with normalized slashes."""

    a = alias.strip().strip("/")
    if not a:
        raise ValidationError("alias path must be non-empty")
    parts = a.split("/")
    for part in parts:
        if part == "" or part == "." or part == "..":
            raise ValidationError(f"invalid alias path segment in {alias!r}")
    return a


def qualified_alias(space: str, alias: str) -> str:
    """Return ``{bucket}/{path}`` used as the registry key and guard scope."""

    return f"{normalize_space(space)}/{normalize_relative_alias(alias)}"


def qualified_alias_for_partition(
    space: str,
    partition_id: str,
    relative_alias: str,
) -> str:
    """Return qualified alias for an asset under ``partition_id``."""

    scoped = (
        f"{normalize_partition_id(partition_id)}/{normalize_relative_alias(relative_alias)}"
    )
    return qualified_alias(space, scoped)
