"""add observacoes to aulas_alunos

Revision ID: f9b2c7d4e1a0
Revises: de9f4a2b7c1e
Create Date: 2026-02-23 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f9b2c7d4e1a0"
down_revision = "de9f4a2b7c1e"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("aulas_alunos", sa.Column("observacoes", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("aulas_alunos", "observacoes")
