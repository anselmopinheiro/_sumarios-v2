"""add letiva to turmas

Revision ID: 7abf1f2c9f1a
Revises: 4f5e1c4f4e0b
Create Date: 2025-02-11 21:36:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7abf1f2c9f1a"
down_revision = "4f5e1c4f4e0b"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("turmas")}

    if "letiva" not in columns:
        op.add_column(
            "turmas",
            sa.Column("letiva", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        )
        op.alter_column("turmas", "letiva", server_default=None)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("turmas")}

    if "letiva" in columns:
        op.drop_column("turmas", "letiva")
