"""add observacoes_html to calendario_aulas

Revision ID: c6f9a7e2b1d3
Revises: f9b2c7d4e1a0
Create Date: 2026-02-24 09:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c6f9a7e2b1d3"
down_revision = "f9b2c7d4e1a0"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("calendario_aulas")}
    if "observacoes_html" not in columns:
        op.add_column("calendario_aulas", sa.Column("observacoes_html", sa.Text(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("calendario_aulas")}
    if "observacoes_html" in columns:
        op.drop_column("calendario_aulas", "observacoes_html")
