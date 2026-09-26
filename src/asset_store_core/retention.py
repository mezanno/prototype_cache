"""Retention defaults and read eligibility (FR-002/060/069, ADR-020)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

from asset_store_core.errors import (
    AssetDeletedError,
    AssetExpiredError,
    CapacityExceededError,
    InvalidStateTransitionError,
    ValidationError,
)
from asset_store_core.models import Asset, AssetState
from asset_store_core.paths import STORAGE_BUCKETS


def expiry_for(space: str, ttl_seconds: int | None, now: datetime) -> datetime | None:
    """One asset deadline shared by aliases; tmp/results have bounded defaults."""
    maximum: int | None = None
    if space == "tmp":
        maximum = 7 * 86400
        ttl_seconds = 86400 if ttl_seconds is None else ttl_seconds
    elif space == "results":
        maximum = int(os.environ.get("ASSET_STORE_RESULTS_MAX_TTL_SECONDS", 365 * 86400))
        if maximum <= 0:
            raise ValidationError("results maximum TTL must be positive")
        ttl_seconds = maximum if ttl_seconds is None else ttl_seconds
    if ttl_seconds is None:
        return None
    if ttl_seconds <= 0 or (maximum is not None and ttl_seconds > maximum):
        raise ValidationError("ttl_seconds must be positive and within the bucket maximum")
    try:
        return now + timedelta(seconds=ttl_seconds)
    except OverflowError as exc:
        raise ValidationError("ttl_seconds is too large") from exc


def require_live(asset: Asset, now: datetime) -> None:
    """Deny expired/deleted reads without mutating lifecycle on lookup."""
    if asset.state is AssetState.DELETED:
        raise AssetDeletedError("asset has been deleted")
    if asset.state is AssetState.EXPIRED or (
        asset.state is AssetState.AVAILABLE
        and asset.expires_at is not None
        and asset.expires_at <= now
    ):
        raise AssetExpiredError("asset has expired")


def validate_cleanup_transition(asset: Asset, state: AssetState, payload_deleted: bool) -> None:
    """Only maintenance transitions are allowed; a purge requires a durable fence."""
    allowed = (
        state is AssetState.EXPIRED and asset.state is AssetState.AVAILABLE and not payload_deleted
    ) or (
        state is AssetState.DELETED
        and asset.state in {AssetState.PENDING, AssetState.EXPIRED, AssetState.DELETED}
        and (not payload_deleted or asset.state is AssetState.DELETED)
    )
    if not allowed or asset.payload_deleted_at is not None:
        raise InvalidStateTransitionError("invalid maintenance lifecycle transition")


def capacity_limits() -> dict[str, int]:
    """Explicit byte budgets for FR-064; unset means no physical capacity gate."""
    try:
        values = json.loads(os.environ.get("ASSET_STORE_CAPACITY_BYTES", "{}"))
        if not isinstance(values, dict) or any(
            key not in STORAGE_BUCKETS or type(value) is not int or value <= 0
            for key, value in values.items()
        ):
            raise ValueError
    except (ValueError, TypeError) as exc:
        raise ValidationError(
            "ASSET_STORE_CAPACITY_BYTES must map buckets to positive bytes"
        ) from exc
    return dict(values)


def enforce_capacity(space: str, prospective_bytes: int) -> None:
    """Separate physical-capacity 503 from logical quota 413 (FR-064/068)."""
    limit = capacity_limits().get(space)
    if limit is None:
        return
    ratio = float(os.environ.get("ASSET_STORE_CAPACITY_HARD_RATIO", "0.95"))
    if not 0 < ratio <= 1:
        raise ValidationError("capacity hard ratio must be in (0, 1]")
    if prospective_bytes >= limit * ratio:
        raise CapacityExceededError("bucket physical capacity hard ceiling reached")
