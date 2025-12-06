"""Add alunos table"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "5f2c5b27a3c4"
down_revision = "c3f9a9d8b21c"
branch_labels = None
depends_on = None


COLS = [
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("turma_id", sa.Integer(), nullable=False),
    sa.Column("processo", sa.String(length=50)),
    sa.Column("numero", sa.Integer()),
    sa.Column("nome", sa.String(length=255), nullable=False),
    sa.Column("nome_curto", sa.String(length=100)),
    sa.Column("nee", sa.Text()),
    sa.Column("observacoes", sa.Text()),
]


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "alunos" not in tables:
        op.create_table(
            "alunos",
            *COLS,
            sa.ForeignKeyConstraint(["turma_id"], ["turmas.id"]),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "alunos" in tables:
        op.drop_table("alunos")
