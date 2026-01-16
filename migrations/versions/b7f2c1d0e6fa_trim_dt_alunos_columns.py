"""Trim dt_alunos columns"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b7f2c1d0e6fa"
down_revision = "a4c8b9d8f1aa"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "dt_alunos" not in tables:
        return

    cols = {col["name"] for col in inspector.get_columns("dt_alunos")}
    if cols == {"id", "dt_turma_id", "aluno_id"}:
        return

    op.create_table(
        "dt_alunos_new",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dt_turma_id", sa.Integer(), nullable=False),
        sa.Column("aluno_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["dt_turma_id"], ["dt_turmas.id"]),
        sa.ForeignKeyConstraint(["aluno_id"], ["alunos.id"]),
    )

    if {"processo", "numero", "nome"}.issubset(cols):
        op.execute(
            """
            INSERT INTO dt_alunos_new (dt_turma_id, aluno_id)
            SELECT d.dt_turma_id, a.id
            FROM dt_alunos d
            JOIN alunos a
              ON a.processo = d.processo
             AND (a.numero IS d.numero OR (a.numero = d.numero))
             AND a.nome = d.nome
            WHERE a.id IS NOT NULL
            """
        )
    elif "aluno_id" in cols:
        op.execute(
            """
            INSERT INTO dt_alunos_new (dt_turma_id, aluno_id)
            SELECT dt_turma_id, aluno_id
            FROM dt_alunos
            WHERE aluno_id IS NOT NULL
            """
        )

    op.drop_table("dt_alunos")
    op.rename_table("dt_alunos_new", "dt_alunos")
    op.create_index("ix_dt_alunos_turma_aluno", "dt_alunos", ["dt_turma_id", "aluno_id"])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "dt_alunos" not in tables:
        return

    cols = {col["name"] for col in inspector.get_columns("dt_alunos")}
    if {"processo", "numero", "nome"}.issubset(cols):
        return

    op.create_table(
        "dt_alunos_old",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dt_turma_id", sa.Integer(), nullable=False),
        sa.Column("aluno_id", sa.Integer()),
        sa.Column("origem_turma_id", sa.Integer()),
        sa.Column("processo", sa.String(length=50)),
        sa.Column("numero", sa.Integer()),
        sa.Column("nome", sa.String(length=255), nullable=False),
        sa.Column("nome_curto", sa.String(length=100)),
        sa.Column("nee", sa.Text()),
        sa.Column("observacoes", sa.Text()),
        sa.ForeignKeyConstraint(["dt_turma_id"], ["dt_turmas.id"]),
        sa.ForeignKeyConstraint(["aluno_id"], ["alunos.id"]),
        sa.ForeignKeyConstraint(["origem_turma_id"], ["turmas.id"]),
    )

    op.execute(
        """
        INSERT INTO dt_alunos_old (dt_turma_id, aluno_id)
        SELECT dt_turma_id, aluno_id FROM dt_alunos
        """
    )

    op.drop_table("dt_alunos")
    op.rename_table("dt_alunos_old", "dt_alunos")
