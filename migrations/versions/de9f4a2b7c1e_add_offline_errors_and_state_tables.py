"""add offline errors and offline state tables

Revision ID: de9f4a2b7c1e
Revises: cc34dd56ee78
Create Date: 2026-02-21 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "de9f4a2b7c1e"
down_revision = "cc34dd56ee78"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "offline_errors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("context_json", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_offline_errors_created_at", "offline_errors", ["created_at"])
    op.create_index("ix_offline_errors_operation", "offline_errors", ["operation"])

    op.create_table(
        "offline_state",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade():
    op.drop_table("offline_state")

    op.drop_index("ix_offline_errors_operation", table_name="offline_errors")
    op.drop_index("ix_offline_errors_created_at", table_name="offline_errors")
    op.drop_table("offline_errors")
