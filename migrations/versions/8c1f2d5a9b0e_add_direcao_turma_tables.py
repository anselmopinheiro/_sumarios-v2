"""Add direcao de turma tables"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "8c1f2d5a9b0e"
down_revision = "b65e5f2e6a8a"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "dt_turmas" not in tables:
        op.create_table(
            "dt_turmas",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("turma_id", sa.Integer(), nullable=False),
            sa.Column("ano_letivo_id", sa.Integer(), nullable=False),
            sa.Column("observacoes", sa.Text()),
            sa.ForeignKeyConstraint(["turma_id"], ["turmas.id"]),
            sa.ForeignKeyConstraint(["ano_letivo_id"], ["anos_letivos.id"]),
            sa.UniqueConstraint("turma_id", "ano_letivo_id", name="uq_dt_turma_ano"),
        )

    if "dt_alunos" not in tables:
        op.create_table(
            "dt_alunos",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("dt_turma_id", sa.Integer(), nullable=False),
            sa.Column("origem_turma_id", sa.Integer()),
            sa.Column("processo", sa.String(length=50)),
            sa.Column("numero", sa.Integer()),
            sa.Column("nome", sa.String(length=255), nullable=False),
            sa.Column("nome_curto", sa.String(length=100)),
            sa.Column("nee", sa.Text()),
            sa.Column("observacoes", sa.Text()),
            sa.ForeignKeyConstraint(["dt_turma_id"], ["dt_turmas.id"]),
            sa.ForeignKeyConstraint(["origem_turma_id"], ["turmas.id"]),
        )
        op.create_index(
            "ix_dt_alunos_turma_numero",
            "dt_alunos",
            ["dt_turma_id", "numero"],
        )

    if "dt_justificacoes" not in tables:
        op.create_table(
            "dt_justificacoes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("dt_aluno_id", sa.Integer(), nullable=False),
            sa.Column("data", sa.Date(), nullable=False),
            sa.Column("tipo", sa.String(length=20), nullable=False, server_default="falta"),
            sa.Column("motivo", sa.Text()),
            sa.ForeignKeyConstraint(["dt_aluno_id"], ["dt_alunos.id"]),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "dt_justificacoes" in tables:
        op.drop_table("dt_justificacoes")

    if "dt_alunos" in tables:
        op.drop_index("ix_dt_alunos_turma_numero", table_name="dt_alunos")
        op.drop_table("dt_alunos")

    if "dt_turmas" in tables:
        op.drop_table("dt_turmas")
