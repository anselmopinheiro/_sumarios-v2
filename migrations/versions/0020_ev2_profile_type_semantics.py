"""ev2 profile type semantics

Revision ID: 0020_ev2_profile_type_semantics
Revises: 0019_ev2_profile_model_and_local_copy
Create Date: 2026-03-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0020_ev2_profile_type_semantics"
down_revision = "0019_ev2_profile_model_and_local_copy"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("ev2_subject_configs") as batch_op:
        batch_op.drop_constraint("ck_ev2_subject_cfg_tipo", type_="check")
        batch_op.create_check_constraint(
            "ck_ev2_subject_cfg_tipo_transitional",
            "tipo IN ('modelo','local','perfil_base_turma','modelo_atividade','local_turma')",
        )

    bind = op.get_bind()
    # Mapeamentos legados -> novos
    bind.execute(text("UPDATE ev2_subject_configs SET tipo='perfil_base_turma' WHERE tipo='modelo'"))
    bind.execute(text("UPDATE ev2_subject_configs SET tipo='local_turma' WHERE tipo='local'"))
    # Hardening para quaisquer valores antigos inesperados.
    bind.execute(
        text(
            """
            UPDATE ev2_subject_configs
            SET tipo='perfil_base_turma'
            WHERE tipo NOT IN ('perfil_base_turma','modelo_atividade','local_turma')
            """
        )
    )

    with op.batch_alter_table("ev2_subject_configs") as batch_op:
        batch_op.drop_constraint("ck_ev2_subject_cfg_tipo_transitional", type_="check")
        batch_op.create_check_constraint(
            "ck_ev2_subject_cfg_tipo",
            "tipo IN ('perfil_base_turma','modelo_atividade','local_turma')",
        )


def downgrade():
    with op.batch_alter_table("ev2_subject_configs") as batch_op:
        batch_op.drop_constraint("ck_ev2_subject_cfg_tipo", type_="check")
        batch_op.create_check_constraint(
            "ck_ev2_subject_cfg_tipo_transitional",
            "tipo IN ('modelo','local','perfil_base_turma','modelo_atividade','local_turma')",
        )

    bind = op.get_bind()
    bind.execute(text("UPDATE ev2_subject_configs SET tipo='modelo' WHERE tipo IN ('perfil_base_turma','modelo_atividade')"))
    bind.execute(text("UPDATE ev2_subject_configs SET tipo='local' WHERE tipo='local_turma'"))
    bind.execute(
        text(
            """
            UPDATE ev2_subject_configs
            SET tipo='modelo'
            WHERE tipo NOT IN ('modelo','local')
            """
        )
    )

    with op.batch_alter_table("ev2_subject_configs") as batch_op:
        batch_op.drop_constraint("ck_ev2_subject_cfg_tipo_transitional", type_="check")
        batch_op.create_check_constraint(
            "ck_ev2_subject_cfg_tipo",
            "tipo IN ('modelo','local')",
        )
