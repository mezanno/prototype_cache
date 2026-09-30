"""Durable proxy-upload byte estimates (M-001/P2, ADR-029)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_upload_reservations"
down_revision = "0002_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("reserved_bytes", sa.BigInteger(), nullable=True))
    op.create_check_constraint("assets_reserved_bytes_nonnegative", "assets", "reserved_bytes >= 0")


def downgrade() -> None:
    op.drop_constraint("assets_reserved_bytes_nonnegative", "assets", type_="check")
    op.drop_column("assets", "reserved_bytes")
