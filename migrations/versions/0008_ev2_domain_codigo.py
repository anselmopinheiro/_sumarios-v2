"""add codigo field to ev2 domains

Revision ID: 0008_ev2_domain_codigo
Revises: 0007_ev2_domain_letra
Create Date: 2026-03-18
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_ev2_domain_codigo"
down_revision = "0007_ev2_domain_letra"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for col in inspector.get_columns(table_name):
        if col.get("name") == column_name:
            return True
    return False


def upgrade():
    if not _has_column("ev2_domains", "codigo"):
        op.add_column("ev2_domains", sa.Column("codigo", sa.String(length=20), nullable=True))


def downgrade():
    if _has_column("ev2_domains", "codigo"):
        op.drop_column("ev2_domains", "codigo")
