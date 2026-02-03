"""Add aluno_id to dt_alunos"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a4c8b9d8f1aa"
down_revision = "9c2a1d4f8b7e"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("dt_alunos")}

    if "aluno_id" not in columns:
        op.add_column("dt_alunos", sa.Column("aluno_id", sa.Integer()))
        op.create_index("ix_dt_alunos_turma_aluno", "dt_alunos", ["dt_turma_id", "aluno_id"])
        op.create_foreign_key("fk_dt_aluno", "dt_alunos", "alunos", ["aluno_id"], ["id"])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("dt_alunos")}

    if "aluno_id" in columns:
        op.drop_constraint("fk_dt_aluno", "dt_alunos", type_="foreignkey")
        op.drop_index("ix_dt_alunos_turma_aluno", table_name="dt_alunos")
        op.drop_column("dt_alunos", "aluno_id")
