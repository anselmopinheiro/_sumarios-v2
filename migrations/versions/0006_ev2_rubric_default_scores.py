"""add default score fields to ev2 rubrics

Revision ID: 0006_ev2_rubric_default_scores
Revises: 0005_aula_avaliacao_tables
Create Date: 2026-03-18
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_ev2_rubric_default_scores"
down_revision = "0005_aula_avaliacao_tables"
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
    if not _has_column("ev2_rubrics", "pontuacao_padrao_basico"):
        op.add_column(
            "ev2_rubrics",
            sa.Column("pontuacao_padrao_basico", sa.Float(), nullable=True, server_default="3"),
        )
    if not _has_column("ev2_rubrics", "pontuacao_padrao_secundario"):
        op.add_column(
            "ev2_rubrics",
            sa.Column("pontuacao_padrao_secundario", sa.Float(), nullable=True, server_default="12"),
        )


def downgrade():
    if _has_column("ev2_rubrics", "pontuacao_padrao_basico"):
        op.drop_column("ev2_rubrics", "pontuacao_padrao_basico")
    if _has_column("ev2_rubrics", "pontuacao_padrao_secundario"):
        op.drop_column("ev2_rubrics", "pontuacao_padrao_secundario")
