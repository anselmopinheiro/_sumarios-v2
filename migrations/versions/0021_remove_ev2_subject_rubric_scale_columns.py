"""remove ev2 subject rubric scale columns

Revision ID: 0021_remove_ev2_subject_rubric_scale_columns
Revises: 0020_ev2_profile_type_semantics
Create Date: 2026-03-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0021_remove_ev2_subject_rubric_scale_columns"
down_revision = "0020_ev2_profile_type_semantics"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("ev2_subject_rubrics") as batch_op:
        batch_op.drop_constraint("ck_ev2_subject_rubric_scale", type_="check")
        batch_op.drop_column("scale_min")
        batch_op.drop_column("scale_max")


def downgrade():
    with op.batch_alter_table("ev2_subject_rubrics") as batch_op:
        batch_op.add_column(sa.Column("scale_min", sa.Integer(), nullable=True, server_default="1"))
        batch_op.add_column(sa.Column("scale_max", sa.Integer(), nullable=True, server_default="5"))

    bind = op.get_bind()
    bind.execute(
        text(
            """
            UPDATE ev2_subject_rubrics AS sr
            SET scale_min = COALESCE(
                    (SELECT sc.escala_min FROM ev2_subject_configs AS sc WHERE sc.id = sr.subject_config_id),
                    1
                ),
                scale_max = COALESCE(
                    (SELECT sc.escala_max FROM ev2_subject_configs AS sc WHERE sc.id = sr.subject_config_id),
                    5
                )
            """
        )
    )
    bind.execute(text("UPDATE ev2_subject_rubrics SET scale_min = 1 WHERE scale_min IS NULL"))
    bind.execute(text("UPDATE ev2_subject_rubrics SET scale_max = 5 WHERE scale_max IS NULL"))

    with op.batch_alter_table("ev2_subject_rubrics") as batch_op:
        batch_op.alter_column("scale_min", existing_type=sa.Integer(), nullable=False, server_default="1")
        batch_op.alter_column("scale_max", existing_type=sa.Integer(), nullable=False, server_default="5")
        batch_op.create_check_constraint("ck_ev2_subject_rubric_scale", "scale_min < scale_max")
