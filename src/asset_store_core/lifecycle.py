"""Dry-run-first maintenance worker (B-014, FR-060/064/067, ADR-020).

Run with ``python -m asset_store_core.lifecycle --help``. No mutations occur
unless --apply is explicit. Postgres owns concurrency; S3 delete is idempotent.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from prometheus_client import CollectorRegistry, Counter, Gauge, write_to_textfile
from pydantic import BaseModel, ConfigDict, Field, model_validator

from asset_store_core.models import Asset, AssetState, EvictionPolicy, utcnow
from asset_store_core.object_store import ObjectStoreBackend
from asset_store_core.paths import STORAGE_BUCKETS
from asset_store_core.registry_base import AssetRegistry
from asset_store_core.retention import capacity_limits
from asset_store_core.storage import ObjectStoreLocation


class SweepPolicy(BaseModel):
    """Operator-configurable thresholds; capacity budgets shared with API env."""

    model_config = ConfigDict(extra="forbid")
    pending_seconds: int = Field(default=86400, gt=0)
    grace_seconds: dict[str, int] = Field(
        default_factory=lambda: {
            "cache": 7 * 86400,
            "tmp": 86400,
            "users": 7 * 86400,
            "results": 7 * 86400,
        }
    )
    capacity_bytes: dict[str, int] = Field(default_factory=capacity_limits)
    pressure_trigger: float = Field(default=0.90, gt=0, le=1)
    pressure_target: float = Field(default=0.70, ge=0, lt=1)
    quota_trigger: float = Field(default=0.90, gt=0, le=1)
    quota_target: float = Field(default=0.75, ge=0, lt=1)

    @model_validator(mode="after")
    def validate_policy(self) -> SweepPolicy:
        if set(self.grace_seconds) != STORAGE_BUCKETS or any(
            v < 0 for v in self.grace_seconds.values()
        ):
            raise ValueError("grace_seconds must contain all four buckets with nonnegative values")
        if any(k not in STORAGE_BUCKETS or v <= 0 for k, v in self.capacity_bytes.items()):
            raise ValueError("capacity_bytes must map buckets to positive values")
        if self.pressure_target >= self.pressure_trigger or self.quota_target >= self.quota_trigger:
            raise ValueError("low-water targets must be below their triggers")
        return self


@dataclass(frozen=True)
class Action:
    """Snapshot-rechecked lifecycle intent, not authorization to delete blindly."""

    asset: Asset
    state: AssetState
    reason: str
    purge: bool = False


@dataclass
class SweepReport:
    dry_run: bool
    candidates: int = 0
    applied: int = 0
    skipped: int = 0
    errors: int = 0
    exhausted: tuple[str, ...] = ()


class SweepMetrics:
    """Per-process Prometheus metrics, exportable via a node-exporter textfile."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.evicted = Counter(
            "gc_evicted_total",
            "Applied lifecycle actions.",
            ["space", "reason"],
            registry=self.registry,
        )
        self.exhausted = Gauge(
            "gc_eviction_exhausted",
            "Sweep cannot reach projected low water.",
            ["space"],
            registry=self.registry,
        )
        self.errors = Counter(
            "gc_errors_total", "Failed maintenance actions.", ["space"], registry=self.registry
        )
        self.used_ratio = Gauge(
            "storage_space_used_ratio",
            "Estimated physical occupancy ratio.",
            ["space"],
            registry=self.registry,
        )


def _score(asset: Asset, now: datetime) -> tuple[float, str]:
    age = max(0.0, (now - (asset.last_read_at or asset.created_at)).total_seconds()) / 86400
    return (age * (asset.size_bytes or 0), asset.asset_id)


def plan_sweep(
    registry: AssetRegistry, policy: SweepPolicy, now: datetime
) -> tuple[list[Action], set[str], dict[str, float]]:
    """Pure selection: TTL/orphans first, quota then pressure; never alter registry."""
    assets = registry.list_assets()
    actions: list[Action] = []
    selected: set[str] = set()
    purged: set[str] = set()
    exhausted: set[str] = set()
    ratios: dict[str, float] = {}
    by_space: dict[str, list[Asset]] = defaultdict(list)
    by_partition: dict[tuple[str, str], list[Asset]] = defaultdict(list)
    for asset in assets:
        by_space[asset.space].append(asset)
        by_partition[(asset.space, asset.partition_id)].append(asset)
    for asset in sorted(assets, key=lambda a: a.asset_id):
        age = (now - asset.created_at).total_seconds()
        action: Action | None = None
        if asset.state is AssetState.PENDING and age >= policy.pending_seconds:
            action = Action(asset, AssetState.DELETED, "orphan", True)
        elif (
            asset.state is AssetState.AVAILABLE
            and asset.expires_at is not None
            and asset.expires_at <= now
        ):
            action = Action(asset, AssetState.EXPIRED, "ttl_expired")
        elif asset.state is AssetState.EXPIRED:
            expired_at = asset.expired_at or asset.updated_at
            if (now - expired_at).total_seconds() >= policy.grace_seconds[asset.space]:
                action = Action(asset, AssetState.DELETED, "ttl_expired", True)
        elif asset.state is AssetState.DELETED and asset.payload_deleted_at is None:
            action = Action(asset, AssetState.DELETED, "orphan", True)
        if action is not None:
            actions.append(action)
            selected.add(asset.asset_id)
            if action.purge:
                purged.add(asset.asset_id)

    def available(group: list[Asset]) -> list[Asset]:
        return [a for a in group if a.state is AssetState.AVAILABLE and a.asset_id not in selected]

    def evict(group: list[Asset], target: float, reason: str, space: str) -> None:
        remaining = sum(a.size_bytes or 0 for a in available(group))
        candidates = sorted(
            (a for a in available(group) if a.eviction_policy is EvictionPolicy.INHERIT),
            key=lambda a: _score(a, now),
            reverse=True,
        )
        for asset in candidates:
            if remaining <= target:
                break
            actions.append(Action(asset, AssetState.EXPIRED, reason))
            selected.add(asset.asset_id)
            remaining -= asset.size_bytes or 0
        if remaining > target:
            exhausted.add(space)

    partitions = sorted(key for key in by_partition if key[0] in {"cache", "tmp"})
    for space, partition in partitions:
        quota = registry.get_partition_quota(space=space, partition_id=partition)
        if not quota.eviction_sweep_enabled or quota.quota_bytes is None:
            continue
        group = by_partition[(space, partition)]
        used = sum(a.size_bytes or 0 for a in available(group))
        if used > 0 and used >= quota.quota_bytes * policy.quota_trigger:
            evict(group, quota.quota_bytes * policy.quota_target, "quota_lfu", space)

    for space, capacity in sorted(policy.capacity_bytes.items()):
        group = by_space[space]
        physical = sum(a.size_bytes or 0 for a in group if a.payload_deleted_at is None)
        ratios[space] = physical / capacity
        projected_physical = sum(a.size_bytes or 0 for a in group if a.asset_id not in purged)
        if space in {"cache", "tmp"} and projected_physical >= capacity * policy.pressure_trigger:
            evict(group, capacity * policy.pressure_target, "pressure_lfu", space)
    return actions, exhausted, ratios


def run_sweep(
    registry: AssetRegistry,
    store: ObjectStoreBackend,
    *,
    policy: SweepPolicy | None = None,
    dry_run: bool = True,
    now: datetime | None = None,
    metrics: SweepMetrics | None = None,
) -> SweepReport:
    """Plan and optionally apply locked, retryable maintenance (FR-060/064/067)."""
    policy = policy or SweepPolicy()
    now = now or utcnow()
    metrics = metrics or SweepMetrics()
    actions, exhausted, ratios = plan_sweep(registry, policy, now)
    report = SweepReport(
        dry_run=dry_run, candidates=len(actions), exhausted=tuple(sorted(exhausted))
    )
    logger = logging.getLogger("asset_store")
    for space in STORAGE_BUCKETS:
        metrics.exhausted.labels(space).set(int(space in exhausted))
    for space, ratio in ratios.items():
        metrics.used_ratio.labels(space).set(ratio)
    for action in actions:
        asset = action.asset
        logger.info(
            "GC %s asset=%s reason=%s",
            "candidate" if dry_run else "attempt",
            asset.asset_id,
            action.reason,
            extra={"event": "gc.candidate", "space": asset.space},
        )
        if dry_run:
            continue
        try:
            with registry.asset_lock(asset.asset_id) as current:
                if current != asset:
                    report.skipped += 1
                    continue
                if action.reason == "quota_lfu":
                    quota = registry.get_partition_quota(
                        space=asset.space, partition_id=asset.partition_id
                    )
                    if (
                        not quota.eviction_sweep_enabled
                        or quota.quota_bytes is None
                        or quota.used_bytes <= quota.quota_bytes * policy.quota_target
                    ):
                        report.skipped += 1
                        continue
                if action.reason == "pressure_lfu":
                    usage = registry.get_bucket_quota(space=asset.space).used_bytes
                    if usage <= policy.capacity_bytes[asset.space] * policy.pressure_target:
                        report.skipped += 1
                        continue
                if not action.purge or current.state is not AssetState.DELETED:
                    registry.lifecycle_update(
                        current, state=action.state, now=now, reason=action.reason
                    )
            if action.purge:
                # Commit the terminal state BEFORE deleting bytes: a crash must
                # never restore a pending reservation whose object was removed.
                with registry.asset_lock(asset.asset_id) as fenced:
                    if fenced.payload_deleted_at is not None:
                        report.skipped += 1
                        continue
                    if fenced.state is not AssetState.DELETED:
                        raise RuntimeError("cleanup asset is not fenced")
                    store.delete_object(
                        ObjectStoreLocation(bucket=fenced.space, key=fenced.storage_key)
                    )
                    registry.lifecycle_update(
                        fenced,
                        state=AssetState.DELETED,
                        now=now,
                        reason=action.reason,
                        payload_deleted=True,
                    )
            report.applied += 1
            metrics.evicted.labels(asset.space, action.reason).inc()
            logger.info(
                "GC applied asset=%s reason=%s",
                asset.asset_id,
                action.reason,
                extra={"event": "gc.applied", "space": asset.space},
            )
        except Exception:
            # Storage adapters have different exception types; retain candidates for retry.
            report.errors += 1
            metrics.errors.labels(asset.space).inc()
            logger.error(
                "GC failed asset=%s; retry next pass",
                asset.asset_id,
                extra={"event": "gc.error", "space": asset.space},
            )
    return report


def main() -> None:
    """Run against configured durable adapters; apply requires an explicit flag."""
    from dataclasses import asdict

    from asset_store_core.api.observability import configure_logging
    from asset_store_core.pg_registry import PostgresAssetRegistry
    from asset_store_core.s3_object_store import S3ObjectStore

    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    parser.add_argument("--config", type=Path, help="SweepPolicy JSON file")
    parser.add_argument("--interval", type=float, default=0, help="Repeat seconds; 0 runs once")
    parser.add_argument("--metrics-file", type=Path)
    args = parser.parse_args()
    if args.interval < 0 or not float(args.interval) < float("inf"):
        parser.error("interval must be finite and nonnegative")
    configure_logging()
    policy = (
        SweepPolicy.model_validate_json(args.config.read_text()) if args.config else SweepPolicy()
    )
    store = S3ObjectStore(
        endpoint_url=os.environ["ASSET_STORE_S3_ENDPOINT"],
        region=os.environ.get("ASSET_STORE_S3_REGION", "garage"),
        access_key=os.environ["ASSET_STORE_S3_ACCESS_KEY"],
        secret_key=os.environ["ASSET_STORE_S3_SECRET_KEY"],
    )
    metrics = SweepMetrics()
    with PostgresAssetRegistry.connect(
        os.environ["ASSET_STORE_PG_DSN"], bootstrap_schema=False
    ) as registry:
        while True:
            report = run_sweep(
                registry, store, policy=policy, dry_run=not args.apply, metrics=metrics
            )
            print(json.dumps(asdict(report)), flush=True)
            if args.metrics_file:
                write_to_textfile(str(args.metrics_file), metrics.registry)
            if not args.interval:
                raise SystemExit(1 if report.errors else 0)
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
