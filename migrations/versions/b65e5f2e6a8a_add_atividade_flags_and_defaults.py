"""add atividade flags and default notas 3

Revision ID: b65e5f2e6a8a
Revises: e5d9d0d2d9f8
Create Date: 2025-02-21
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b65e5f2e6a8a"
down_revision = "e5d9d0d2d9f8"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("calendario_aulas") as batch:
        batch.add_column(sa.Column("atividade", sa.Boolean(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("atividade_nome", sa.Text(), nullable=True))

    for campo in [
        "responsabilidade",
        "comportamento",
        "participacao",
        "trabalho_autonomo",
        "portatil_material",
        "atividade",
    ]:
        op.alter_column(
            "aulas_alunos",
            campo,
            existing_type=sa.Integer(),
            server_default="3",
            existing_nullable=True,
        )
        op.execute(
            sa.text(
                f"UPDATE aulas_alunos SET {campo}=3 WHERE {campo} IS NULL"
            )
        )


def downgrade():
    for campo in [
        "responsabilidade",
        "comportamento",
        "participacao",
        "trabalho_autonomo",
        "portatil_material",
        "atividade",
    ]:
        op.alter_column(
            "aulas_alunos",
            campo,
            existing_type=sa.Integer(),
            server_default="5",
            existing_nullable=True,
        )

    with op.batch_alter_table("calendario_aulas") as batch:
        batch.drop_column("atividade_nome")
        batch.drop_column("atividade")
