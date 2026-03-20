"""add optional grupo_turma_id to ev2_aula_event_links

Revision ID: 0011_ev2_aula_event_group_scope
Revises: 0010_ev2_event_dates_and_aula_links
Create Date: 2026-03-20
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_ev2_aula_event_group_scope"
down_revision = "0010_ev2_event_dates_and_aula_links"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("ev2_aula_event_links") as batch_op:
        batch_op.add_column(sa.Column("grupo_turma_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_ev2_aula_event_grupo", ["grupo_turma_id"], unique=False)
        batch_op.drop_constraint("uq_ev2_aula_event_once", type_="unique")
        batch_op.create_unique_constraint(
            "uq_ev2_aula_event_once", ["aula_id", "event_id", "grupo_turma_id"]
        )
        batch_op.create_foreign_key(
            "fk_ev2_aula_event_group_turma",
            "grupos_turma",
            ["grupo_turma_id"],
            ["id"],
        )


def downgrade():
    with op.batch_alter_table("ev2_aula_event_links") as batch_op:
        batch_op.drop_constraint("fk_ev2_aula_event_group_turma", type_="foreignkey")
        batch_op.drop_constraint("uq_ev2_aula_event_once", type_="unique")
        batch_op.create_unique_constraint("uq_ev2_aula_event_once", ["aula_id", "event_id"])
        batch_op.drop_index("ix_ev2_aula_event_grupo")
        batch_op.drop_column("grupo_turma_id")
