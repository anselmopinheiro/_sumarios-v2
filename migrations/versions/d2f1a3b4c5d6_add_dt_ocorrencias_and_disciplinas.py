"""add dt ocorrencias and disciplinas

Revision ID: d2f1a3b4c5d6
Revises: 1f2a3b4c5d6e
Create Date: 2026-02-10
"""

from alembic import op
import sqlalchemy as sa


revision = "d2f1a3b4c5d6"
down_revision = "1f2a3b4c5d6e"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "dt_disciplinas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nome", sa.String(length=120), nullable=False),
        sa.Column("ativa", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.PrimaryKeyConstraint("id", name="pk_dt_disciplinas"),
        sa.UniqueConstraint("nome", name="uq_dt_disciplinas_nome"),
    )

    op.create_table(
        "dt_ocorrencias",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dt_turma_id", sa.Integer(), nullable=False),
        sa.Column("data", sa.Date(), nullable=False),
        sa.Column("hora_inicio", sa.Time(), nullable=True),
        sa.Column("hora_fim", sa.Time(), nullable=True),
        sa.Column("num_tempos", sa.Integer(), nullable=True),
        sa.Column("dt_disciplina_id", sa.Integer(), nullable=False),
        sa.Column("observacoes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["dt_disciplina_id"], ["dt_disciplinas.id"], name="fk_dt_ocorrencia_disciplina"),
        sa.ForeignKeyConstraint(["dt_turma_id"], ["dt_turmas.id"], name="fk_dt_ocorrencia_turma"),
        sa.PrimaryKeyConstraint("id", name="pk_dt_ocorrencias"),
    )
    op.create_index("ix_dt_ocorrencias_data", "dt_ocorrencias", ["data"], unique=False)
    op.create_index("ix_dt_ocorrencias_dt_disciplina_id", "dt_ocorrencias", ["dt_disciplina_id"], unique=False)
    op.create_index("ix_dt_ocorrencias_dt_turma_id", "dt_ocorrencias", ["dt_turma_id"], unique=False)

    op.create_table(
        "dt_ocorrencia_alunos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dt_ocorrencia_id", sa.Integer(), nullable=False),
        sa.Column("dt_aluno_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["dt_aluno_id"], ["dt_alunos.id"], name="fk_dt_ocorr_aluno_aluno"),
        sa.ForeignKeyConstraint(["dt_ocorrencia_id"], ["dt_ocorrencias.id"], name="fk_dt_ocorr_aluno_ocorr"),
        sa.PrimaryKeyConstraint("id", name="pk_dt_ocorrencia_alunos"),
        sa.UniqueConstraint("dt_ocorrencia_id", "dt_aluno_id", name="uq_dt_ocorrencia_aluno"),
    )
    op.create_index("ix_dt_ocorrencia_alunos_aluno", "dt_ocorrencia_alunos", ["dt_aluno_id"], unique=False)
    op.create_index("ix_dt_ocorrencia_alunos_ocorrencia", "dt_ocorrencia_alunos", ["dt_ocorrencia_id"], unique=False)


def downgrade():
    op.drop_index("ix_dt_ocorrencia_alunos_ocorrencia", table_name="dt_ocorrencia_alunos")
    op.drop_index("ix_dt_ocorrencia_alunos_aluno", table_name="dt_ocorrencia_alunos")
    op.drop_table("dt_ocorrencia_alunos")
    op.drop_index("ix_dt_ocorrencias_dt_turma_id", table_name="dt_ocorrencias")
    op.drop_index("ix_dt_ocorrencias_dt_disciplina_id", table_name="dt_ocorrencias")
    op.drop_index("ix_dt_ocorrencias_data", table_name="dt_ocorrencias")
    op.drop_table("dt_ocorrencias")
    op.drop_table("dt_disciplinas")
