"""Postgres-backed asset registry — thin spike (S-002, ADR-001 control plane).

A faithful, durable implementation of the **reserve → commit → resolve** slice of
:class:`~asset_store_core.registry.InMemoryAssetRegistry`, used to validate the
schema and the registry seam against real Postgres before the full B-009 port
(which will add SQLAlchemy + Alembic and the remaining lifecycle/quota/alias
surface). Returns the same domain :class:`~asset_store_core.models.Asset` objects
so HTTP adapters are unaffected.

Scope (deliberately thin):

- Implemented: ``reserve_asset``, ``commit_asset``, ``resolve_alias`` with the
  same validation, alias-conflict, checksum (FR-022) and state-transition rules,
  plus transactional ``alias.create`` / ``asset.commit`` audit rows.
- Deferred to B-009: quota accounting/ceilings, alias detach/rebind, annotations,
  expire/delete, the FR-003 tombstone grace window, and connection pooling.

``psycopg`` (v3) is an optional dependency; install the ``pg`` extra
(``pip install asset-store-prototype[pg]``). It ships inline types, so no stubs
are needed. Like the in-memory registry, an instance is **not** thread-safe: it
holds a single connection and serialises operations per transaction.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from asset_store_core.errors import (
    AliasConflictError,
    AliasNotFoundError,
    AssetNotFoundError,
    ChecksumMismatchError,
    InvalidStateTransitionError,
    ValidationError,
)
from asset_store_core.ids import new_asset_id
from asset_store_core.models import (
    Asset,
    AssetState,
    AuditEvent,
    EvictionPolicy,
    utcnow,
)
from asset_store_core.paths import normalize_relative_alias, normalize_space
from asset_store_core.registry import _alias_under_partition, _normalize_alias_specs
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

CREATE TABLE IF NOT EXISTS audit_events (
    id               bigserial PRIMARY KEY,
    action           text NOT NULL,
    target           text NOT NULL,
    caller_service_id text NOT NULL,
    outcome          text NOT NULL,
    before           jsonb NOT NULL DEFAULT '{}'::jsonb,
    after            jsonb NOT NULL DEFAULT '{}'::jsonb,
    ts               timestamptz NOT NULL
);
"""


class PostgresAssetRegistry:
    """Durable reserve/commit/resolve over Postgres (thin S-002 spike)."""

    __slots__ = ("_conn",)

    def __init__(self, connection: Connection[Any], *, bootstrap_schema: bool = True) -> None:
        self._conn = connection
        # Autocommit + explicit ``transaction()`` blocks is the recommended psycopg-3
        # pattern: standalone reads commit immediately (no lingering open transaction),
        # so each multi-statement op below opens a real top-level transaction rather
        # than a savepoint nested in a stray read transaction.
        self._conn.autocommit = True
        if bootstrap_schema:
            with self._conn.transaction():
                self._conn.execute(_SCHEMA)

    @classmethod
    def connect(cls, dsn: str, *, bootstrap_schema: bool = True) -> PostgresAssetRegistry:
        """Open a new connection from ``dsn`` and return a registry."""

        connection = psycopg.connect(dsn, row_factory=dict_row)
        return cls(connection, bootstrap_schema=bootstrap_schema)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> PostgresAssetRegistry:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

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
                row = self._conn.execute(
                    "SELECT 1 FROM aliases WHERE space = %s AND alias = %s",
                    (norm_space, scoped_alias),
                ).fetchone()
                if row is not None:
                    raise AliasConflictError(f"alias {norm_space}/{scoped_alias!r} already exists")

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
                "SELECT state, mime FROM assets WHERE asset_id = %s FOR UPDATE",
                (asset_id,),
            ).fetchone()
            if row is None:
                raise AssetNotFoundError(asset_id)
            if row["state"] != AssetState.PENDING.value:
                raise InvalidStateTransitionError(
                    f"asset {asset_id!r} cannot be committed from state {row['state']!r}"
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
            self._write_audit(
                action="asset.commit",
                target=asset_id,
                caller_service_id=caller_service_id,
                before={"state": AssetState.PENDING.value},
                after={"state": AssetState.AVAILABLE.value},
            )

        return self._load_asset(asset_id)

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

    def audit_events(self) -> tuple[AuditEvent, ...]:
        """Return recorded audit events in insertion order."""

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
