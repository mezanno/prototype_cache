"""Lifecycle timestamps and access counters (B-014, ADR-020)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_lifecycle"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("expired_at", "last_read_at", "payload_deleted_at"):
        op.add_column("assets", sa.Column(name, sa.TIMESTAMP(timezone=True)))
    op.add_column(
        "assets",
        sa.Column("read_count", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )
    op.execute("UPDATE assets SET expired_at = updated_at WHERE state = 'expired'")
    op.execute(
        "UPDATE assets SET expires_at = created_at + interval '24 hours' "
        "WHERE space = 'tmp' AND expires_at IS NULL AND state IN ('pending', 'available')"
    )
    op.execute(
        "UPDATE assets SET expires_at = created_at + interval '365 days' "
        "WHERE space = 'results' AND expires_at IS NULL AND state IN ('pending', 'available')"
    )
    # Fix legacy zero-alias GC marks which did not release available quota.
    op.execute(
        "UPDATE partition_quotas q SET used_bytes = "
        "(SELECT COALESCE(SUM(size_bytes), 0) FROM assets a WHERE a.space = q.space "
        "AND a.partition_id = q.partition_id AND a.state = 'available'), "
        "used_asset_count = (SELECT COUNT(*) FROM assets a WHERE a.space = q.space "
        "AND a.partition_id = q.partition_id AND a.state = 'available')"
    )
    op.execute(
        "UPDATE bucket_quotas q SET used_bytes = "
        "(SELECT COALESCE(SUM(size_bytes), 0) FROM assets a "
        "WHERE a.space = q.space AND a.state = 'available')"
    )
    op.create_index("assets_lifecycle_idx", "assets", ["state", "expires_at"])


def downgrade() -> None:
    op.drop_index("assets_lifecycle_idx", table_name="assets")
    for name in ("read_count", "payload_deleted_at", "last_read_at", "expired_at"):
        op.drop_column("assets", name)
