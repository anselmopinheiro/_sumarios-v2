"""add falta_disciplinar to aulas_alunos

Revision ID: 4f5e1c4f4e0b
Revises: 2c60e0f613b9_add_tempo_columns_to_turmas
Create Date: 2025-05-21 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "4f5e1c4f4e0b"
down_revision = "2c60e0f613b9_add_tempo_columns_to_turmas"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "aulas_alunos",
        sa.Column("falta_disciplinar", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("aulas_alunos", "falta_disciplinar", server_default=None)


def downgrade():
    op.drop_column("aulas_alunos", "falta_disciplinar")
