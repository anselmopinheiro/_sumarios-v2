"""add aula avaliacao tables

Revision ID: 0005_aula_avaliacao_tables
Revises: 0004_ev2_schema_baseline
Create Date: 2026-03-18
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_aula_avaliacao_tables"
down_revision = "0004_ev2_schema_baseline"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade():
    if not _has_table("avaliacoes"):
        op.create_table(
            "avaliacoes",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("aluno_id", sa.Integer(), nullable=False),
            sa.Column("aula_id", sa.Integer(), nullable=False),
            sa.Column("resultado", sa.Float(), nullable=True),
            sa.ForeignKeyConstraint(["aluno_id"], ["alunos.id"]),
            sa.ForeignKeyConstraint(["aula_id"], ["calendario_aulas.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("aluno_id", "aula_id", name="uq_avaliacao_aluno_aula"),
        )
        op.create_index("ix_avaliacoes_aula", "avaliacoes", ["aula_id"])
        op.create_index("ix_avaliacoes_aluno", "avaliacoes", ["aluno_id"])

    if not _has_table("avaliacao_itens"):
        op.create_table(
            "avaliacao_itens",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("avaliacao_id", sa.Integer(), nullable=False),
            sa.Column("rubrica_id", sa.Integer(), nullable=False),
            sa.Column("pontuacao", sa.Float(), nullable=True),
            sa.ForeignKeyConstraint(["avaliacao_id"], ["avaliacoes.id"]),
            sa.ForeignKeyConstraint(["rubrica_id"], ["ev2_rubrics.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("avaliacao_id", "rubrica_id", name="uq_avaliacao_item_once"),
        )
        op.create_index("ix_avaliacao_itens_avaliacao", "avaliacao_itens", ["avaliacao_id"])
        op.create_index("ix_avaliacao_itens_rubrica", "avaliacao_itens", ["rubrica_id"])


def downgrade():
    if _has_table("avaliacao_itens"):
        op.drop_table("avaliacao_itens")

    if _has_table("avaliacoes"):
        op.drop_table("avaliacoes")
