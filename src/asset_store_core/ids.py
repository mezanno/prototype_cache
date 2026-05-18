"""Opaque asset identifiers (ADR-004).

Prefer ``uuid.uuid7()`` when the interpreter provides it (Python 3.13+); otherwise
fall back to ``uuid4`` with no time-ordering guarantee. Both are valid opaque ids.
"""

from __future__ import annotations

import uuid


def new_asset_id() -> str:
    """Return a new opaque asset identifier string."""

    factory = getattr(uuid, "uuid7", None)
    if callable(factory):
        return str(factory())
    return str(uuid.uuid4())
