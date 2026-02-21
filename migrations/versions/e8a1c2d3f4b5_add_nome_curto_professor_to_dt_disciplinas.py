"""add nome_curto and professor_nome to dt_disciplinas

Revision ID: e8a1c2d3f4b5
Revises: d2f1a3b4c5d6
Create Date: 2026-02-10
"""

from alembic import op
import sqlalchemy as sa


revision = "e8a1c2d3f4b5"
down_revision = "d2f1a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("dt_disciplinas")}

    if "nome_curto" not in columns:
        op.add_column("dt_disciplinas", sa.Column("nome_curto", sa.String(length=40), nullable=True))
    if "professor_nome" not in columns:
        op.add_column("dt_disciplinas", sa.Column("professor_nome", sa.String(length=120), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("dt_disciplinas")}

    if "professor_nome" in columns:
        op.drop_column("dt_disciplinas", "professor_nome")
    if "nome_curto" in columns:
        op.drop_column("dt_disciplinas", "nome_curto")
