"""add ordem and peso to ev2 rubrics

Revision ID: 0022_add_ordem_peso_to_ev2_rubrics
Revises: 0021_remove_ev2_subject_rubric_scale_columns
Create Date: 2026-03-30
"""

from alembic import op
import sqlalchemy as sa

revision = "0022_add_ordem_peso_to_ev2_rubrics"
down_revision = "0021_remove_ev2_subject_rubric_scale_columns"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("ev2_rubrics") as batch_op:
        batch_op.add_column(sa.Column("ordem", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("peso", sa.Numeric(precision=5, scale=2), nullable=False, server_default="0"))
        batch_op.create_check_constraint("ck_ev2_rubric_peso", "peso >= 0 AND peso <= 100")


def downgrade():
    with op.batch_alter_table("ev2_rubrics") as batch_op:
        batch_op.drop_constraint("ck_ev2_rubric_peso", type_="check")
        batch_op.drop_column("peso")
        batch_op.drop_column("ordem")
