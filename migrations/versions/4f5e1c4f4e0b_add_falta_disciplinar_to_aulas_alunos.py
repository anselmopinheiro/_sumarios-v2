"""add falta_disciplinar to aulas_alunos

Revision ID: 4f5e1c4f4e0b
Revises: 2c60e0f613b9
Create Date: 2025-05-21 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "4f5e1c4f4e0b"
down_revision = "2c60e0f613b9"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("aulas_alunos")}

    if "falta_disciplinar" not in columns:
        op.add_column(
            "aulas_alunos",
            sa.Column("falta_disciplinar", sa.Integer(), nullable=False, server_default=sa.text("0")),
        )
        op.alter_column("aulas_alunos", "falta_disciplinar", server_default=None)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("aulas_alunos")}

    if "falta_disciplinar" in columns:
        op.drop_column("aulas_alunos", "falta_disciplinar")
