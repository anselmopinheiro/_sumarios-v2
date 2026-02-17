"""add trabalhos module

Revision ID: aa12bb34cc56
Revises: f2a1b7c9d001
Create Date: 2026-02-17 21:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "aa12bb34cc56"
down_revision = "f2a1b7c9d001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "trabalhos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("turma_id", sa.Integer(), nullable=False),
        sa.Column("titulo", sa.String(length=255), nullable=False),
        sa.Column("descricao", sa.Text(), nullable=True),
        sa.Column("modo", sa.String(length=20), nullable=False, server_default="individual"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["turma_id"], ["turmas.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trabalhos_turma_id", "trabalhos", ["turma_id"])

    op.create_table(
        "trabalho_grupos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trabalho_id", sa.Integer(), nullable=False),
        sa.Column("nome", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(["trabalho_id"], ["trabalhos.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trabalho_id", "nome", name="uq_trabalho_grupo_nome"),
    )
    op.create_index("ix_trabalho_grupos_trabalho_id", "trabalho_grupos", ["trabalho_id"])

    op.create_table(
        "trabalho_grupo_membros",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trabalho_grupo_id", sa.Integer(), nullable=False),
        sa.Column("aluno_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["trabalho_grupo_id"], ["trabalho_grupos.id"]),
        sa.ForeignKeyConstraint(["aluno_id"], ["alunos.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trabalho_grupo_id", "aluno_id", name="uq_trabalho_grupo_membro"),
    )
    op.create_index("ix_trabalho_grupo_membros_trabalho_grupo_id", "trabalho_grupo_membros", ["trabalho_grupo_id"])
    op.create_index("ix_trabalho_grupo_membros_aluno_id", "trabalho_grupo_membros", ["aluno_id"])

    op.create_table(
        "entregas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trabalho_id", sa.Integer(), nullable=False),
        sa.Column("trabalho_grupo_id", sa.Integer(), nullable=False),
        sa.Column("entregue", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("consecucao", sa.Integer(), nullable=True),
        sa.Column("qualidade", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("consecucao IS NULL OR (consecucao >= 1 AND consecucao <= 5)", name="ck_entrega_consecucao_1_5"),
        sa.CheckConstraint("qualidade IS NULL OR (qualidade >= 1 AND qualidade <= 5)", name="ck_entrega_qualidade_1_5"),
        sa.ForeignKeyConstraint(["trabalho_id"], ["trabalhos.id"]),
        sa.ForeignKeyConstraint(["trabalho_grupo_id"], ["trabalho_grupos.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trabalho_id", "trabalho_grupo_id", name="uq_entrega_trabalho_grupo"),
    )
    op.create_index("ix_entregas_trabalho_id", "entregas", ["trabalho_id"])
    op.create_index("ix_entregas_trabalho_grupo_id", "entregas", ["trabalho_grupo_id"])

    op.create_table(
        "parametro_definicoes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trabalho_id", sa.Integer(), nullable=False),
        sa.Column("nome", sa.String(length=120), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False, server_default="numerico"),
        sa.Column("ordem", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["trabalho_id"], ["trabalhos.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trabalho_id", "nome", name="uq_parametro_trabalho_nome"),
    )
    op.create_index("ix_parametro_definicoes_trabalho_id", "parametro_definicoes", ["trabalho_id"])

    op.create_table(
        "entrega_parametros",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("entrega_id", sa.Integer(), nullable=False),
        sa.Column("parametro_definicao_id", sa.Integer(), nullable=False),
        sa.Column("valor_numerico", sa.Integer(), nullable=True),
        sa.Column("valor_texto", sa.Text(), nullable=True),
        sa.CheckConstraint("valor_numerico IS NULL OR (valor_numerico >= 1 AND valor_numerico <= 5)", name="ck_entrega_parametro_num_1_5"),
        sa.ForeignKeyConstraint(["entrega_id"], ["entregas.id"]),
        sa.ForeignKeyConstraint(["parametro_definicao_id"], ["parametro_definicoes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entrega_id", "parametro_definicao_id", name="uq_entrega_parametro"),
    )
    op.create_index("ix_entrega_parametros_entrega_id", "entrega_parametros", ["entrega_id"])
    op.create_index("ix_entrega_parametros_parametro_definicao_id", "entrega_parametros", ["parametro_definicao_id"])


def downgrade():
    op.drop_index("ix_entrega_parametros_parametro_definicao_id", table_name="entrega_parametros")
    op.drop_index("ix_entrega_parametros_entrega_id", table_name="entrega_parametros")
    op.drop_table("entrega_parametros")

    op.drop_index("ix_parametro_definicoes_trabalho_id", table_name="parametro_definicoes")
    op.drop_table("parametro_definicoes")

    op.drop_index("ix_entregas_trabalho_grupo_id", table_name="entregas")
    op.drop_index("ix_entregas_trabalho_id", table_name="entregas")
    op.drop_table("entregas")

    op.drop_index("ix_trabalho_grupo_membros_aluno_id", table_name="trabalho_grupo_membros")
    op.drop_index("ix_trabalho_grupo_membros_trabalho_grupo_id", table_name="trabalho_grupo_membros")
    op.drop_table("trabalho_grupo_membros")

    op.drop_index("ix_trabalho_grupos_trabalho_id", table_name="trabalho_grupos")
    op.drop_table("trabalho_grupos")

    op.drop_index("ix_trabalhos_turma_id", table_name="trabalhos")
    op.drop_table("trabalhos")
