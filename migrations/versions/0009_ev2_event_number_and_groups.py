"""add ev2 event number and evaluation groups

Revision ID: 0009_ev2_event_number_and_groups
Revises: 0008_ev2_domain_codigo
Create Date: 2026-03-20
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_ev2_event_number_and_groups"
down_revision = "0008_ev2_domain_codigo"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ev2_events", sa.Column("numero", sa.Integer(), nullable=True))

    op.create_table(
        "ev2_evaluation_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("ev2_events.id"), nullable=False),
        sa.Column("nome", sa.String(length=120), nullable=False),
        sa.Column("ordem", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("event_id", "nome", name="uq_ev2_eval_group_event_nome"),
    )
    op.create_index("ix_ev2_eval_group_event_ordem", "ev2_evaluation_groups", ["event_id", "ordem"])

    op.create_table(
        "ev2_evaluation_group_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("ev2_evaluation_groups.id"), nullable=False),
        sa.Column("aluno_id", sa.Integer(), sa.ForeignKey("alunos.id"), nullable=False),
        sa.UniqueConstraint("group_id", "aluno_id", name="uq_ev2_eval_group_member_once"),
    )
    op.create_index("ix_ev2_eval_group_member_group", "ev2_evaluation_group_members", ["group_id"])


def downgrade():
    op.drop_index("ix_ev2_eval_group_member_group", table_name="ev2_evaluation_group_members")
    op.drop_table("ev2_evaluation_group_members")
    op.drop_index("ix_ev2_eval_group_event_ordem", table_name="ev2_evaluation_groups")
    op.drop_table("ev2_evaluation_groups")
    op.drop_column("ev2_events", "numero")
