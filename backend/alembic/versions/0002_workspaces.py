"""workspaces: advisor = no-login workspace (created_at, last_seen_at, created_ip) + per-IP daily provisioning counter

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("advisors", sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.add_column("advisors", sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.add_column("advisors", sa.Column("created_ip", sa.String(length=64), nullable=True))
    op.create_index(op.f("ix_advisors_last_seen_at"), "advisors", ["last_seen_at"], unique=False)
    op.create_table(
        "workspace_provisions",
        sa.Column("ip", sa.String(length=64), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("count", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("ip", "day"),
    )


def downgrade() -> None:
    op.drop_table("workspace_provisions")
    op.drop_index(op.f("ix_advisors_last_seen_at"), table_name="advisors")
    op.drop_column("advisors", "created_ip")
    op.drop_column("advisors", "last_seen_at")
    op.drop_column("advisors", "created_at")
