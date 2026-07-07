"""initial asset-store registry schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-07-07

Creates the durable control-plane schema for the Postgres asset registry
(B-009): assets, aliases (+ tombstones), the two-tier partition/bucket quotas,
and the audit log. This mirrors the ``CREATE TABLE IF NOT EXISTS`` DDL that the
registry can still bootstrap for dev/test; production owns the schema through
this migration history.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("asset_id", sa.Text(), primary_key=True),
        sa.Column("space", sa.Text(), nullable=False),
        sa.Column("partition_id", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("mime", sa.Text()),
        sa.Column("size_bytes", sa.BigInteger()),
        sa.Column("checksum_algo", sa.Text(), nullable=False, server_default="sha256"),
        sa.Column("checksum", sa.Text()),
        sa.Column(
            "annotations",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("eviction_policy", sa.Text(), nullable=False, server_default="inherit"),
        sa.Column("owner_service_id", sa.Text(), nullable=False, server_default="system"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True)),
    )

    op.create_table(
        "aliases",
        sa.Column("space", sa.Text(), nullable=False),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("asset_id", sa.Text(), sa.ForeignKey("assets.asset_id")),
        sa.Column("mutable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("previous_asset_id", sa.Text()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("created_by_service_id", sa.Text(), nullable=False, server_default="system"),
        sa.PrimaryKeyConstraint("space", "alias"),
    )
    op.create_index("aliases_asset_id_idx", "aliases", ["asset_id"])

    op.create_table(
        "alias_tombstones",
        sa.Column("space", sa.Text(), nullable=False),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("grace_until", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("space", "alias"),
    )

    op.create_table(
        "partition_quotas",
        sa.Column("space", sa.Text(), nullable=False),
        sa.Column("partition_id", sa.Text(), nullable=False),
        sa.Column("quota_bytes", sa.BigInteger()),
        sa.Column("quota_asset_count", sa.BigInteger()),
        sa.Column("used_bytes", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("used_asset_count", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "eviction_sweep_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.PrimaryKeyConstraint("space", "partition_id"),
    )

    op.create_table(
        "bucket_quotas",
        sa.Column("space", sa.Text(), primary_key=True),
        sa.Column("quota_bytes", sa.BigInteger()),
        sa.Column("used_bytes", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "warn_threshold",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.80"),
        ),
        sa.Column(
            "hard_ceiling",
            sa.Float(),
            nullable=False,
            server_default=sa.text("1.00"),
        ),
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("caller_service_id", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column(
            "before",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "after",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("bucket_quotas")
    op.drop_table("partition_quotas")
    op.drop_table("alias_tombstones")
    op.drop_index("aliases_asset_id_idx", table_name="aliases")
    op.drop_table("aliases")
    op.drop_table("assets")
