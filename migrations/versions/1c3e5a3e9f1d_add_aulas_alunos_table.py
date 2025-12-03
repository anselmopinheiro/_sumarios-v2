"""Add aulas_alunos table for per-student attendance"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "1c3e5a3e9f1d"
down_revision = "5f2c5b27a3c4"
branch_labels = None
depends_on = None


COLS = [
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("aula_id", sa.Integer(), nullable=False),
    sa.Column("aluno_id", sa.Integer(), nullable=False),
    sa.Column("atraso", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    sa.Column("faltas", sa.Integer(), nullable=False, server_default=sa.text("0")),
    sa.Column("responsabilidade", sa.Integer()),
    sa.Column("comportamento", sa.Integer()),
    sa.Column("participacao", sa.Integer()),
    sa.Column("trabalho_autonomo", sa.Integer()),
    sa.Column("portatil_material", sa.Integer()),
    sa.Column("atividade", sa.Integer()),
]


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "aulas_alunos" not in tables:
        op.create_table(
            "aulas_alunos",
            *COLS,
            sa.ForeignKeyConstraint(["aula_id"], ["calendario_aulas.id"]),
            sa.ForeignKeyConstraint(["aluno_id"], ["alunos.id"]),
            sa.UniqueConstraint("aula_id", "aluno_id", name="uq_aula_aluno"),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "aulas_alunos" in tables:
        op.drop_table("aulas_alunos")
