"""add letra field to ev2 domains

Revision ID: 0007_ev2_domain_letra
Revises: 0006_ev2_rubric_default_scores
Create Date: 2026-03-18
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_ev2_domain_letra"
down_revision = "0006_ev2_rubric_default_scores"
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
    if not _has_column("ev2_domains", "letra"):
        op.add_column("ev2_domains", sa.Column("letra", sa.String(length=5), nullable=True))


def downgrade():
    if _has_column("ev2_domains", "letra"):
        op.drop_column("ev2_domains", "letra")
