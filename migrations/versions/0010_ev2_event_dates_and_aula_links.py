"""ev2 event dates and aula links

Revision ID: 0010_ev2_event_dates_and_aula_links
Revises: 0009_ev2_event_number_and_groups
Create Date: 2026-03-20
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_ev2_event_dates_and_aula_links"
down_revision = "0009_ev2_event_number_and_groups"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ev2_events", sa.Column("data_inicio", sa.Date(), nullable=True))
    op.add_column("ev2_events", sa.Column("prazo_entrega", sa.Date(), nullable=True))
    op.create_index("ix_ev2_events_tipo_numero", "ev2_events", ["evaluation_type", "numero"])

    op.create_table(
        "ev2_aula_event_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("aula_id", sa.Integer(), sa.ForeignKey("calendario_aulas.id"), nullable=False),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("ev2_events.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("aula_id", "event_id", name="uq_ev2_aula_event_once"),
    )
    op.create_index("ix_ev2_aula_event_aula", "ev2_aula_event_links", ["aula_id"])
    op.create_index("ix_ev2_aula_event_event", "ev2_aula_event_links", ["event_id"])


def downgrade():
    op.drop_index("ix_ev2_aula_event_event", table_name="ev2_aula_event_links")
    op.drop_index("ix_ev2_aula_event_aula", table_name="ev2_aula_event_links")
    op.drop_table("ev2_aula_event_links")
    op.drop_index("ix_ev2_events_tipo_numero", table_name="ev2_events")
    op.drop_column("ev2_events", "prazo_entrega")
    op.drop_column("ev2_events", "data_inicio")
