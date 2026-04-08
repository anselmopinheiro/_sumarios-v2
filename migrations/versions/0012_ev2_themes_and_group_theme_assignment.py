"""add EV2 themes and aula group-theme assignment

Revision ID: 0012_ev2_themes_and_group_theme_assignment
Revises: 0011_ev2_aula_event_group_scope
Create Date: 2026-03-20
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_ev2_themes_and_group_theme_assignment"
down_revision = "0011_ev2_aula_event_group_scope"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("ev2_events") as batch_op:
        batch_op.add_column(sa.Column("tema_multiplo", sa.Boolean(), nullable=False, server_default=sa.text("0")))

    op.create_table(
        "ev2_event_themes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("ev2_events.id"), nullable=False),
        sa.Column("nome_tema", sa.String(length=255), nullable=False),
        sa.Column("descricao", sa.Text(), nullable=True),
        sa.Column("ordem", sa.Integer(), nullable=True),
        sa.UniqueConstraint("event_id", "nome_tema", name="uq_ev2_event_theme_nome"),
    )
    op.create_index("ix_ev2_event_theme_event_ordem", "ev2_event_themes", ["event_id", "ordem"], unique=False)

    op.create_table(
        "ev2_aula_theme_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("aula_id", sa.Integer(), sa.ForeignKey("calendario_aulas.id"), nullable=False),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("ev2_events.id"), nullable=False),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("ev2_evaluation_groups.id"), nullable=False),
        sa.Column("theme_id", sa.Integer(), sa.ForeignKey("ev2_event_themes.id"), nullable=True),
        sa.Column("entregue", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("data_entrega", sa.Date(), nullable=True),
        sa.Column("observacoes", sa.Text(), nullable=True),
        sa.UniqueConstraint("aula_id", "event_id", "group_id", name="uq_ev2_aula_theme_assignment"),
    )
    op.create_index("ix_ev2_aula_theme_assignment_aula_event", "ev2_aula_theme_assignments", ["aula_id", "event_id"], unique=False)


def downgrade():
    op.drop_index("ix_ev2_aula_theme_assignment_aula_event", table_name="ev2_aula_theme_assignments")
    op.drop_table("ev2_aula_theme_assignments")
    op.drop_index("ix_ev2_event_theme_event_ordem", table_name="ev2_event_themes")
    op.drop_table("ev2_event_themes")
    with op.batch_alter_table("ev2_events") as batch_op:
        batch_op.drop_column("tema_multiplo")
