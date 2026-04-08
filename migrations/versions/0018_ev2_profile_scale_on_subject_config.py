"""ev2 profile scale on subject config

Revision ID: 0018_ev2_profile_scale_on_subject_config
Revises: 0017_ev2_subject_config_by_turma
Create Date: 2026-03-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0018_ev2_profile_scale_on_subject_config"
down_revision = "0017_ev2_subject_config_by_turma"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("ev2_subject_configs") as batch_op:
        batch_op.add_column(sa.Column("escala_min", sa.Integer(), nullable=True, server_default="1"))
        batch_op.add_column(sa.Column("escala_max", sa.Integer(), nullable=True, server_default="5"))

    bind = op.get_bind()
    bind.execute(
        text(
            """
            UPDATE ev2_subject_configs AS cfg
            SET
              escala_min = COALESCE(
                (
                  SELECT MIN(sr.scale_min)
                  FROM ev2_subject_rubrics sr
                  WHERE sr.subject_config_id = cfg.id
                ),
                1
              ),
              escala_max = COALESCE(
                (
                  SELECT MAX(sr.scale_max)
                  FROM ev2_subject_rubrics sr
                  WHERE sr.subject_config_id = cfg.id
                ),
                5
              )
            """
        )
    )
    bind.execute(text("UPDATE ev2_subject_configs SET escala_min = 1 WHERE escala_min IS NULL"))
    bind.execute(text("UPDATE ev2_subject_configs SET escala_max = 5 WHERE escala_max IS NULL"))

    with op.batch_alter_table("ev2_subject_configs") as batch_op:
        batch_op.alter_column("escala_min", existing_type=sa.Integer(), nullable=False, server_default="1")
        batch_op.alter_column("escala_max", existing_type=sa.Integer(), nullable=False, server_default="5")
        batch_op.create_check_constraint("ck_ev2_subject_cfg_scale", "escala_min < escala_max")


def downgrade():
    with op.batch_alter_table("ev2_subject_configs") as batch_op:
        batch_op.drop_constraint("ck_ev2_subject_cfg_scale", type_="check")
        batch_op.drop_column("escala_max")
        batch_op.drop_column("escala_min")
