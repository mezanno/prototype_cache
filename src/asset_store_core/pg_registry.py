"""Postgres-backed asset registry (B-009, ADR-001 control plane).

A durable implementation of the full :class:`~asset_store_core.registry_base.AssetRegistry`
surface, at behavioural parity with the in-memory reference registry
(:class:`~asset_store_core.registry.InMemoryAssetRegistry`): reserve, commit,
resolve, annotations, expire/delete, immutable/mutable alias detach + rebind,
per-asset eviction policy, and the two-tier partition/bucket quotas with
commit-time ceilings and usage accounting. Every mutation records the same audit
actions as the in-memory registry, written transactionally with the change.

Returns the same domain :class:`~asset_store_core.models.Asset` objects so the
:class:`~asset_store_core.guard.StorageGuard` facade and HTTP adapters are
backend-agnostic.

The schema is owned by the Alembic migration history under ``migrations/`` (run
``alembic upgrade head`` against ``ASSET_STORE_PG_DSN``). For convenience the
registry can also bootstrap the same tables with ``CREATE TABLE IF NOT EXISTS``
on connect (``bootstrap_schema=True``, the default) — handy for tests and local
dev; production should provision via migrations and pass ``bootstrap_schema=False``.
``psycopg`` (v3) and ``alembic`` are optional dependencies; install the ``pg``
extra (``pip install asset-store-prototype[pg]``). Like the in-memory registry,
an instance is **not** thread-safe: it holds a single connection and serialises
operations per transaction.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from asset_store_core.errors import (
    AliasConflictError,
    AliasImmutableError,
    AliasNotFoundError,
    AssetNotFoundError,
    ChecksumMismatchError,
    InvalidStateTransitionError,
    QuotaExceededError,
    ValidationError,
)
from asset_store_core.ids import new_asset_id
from asset_store_core.models import (
    AliasBinding,
    Asset,
    AssetState,
    AuditEvent,
    BucketQuota,
    EvictionPolicy,
    PartitionQuota,
    utcnow,
)
from asset_store_core.paths import normalize_relative_alias, normalize_space
from asset_store_core.registry import (
    _alias_under_partition,
    _normalize_alias_specs,
    _partition_from_scoped_alias,
)
from asset_store_core.storage import build_storage_key, normalize_partition_id

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
except ImportError as exc:  # pragma: no cover - exercised only without the pg extra
    raise ImportError(
        "PostgresAssetRegistry requires psycopg; install the 'pg' extra: pip install "
        "asset-store-prototype[pg]"
    ) from exc

if TYPE_CHECKING:
    from psycopg import Connection

# Partition commits are rejected once prospective usage reaches 105% of the byte
# quota; the 5% band absorbs concurrent in-flight uploads (FR-066, ADR-009).
_PARTITION_HARD_RATIO = 1.05

# Spaces whose partitions enable quota-triggered eviction sweeps by default (FR-067).
_SWEEP_DEFAULT_SPACES = frozenset({"cache", "tmp"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS assets (
    asset_id          text PRIMARY KEY,
    space             text NOT NULL,
    partition_id      text NOT NULL,
    storage_key       text NOT NULL,
    state             text NOT NULL,
    mime              text,
    size_bytes        bigint,
    checksum_algo     text NOT NULL DEFAULT 'sha256',
    checksum          text,
    annotations       jsonb NOT NULL DEFAULT '{}'::jsonb,
    eviction_policy   text NOT NULL DEFAULT 'inherit',
    owner_service_id  text NOT NULL DEFAULT 'system',
    created_at        timestamptz NOT NULL,
    updated_at        timestamptz NOT NULL,
    expires_at        timestamptz
);

CREATE TABLE IF NOT EXISTS aliases (
    space                 text NOT NULL,
    alias                 text NOT NULL,
    asset_id              text REFERENCES assets(asset_id),
    mutable               boolean NOT NULL DEFAULT false,
    previous_asset_id     text,
    created_at            timestamptz NOT NULL,
    updated_at            timestamptz NOT NULL,
    created_by_service_id text NOT NULL DEFAULT 'system',
    PRIMARY KEY (space, alias)
);

CREATE INDEX IF NOT EXISTS aliases_asset_id_idx ON aliases (asset_id);

CREATE TABLE IF NOT EXISTS alias_tombstones (
    space       text NOT NULL,
    alias       text NOT NULL,
    grace_until timestamptz NOT NULL,
    PRIMARY KEY (space, alias)
);

CREATE TABLE IF NOT EXISTS partition_quotas (
    space                  text NOT NULL,
    partition_id           text NOT NULL,
    quota_bytes            bigint,
    quota_asset_count      bigint,
    used_bytes             bigint NOT NULL DEFAULT 0,
    used_asset_count       bigint NOT NULL DEFAULT 0,
    eviction_sweep_enabled boolean NOT NULL DEFAULT false,
    PRIMARY KEY (space, partition_id)
);

CREATE TABLE IF NOT EXISTS bucket_quotas (
    space          text PRIMARY KEY,
    quota_bytes    bigint,
    used_bytes     bigint NOT NULL DEFAULT 0,
    warn_threshold double precision NOT NULL DEFAULT 0.80,
    hard_ceiling   double precision NOT NULL DEFAULT 1.00
);

CREATE TABLE IF NOT EXISTS audit_events (
    id                bigserial PRIMARY KEY,
    action            text NOT NULL,
    target            text NOT NULL,
    caller_service_id text NOT NULL,
    outcome           text NOT NULL,
    before            jsonb NOT NULL DEFAULT '{}'::jsonb,
    after             jsonb NOT NULL DEFAULT '{}'::jsonb,
    ts                timestamptz NOT NULL
);
"""


class PostgresAssetRegistry:
    """Durable, full-surface asset registry over Postgres (B-009)."""

    __slots__ = ("_alias_grace", "_conn")

    def __init__(
        self,
        connection: Connection[Any],
        *,
        bootstrap_schema: bool = True,
        alias_name_grace_period: timedelta | None = None,
    ) -> None:
        self._conn = connection
        # Autocommit + explicit ``transaction()`` blocks is the recommended psycopg-3
        # pattern: standalone reads commit immediately, so each multi-statement op
        # below opens a real top-level transaction rather than a savepoint nested in
        # a stray read transaction.
        self._conn.autocommit = True
        if alias_name_grace_period is None:
            self._alias_grace = timedelta(days=7)
        elif alias_name_grace_period < timedelta(0):
            raise ValidationError("alias_name_grace_period must not be negative")
        else:
            self._alias_grace = alias_name_grace_period
        if bootstrap_schema:
            with self._conn.transaction():
                self._conn.execute(_SCHEMA)

    @classmethod
    def connect(
        cls,
        dsn: str,
        *,
        bootstrap_schema: bool = True,
        alias_name_grace_period: timedelta | None = None,
    ) -> PostgresAssetRegistry:
        """Open a new connection from ``dsn`` and return a registry."""

        connection = psycopg.connect(dsn, row_factory=dict_row)
        return cls(
            connection,
            bootstrap_schema=bootstrap_schema,
            alias_name_grace_period=alias_name_grace_period,
        )

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> PostgresAssetRegistry:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ writes

    def reserve_asset(
        self,
        *,
        space: str,
        partition_id: str,
        aliases: Iterable[str] | Mapping[str, bool],
        owner_service_id: str,
        mime: str | None = None,
        annotations: Mapping[str, str] | None = None,
        eviction_policy: EvictionPolicy = EvictionPolicy.INHERIT,
    ) -> Asset:
        """Reserve aliases and create a pending asset shell (FR-001/FR-004)."""

        norm_space = normalize_space(space)
        norm_partition = normalize_partition_id(partition_id)
        specs = _normalize_alias_specs(aliases)
        scoped = {name: _alias_under_partition(norm_partition, name) for name in specs}

        asset_id = new_asset_id()
        now = utcnow()
        storage_key = build_storage_key(partition_id=norm_partition, asset_id=asset_id)
        annotation_map = dict(annotations or {})

        with self._conn.transaction():
            for scoped_alias in scoped.values():
                self._require_alias_name_available(norm_space, scoped_alias)

            self._conn.execute(
                """
                INSERT INTO assets (
                    asset_id, space, partition_id, storage_key, state, mime,
                    annotations, eviction_policy, owner_service_id, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    asset_id,
                    norm_space,
                    norm_partition,
                    storage_key,
                    AssetState.PENDING.value,
                    mime,
                    Jsonb(annotation_map),
                    eviction_policy.value,
                    owner_service_id,
                    now,
                    now,
                ),
            )

            for name, scoped_alias in scoped.items():
                mutable = specs[name]
                self._conn.execute(
                    """
                    INSERT INTO aliases (
                        space, alias, asset_id, mutable, created_at, updated_at,
                        created_by_service_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (norm_space, scoped_alias, asset_id, mutable, now, now, owner_service_id),
                )
                self._write_audit(
                    action="alias.create",
                    target=f"{norm_space}/{scoped_alias}",
                    caller_service_id=owner_service_id,
                    after={"asset_id": asset_id, "mutable": str(mutable).lower()},
                )

        return self._load_asset(asset_id)

    def commit_asset(
        self,
        *,
        asset_id: str,
        size_bytes: int,
        checksum: str,
        caller_service_id: str,
        mime: str | None = None,
        expected_checksum: str | None = None,
    ) -> Asset:
        """Transition ``pending`` → ``available`` after payload commit (FR-022)."""

        if size_bytes < 0:
            raise ValidationError("size_bytes must be >= 0")
        server_checksum = checksum.strip()
        if not server_checksum:
            raise ValidationError("checksum must be non-empty")
        if expected_checksum is not None and expected_checksum != server_checksum:
            raise ChecksumMismatchError(
                f"checksum mismatch: expected {expected_checksum!r}, got {server_checksum!r}"
            )

        now = utcnow()
        with self._conn.transaction():
            row = self._conn.execute(
                "SELECT state, mime, space, partition_id FROM assets "
                "WHERE asset_id = %s FOR UPDATE",
                (asset_id,),
            ).fetchone()
            if row is None:
                raise AssetNotFoundError(asset_id)
            if row["state"] != AssetState.PENDING.value:
                raise InvalidStateTransitionError(
                    f"asset {asset_id!r} cannot be committed from state {row['state']!r}"
                )

            self._enforce_quota(
                space=row["space"], partition_id=row["partition_id"], new_bytes=size_bytes
            )

            self._conn.execute(
                """
                UPDATE assets
                   SET state = %s, size_bytes = %s, checksum = %s, mime = %s, updated_at = %s
                 WHERE asset_id = %s
                """,
                (
                    AssetState.AVAILABLE.value,
                    size_bytes,
                    server_checksum,
                    mime or row["mime"],
                    now,
                    asset_id,
                ),
            )
            self._acquire_quota(
                space=row["space"], partition_id=row["partition_id"], nbytes=size_bytes
            )
            self._write_audit(
                action="asset.commit",
                target=asset_id,
                caller_service_id=caller_service_id,
                before={"state": AssetState.PENDING.value},
                after={"state": AssetState.AVAILABLE.value},
            )

        return self._load_asset(asset_id)

    def update_annotations(
        self,
        *,
        asset_id: str,
        patch: Mapping[str, str],
        caller_service_id: str,
        overwrite: bool = False,
    ) -> Asset:
        """Merge or replace the annotation map (FR-005)."""

        now = utcnow()
        with self._conn.transaction():
            row = self._conn.execute(
                "SELECT state, annotations FROM assets WHERE asset_id = %s FOR UPDATE",
                (asset_id,),
            ).fetchone()
            if row is None:
                raise AssetNotFoundError(asset_id)
            if row["state"] == AssetState.DELETED.value:
                raise InvalidStateTransitionError(
                    f"cannot update annotations on deleted asset {asset_id!r}"
                )

            before = dict(row["annotations"])
            merged = dict(patch) if overwrite else {**before, **patch}
            self._conn.execute(
                "UPDATE assets SET annotations = %s, updated_at = %s WHERE asset_id = %s",
                (Jsonb(merged), now, asset_id),
            )
            self._write_audit(
                action="asset.annotations_update",
                target=asset_id,
                caller_service_id=caller_service_id,
                before=before,
                after=merged,
            )

        return self._load_asset(asset_id)

    def expire_asset(self, *, asset_id: str, caller_service_id: str) -> Asset:
        """Transition ``available`` → ``expired`` (FR-006)."""

        return self._transition_out_of_available(
            asset_id=asset_id,
            caller_service_id=caller_service_id,
            allowed_from=(AssetState.AVAILABLE,),
            new_state=AssetState.EXPIRED,
            action="asset.expire",
            verb="expire",
        )

    def delete_asset(self, *, asset_id: str, caller_service_id: str) -> Asset:
        """Transition to ``deleted`` from ``available`` or ``expired`` (FR-007)."""

        return self._transition_out_of_available(
            asset_id=asset_id,
            caller_service_id=caller_service_id,
            allowed_from=(AssetState.AVAILABLE, AssetState.EXPIRED),
            new_state=AssetState.DELETED,
            action="asset.delete",
            verb="delete",
        )

    def set_eviction_policy(
        self,
        *,
        asset_id: str,
        eviction_policy: EvictionPolicy,
        caller_service_id: str,
    ) -> Asset:
        """Set an asset's eviction policy and audit the change (FR-063)."""

        now = utcnow()
        with self._conn.transaction():
            row = self._conn.execute(
                "SELECT state, eviction_policy FROM assets WHERE asset_id = %s FOR UPDATE",
                (asset_id,),
            ).fetchone()
            if row is None:
                raise AssetNotFoundError(asset_id)
            if row["state"] == AssetState.DELETED.value:
                raise InvalidStateTransitionError(
                    f"cannot set eviction policy on deleted asset {asset_id!r}"
                )

            self._conn.execute(
                "UPDATE assets SET eviction_policy = %s, updated_at = %s WHERE asset_id = %s",
                (eviction_policy.value, now, asset_id),
            )
            self._write_audit(
                action="asset.eviction_policy_set",
                target=asset_id,
                caller_service_id=caller_service_id,
                before={"eviction_policy": row["eviction_policy"]},
                after={"eviction_policy": eviction_policy.value},
            )

        return self._load_asset(asset_id)

    # ----------------------------------------------------------------- aliases

    def detach_alias(self, *, space: str, alias: str, caller_service_id: str) -> None:
        """Detach an **immutable** alias with tombstone grace (FR-003)."""

        norm_space = normalize_space(space)
        norm_alias = normalize_relative_alias(alias)
        with self._conn.transaction():
            binding = self._load_binding(norm_space, norm_alias)
            if binding.mutable:
                raise AliasImmutableError(
                    f"use detach_mutable_alias for mutable alias {binding.qualified_alias!r}"
                )
            asset_id = binding.asset_id
            if asset_id is None:
                raise InvalidStateTransitionError(f"alias {binding.qualified_alias!r} is not bound")

            self._conn.execute(
                "DELETE FROM aliases WHERE space = %s AND alias = %s", (norm_space, norm_alias)
            )
            if self._alias_grace > timedelta(0):
                self._conn.execute(
                    """
                    INSERT INTO alias_tombstones (space, alias, grace_until)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (space, alias) DO UPDATE SET grace_until = EXCLUDED.grace_until
                    """,
                    (norm_space, norm_alias, utcnow() + self._alias_grace),
                )
            self._write_audit(
                action="alias.detach",
                target=binding.qualified_alias,
                caller_service_id=caller_service_id,
                before={"asset_id": asset_id},
                after={},
            )
            self._mark_for_gc_if_orphaned(asset_id, caller_service_id)

    def detach_mutable_alias(
        self, *, space: str, alias: str, caller_service_id: str
    ) -> AliasBinding:
        """Detach a **mutable** alias in preparation for ``rebind_alias`` (FR-003)."""

        norm_space = normalize_space(space)
        norm_alias = normalize_relative_alias(alias)
        now = utcnow()
        with self._conn.transaction():
            binding = self._load_binding(norm_space, norm_alias)
            if not binding.mutable:
                raise AliasImmutableError(
                    f"use detach_alias for immutable alias {binding.qualified_alias!r}"
                )
            old_asset_id = binding.asset_id
            if old_asset_id is None:
                raise InvalidStateTransitionError(
                    f"mutable alias {binding.qualified_alias!r} is already detached"
                )

            self._conn.execute(
                """
                UPDATE aliases
                   SET asset_id = NULL, previous_asset_id = %s, updated_at = %s
                 WHERE space = %s AND alias = %s
                """,
                (old_asset_id, now, norm_space, norm_alias),
            )
            self._write_audit(
                action="alias.detach_mutable",
                target=binding.qualified_alias,
                caller_service_id=caller_service_id,
                before={"asset_id": old_asset_id},
                after={"asset_id": ""},
            )
            self._mark_for_gc_if_orphaned(old_asset_id, caller_service_id)

        return self._load_binding(norm_space, norm_alias)

    def rebind_alias(
        self, *, space: str, alias: str, new_asset_id: str, caller_service_id: str
    ) -> AliasBinding:
        """Rebind a **mutable** alias after ``detach_mutable_alias`` (FR-008)."""

        norm_space = normalize_space(space)
        norm_alias = normalize_relative_alias(alias)
        now = utcnow()
        with self._conn.transaction():
            binding = self._load_binding(norm_space, norm_alias)
            if not binding.mutable:
                raise AliasImmutableError(f"alias {binding.qualified_alias!r} is immutable")
            if binding.asset_id is not None:
                raise InvalidStateTransitionError(
                    f"mutable alias {binding.qualified_alias!r} must be detached before rebind"
                )

            new_asset = self._load_asset(new_asset_id)
            if new_asset.space != binding.space:
                raise AliasConflictError("cannot rebind an alias across buckets")
            if new_asset.partition_id != _partition_from_scoped_alias(binding.alias):
                raise AliasConflictError("cannot rebind an alias across partitions")
            if new_asset.state is not AssetState.AVAILABLE:
                raise InvalidStateTransitionError(
                    f"rebind target asset {new_asset_id!r} must be available, "
                    f"got {new_asset.state.value!r}"
                )

            previous_asset_id = binding.previous_asset_id or ""
            self._conn.execute(
                """
                UPDATE aliases
                   SET asset_id = %s, previous_asset_id = NULL, updated_at = %s
                 WHERE space = %s AND alias = %s
                """,
                (new_asset_id, now, norm_space, norm_alias),
            )
            self._write_audit(
                action="alias.rebind",
                target=binding.qualified_alias,
                caller_service_id=caller_service_id,
                before={"asset_id": previous_asset_id},
                after={"asset_id": new_asset_id},
            )

        return self._load_binding(norm_space, norm_alias)

    def resolve_alias(self, *, space: str, alias: str) -> Asset:
        """Resolve an alias to an ``available`` asset (FR-002)."""

        norm_space = normalize_space(space)
        norm_alias = normalize_relative_alias(alias)
        row = self._conn.execute(
            "SELECT asset_id FROM aliases WHERE space = %s AND alias = %s",
            (norm_space, norm_alias),
        ).fetchone()
        if row is None:
            raise AliasNotFoundError(f"{norm_space}/{norm_alias}")
        if row["asset_id"] is None:
            raise InvalidStateTransitionError(
                f"alias {norm_space}/{norm_alias!r} is detached pending rebind"
            )

        asset = self._load_asset(row["asset_id"])
        if not asset.is_resolvable:
            raise InvalidStateTransitionError(
                f"asset {asset.asset_id!r} is not resolvable in state {asset.state.value!r}"
            )
        return asset

    # ------------------------------------------------------------------ quotas

    def set_partition_quota(
        self,
        *,
        space: str,
        partition_id: str,
        quota_bytes: int | None = None,
        quota_asset_count: int | None = None,
        eviction_sweep_enabled: bool | None = None,
    ) -> PartitionQuota:
        """Configure a partition's quota limits, preserving live usage (FR-066)."""

        if quota_bytes is not None and quota_bytes < 0:
            raise ValidationError("quota_bytes must not be negative")
        if quota_asset_count is not None and quota_asset_count < 0:
            raise ValidationError("quota_asset_count must not be negative")

        norm_space = normalize_space(space)
        norm_partition = normalize_partition_id(partition_id)
        with self._conn.transaction():
            current = self._partition_quota(norm_space, norm_partition, for_update=True)
            sweep = (
                current.eviction_sweep_enabled
                if eviction_sweep_enabled is None
                else eviction_sweep_enabled
            )
            self._conn.execute(
                """
                INSERT INTO partition_quotas (
                    space, partition_id, quota_bytes, quota_asset_count,
                    used_bytes, used_asset_count, eviction_sweep_enabled
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (space, partition_id) DO UPDATE SET
                    quota_bytes = EXCLUDED.quota_bytes,
                    quota_asset_count = EXCLUDED.quota_asset_count,
                    eviction_sweep_enabled = EXCLUDED.eviction_sweep_enabled
                """,
                (
                    norm_space,
                    norm_partition,
                    quota_bytes,
                    quota_asset_count,
                    current.used_bytes,
                    current.used_asset_count,
                    sweep,
                ),
            )
        return self.get_partition_quota(space=norm_space, partition_id=norm_partition)

    def set_bucket_quota(
        self,
        *,
        space: str,
        quota_bytes: int | None = None,
        warn_threshold: float = 0.80,
        hard_ceiling: float = 1.00,
    ) -> BucketQuota:
        """Configure a space's bucket-wide quota, preserving live usage (FR-068)."""

        if quota_bytes is not None and quota_bytes < 0:
            raise ValidationError("quota_bytes must not be negative")

        norm_space = normalize_space(space)
        with self._conn.transaction():
            current = self._bucket_quota(norm_space, for_update=True)
            self._conn.execute(
                """
                INSERT INTO bucket_quotas (
                    space, quota_bytes, used_bytes, warn_threshold, hard_ceiling
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (space) DO UPDATE SET
                    quota_bytes = EXCLUDED.quota_bytes,
                    warn_threshold = EXCLUDED.warn_threshold,
                    hard_ceiling = EXCLUDED.hard_ceiling
                """,
                (norm_space, quota_bytes, current.used_bytes, warn_threshold, hard_ceiling),
            )
        return self.get_bucket_quota(space=norm_space)

    def get_partition_quota(self, *, space: str, partition_id: str) -> PartitionQuota:
        """Return the (possibly default) partition quota counters."""

        return self._partition_quota(normalize_space(space), normalize_partition_id(partition_id))

    def get_bucket_quota(self, *, space: str) -> BucketQuota:
        """Return the (possibly default) bucket quota counters."""

        return self._bucket_quota(normalize_space(space))

    # -------------------------------------------------------------------- audit

    @property
    def audit_events(self) -> tuple[AuditEvent, ...]:
        """Recorded audit events in insertion order (FR-008/FR-016)."""

        rows = self._conn.execute(
            """
            SELECT action, target, caller_service_id, outcome, before, after, ts
              FROM audit_events
             ORDER BY id
            """
        ).fetchall()
        return tuple(
            AuditEvent(
                action=row["action"],
                target=row["target"],
                caller_service_id=row["caller_service_id"],
                outcome=row["outcome"],
                before=MappingProxyType(dict(row["before"])),
                after=MappingProxyType(dict(row["after"])),
                ts=row["ts"],
            )
            for row in rows
        )

    # ----------------------------------------------------------------- helpers

    def _transition_out_of_available(
        self,
        *,
        asset_id: str,
        caller_service_id: str,
        allowed_from: tuple[AssetState, ...],
        new_state: AssetState,
        action: str,
        verb: str,
    ) -> Asset:
        """Shared ``available``/``expired`` → new-state transition with quota release."""

        allowed = {state.value for state in allowed_from}
        now = utcnow()
        with self._conn.transaction():
            row = self._conn.execute(
                "SELECT state, space, partition_id, size_bytes FROM assets "
                "WHERE asset_id = %s FOR UPDATE",
                (asset_id,),
            ).fetchone()
            if row is None:
                raise AssetNotFoundError(asset_id)
            if row["state"] not in allowed:
                raise InvalidStateTransitionError(
                    f"asset {asset_id!r} cannot {verb} from state {row['state']!r}"
                )

            self._conn.execute(
                "UPDATE assets SET state = %s, updated_at = %s WHERE asset_id = %s",
                (new_state.value, now, asset_id),
            )
            if row["state"] == AssetState.AVAILABLE.value:
                self._release_quota(
                    space=row["space"],
                    partition_id=row["partition_id"],
                    nbytes=row["size_bytes"] or 0,
                )
            self._write_audit(
                action=action,
                target=asset_id,
                caller_service_id=caller_service_id,
                before={"state": row["state"]},
                after={"state": new_state.value},
            )

        return self._load_asset(asset_id)

    def _mark_for_gc_if_orphaned(self, asset_id: str, caller_service_id: str) -> None:
        """Mark an asset with zero remaining aliases for GC (FR-003).

        Reuses ``expired`` so the normal GC sweep handles the ``expired → deleted``
        transition; the distinct ``asset.gc_mark`` action records that the trigger
        was alias removal. Mirrors the in-memory registry, which does not release
        quota on this path (that happens on the subsequent expire/delete).
        """

        remaining = self._conn.execute(
            "SELECT 1 FROM aliases WHERE asset_id = %s LIMIT 1", (asset_id,)
        ).fetchone()
        if remaining is not None:
            return
        row = self._conn.execute(
            "SELECT state FROM assets WHERE asset_id = %s FOR UPDATE", (asset_id,)
        ).fetchone()
        if row is None:
            return
        if row["state"] in (AssetState.EXPIRED.value, AssetState.DELETED.value):
            return
        self._conn.execute(
            "UPDATE assets SET state = %s, updated_at = %s WHERE asset_id = %s",
            (AssetState.EXPIRED.value, utcnow(), asset_id),
        )
        self._write_audit(
            action="asset.gc_mark",
            target=asset_id,
            caller_service_id=caller_service_id,
            before={"state": row["state"], "reason": "zero_aliases"},
            after={"state": AssetState.EXPIRED.value},
        )

    def _require_alias_name_available(self, norm_space: str, alias_name: str) -> None:
        """Raise if the alias name exists or is within its tombstone grace window."""

        existing = self._conn.execute(
            "SELECT 1 FROM aliases WHERE space = %s AND alias = %s", (norm_space, alias_name)
        ).fetchone()
        if existing is not None:
            raise AliasConflictError(f"alias {norm_space}/{alias_name!r} already exists")

        tomb = self._conn.execute(
            "SELECT grace_until FROM alias_tombstones WHERE space = %s AND alias = %s",
            (norm_space, alias_name),
        ).fetchone()
        if tomb is None:
            return
        if utcnow() >= tomb["grace_until"]:
            self._conn.execute(
                "DELETE FROM alias_tombstones WHERE space = %s AND alias = %s",
                (norm_space, alias_name),
            )
            return
        raise AliasConflictError(
            f"alias {norm_space}/{alias_name!r} already exists or is within grace period"
        )

    def _enforce_quota(self, *, space: str, partition_id: str, new_bytes: int) -> None:
        """Reject a commit that would breach a partition or bucket ceiling (FR-066/FR-068)."""

        pq = self._partition_quota(space, partition_id, for_update=True)
        if pq.quota_bytes is not None and (
            pq.used_bytes + new_bytes >= pq.quota_bytes * _PARTITION_HARD_RATIO
        ):
            raise QuotaExceededError(
                f"partition quota exceeded for {pq.space}/{pq.partition_id}", scope="partition"
            )
        if pq.quota_asset_count is not None and pq.used_asset_count + 1 > pq.quota_asset_count:
            raise QuotaExceededError(
                f"partition asset-count quota exceeded for {pq.space}/{pq.partition_id}",
                scope="partition",
            )

        bq = self._bucket_quota(space, for_update=True)
        if bq.quota_bytes is not None and (
            bq.used_bytes + new_bytes >= bq.quota_bytes * bq.hard_ceiling
        ):
            raise QuotaExceededError(f"bucket quota exceeded for {bq.space}", scope="bucket")

    def _acquire_quota(self, *, space: str, partition_id: str, nbytes: int) -> None:
        """Increment partition + bucket usage after a successful commit."""

        self._conn.execute(
            """
            INSERT INTO partition_quotas (
                space, partition_id, used_bytes, used_asset_count, eviction_sweep_enabled
            ) VALUES (%s, %s, %s, 1, %s)
            ON CONFLICT (space, partition_id) DO UPDATE SET
                used_bytes = partition_quotas.used_bytes + EXCLUDED.used_bytes,
                used_asset_count = partition_quotas.used_asset_count + 1
            """,
            (space, partition_id, nbytes, space in _SWEEP_DEFAULT_SPACES),
        )
        self._conn.execute(
            """
            INSERT INTO bucket_quotas (space, used_bytes) VALUES (%s, %s)
            ON CONFLICT (space) DO UPDATE SET
                used_bytes = bucket_quotas.used_bytes + EXCLUDED.used_bytes
            """,
            (space, nbytes),
        )

    def _release_quota(self, *, space: str, partition_id: str, nbytes: int) -> None:
        """Decrement usage counters (clamped at zero) when an asset leaves ``available``."""

        self._conn.execute(
            """
            UPDATE partition_quotas
               SET used_bytes = GREATEST(0, used_bytes - %s),
                   used_asset_count = GREATEST(0, used_asset_count - 1)
             WHERE space = %s AND partition_id = %s
            """,
            (nbytes, space, partition_id),
        )
        self._conn.execute(
            "UPDATE bucket_quotas SET used_bytes = GREATEST(0, used_bytes - %s) WHERE space = %s",
            (nbytes, space),
        )

    def _partition_quota(
        self, norm_space: str, norm_partition: str, *, for_update: bool = False
    ) -> PartitionQuota:
        sql = (
            "SELECT quota_bytes, quota_asset_count, used_bytes, used_asset_count, "
            "eviction_sweep_enabled FROM partition_quotas WHERE space = %s AND partition_id = %s"
        )
        if for_update:
            sql += " FOR UPDATE"
        row = self._conn.execute(sql, (norm_space, norm_partition)).fetchone()
        if row is None:
            return PartitionQuota(
                space=norm_space,
                partition_id=norm_partition,
                eviction_sweep_enabled=norm_space in _SWEEP_DEFAULT_SPACES,
            )
        return PartitionQuota(
            space=norm_space,
            partition_id=norm_partition,
            quota_bytes=row["quota_bytes"],
            quota_asset_count=row["quota_asset_count"],
            used_bytes=row["used_bytes"],
            used_asset_count=row["used_asset_count"],
            eviction_sweep_enabled=row["eviction_sweep_enabled"],
        )

    def _bucket_quota(self, norm_space: str, *, for_update: bool = False) -> BucketQuota:
        sql = (
            "SELECT quota_bytes, used_bytes, warn_threshold, hard_ceiling "
            "FROM bucket_quotas WHERE space = %s"
        )
        if for_update:
            sql += " FOR UPDATE"
        row = self._conn.execute(sql, (norm_space,)).fetchone()
        if row is None:
            return BucketQuota(space=norm_space)
        return BucketQuota(
            space=norm_space,
            quota_bytes=row["quota_bytes"],
            used_bytes=row["used_bytes"],
            warn_threshold=row["warn_threshold"],
            hard_ceiling=row["hard_ceiling"],
        )

    def _load_binding(self, norm_space: str, norm_alias: str) -> AliasBinding:
        row = self._conn.execute(
            """
            SELECT space, alias, asset_id, mutable, previous_asset_id,
                   created_at, updated_at, created_by_service_id
              FROM aliases WHERE space = %s AND alias = %s
            """,
            (norm_space, norm_alias),
        ).fetchone()
        if row is None:
            raise AliasNotFoundError(f"{norm_space}/{norm_alias}")
        return AliasBinding(
            space=row["space"],
            alias=row["alias"],
            asset_id=row["asset_id"],
            mutable=row["mutable"],
            previous_asset_id=row["previous_asset_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            created_by_service_id=row["created_by_service_id"],
        )

    def _write_audit(
        self,
        *,
        action: str,
        target: str,
        caller_service_id: str,
        before: Mapping[str, str] | None = None,
        after: Mapping[str, str] | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO audit_events (action, target, caller_service_id, outcome, before, after, ts)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                action,
                target,
                caller_service_id,
                "success",
                Jsonb(dict(before or {})),
                Jsonb(dict(after or {})),
                utcnow(),
            ),
        )

    def _load_asset(self, asset_id: str) -> Asset:
        asset_row = self._conn.execute(
            """
            SELECT asset_id, space, partition_id, storage_key, state, mime, size_bytes,
                   checksum_algo, checksum, annotations, eviction_policy, owner_service_id,
                   created_at, updated_at, expires_at
              FROM assets WHERE asset_id = %s
            """,
            (asset_id,),
        ).fetchone()
        if asset_row is None:
            raise AssetNotFoundError(asset_id)

        alias_rows = self._conn.execute(
            "SELECT alias FROM aliases WHERE asset_id = %s",
            (asset_id,),
        ).fetchall()
        aliases = frozenset(f"{asset_row['space']}/{row['alias']}" for row in alias_rows)

        return Asset(
            asset_id=asset_row["asset_id"],
            space=asset_row["space"],
            partition_id=asset_row["partition_id"],
            storage_key=asset_row["storage_key"],
            state=AssetState(asset_row["state"]),
            aliases=aliases,
            mime=asset_row["mime"],
            size_bytes=asset_row["size_bytes"],
            checksum_algo=asset_row["checksum_algo"],
            checksum=asset_row["checksum"],
            annotations=MappingProxyType(dict(asset_row["annotations"])),
            created_at=asset_row["created_at"],
            updated_at=asset_row["updated_at"],
            expires_at=asset_row["expires_at"],
            owner_service_id=asset_row["owner_service_id"],
            eviction_policy=EvictionPolicy(asset_row["eviction_policy"]),
        )
