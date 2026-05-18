"""Canonical alias path rules shared by registry and capability checks.

Aliases are ``space`` + relative ``alias`` path segments. We normalize leading and
trailing slashes and reject empty segments and ``..`` (path traversal).

See ``FR-001`` / ``FR-012`` (prefix scoping assumes stable string keys).
"""

from __future__ import annotations

from asset_store_core.errors import ValidationError


def normalize_space(space: str) -> str:
    """Return stripped tenant namespace with no slashes."""

    s = space.strip().strip("/")
    if not s:
        raise ValidationError("space must be non-empty")
    if "/" in s:
        raise ValidationError(f"space must not contain '/': {space!r}")
    if s in {".", ".."}:
        raise ValidationError(f"invalid space: {space!r}")
    return s


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
    """Return ``{space}/{relative_alias}`` used as the registry key and guard scope."""

    return f"{normalize_space(space)}/{normalize_relative_alias(alias)}"
