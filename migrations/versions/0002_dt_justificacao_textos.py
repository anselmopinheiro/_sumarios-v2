"""add dt_justificacao_textos table

Revision ID: 0002_dt_justificacao_textos
Revises: 0001_initial
Create Date: 2026-03-12
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_dt_justificacao_textos"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "dt_justificacao_textos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("titulo", sa.String(length=120), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("dt_justificacao_textos")
