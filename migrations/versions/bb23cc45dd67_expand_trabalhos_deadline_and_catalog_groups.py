"""expand trabalhos deadline and catalog groups

Revision ID: bb23cc45dd67
Revises: aa12bb34cc56
Create Date: 2026-02-18 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "bb23cc45dd67"
down_revision = "aa12bb34cc56"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("trabalhos", sa.Column("data_limite", sa.DateTime(), nullable=True))

    op.add_column("entregas", sa.Column("data_entrega", sa.DateTime(), nullable=True))
    op.add_column("entregas", sa.Column("observacoes", sa.Text(), nullable=True))

    op.create_table(
        "grupos_turma",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("turma_id", sa.Integer(), nullable=False),
        sa.Column("nome", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(["turma_id"], ["turmas.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("turma_id", "nome", name="uq_grupo_turma_nome"),
    )
    op.create_index("ix_grupos_turma_turma_id", "grupos_turma", ["turma_id"])

    op.create_table(
        "grupo_turma_membros",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("grupo_turma_id", sa.Integer(), nullable=False),
        sa.Column("aluno_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["grupo_turma_id"], ["grupos_turma.id"]),
        sa.ForeignKeyConstraint(["aluno_id"], ["alunos.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("grupo_turma_id", "aluno_id", name="uq_grupo_turma_membro"),
    )
    op.create_index("ix_grupo_turma_membros_grupo_turma_id", "grupo_turma_membros", ["grupo_turma_id"])
    op.create_index("ix_grupo_turma_membros_aluno_id", "grupo_turma_membros", ["aluno_id"])


def downgrade():
    op.drop_index("ix_grupo_turma_membros_aluno_id", table_name="grupo_turma_membros")
    op.drop_index("ix_grupo_turma_membros_grupo_turma_id", table_name="grupo_turma_membros")
    op.drop_table("grupo_turma_membros")

    op.drop_index("ix_grupos_turma_turma_id", table_name="grupos_turma")
    op.drop_table("grupos_turma")

    op.drop_column("entregas", "observacoes")
    op.drop_column("entregas", "data_entrega")
    op.drop_column("trabalhos", "data_limite")
