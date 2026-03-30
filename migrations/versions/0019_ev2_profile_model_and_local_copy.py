"""ev2 profile model and local copy

Revision ID: 0019_ev2_profile_model_and_local_copy
Revises: 0018_ev2_profile_scale_on_subject_config
Create Date: 2026-03-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0019_ev2_profile_model_and_local_copy"
down_revision = "0018_ev2_profile_scale_on_subject_config"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("ev2_subject_configs") as batch_op:
        batch_op.add_column(sa.Column("tipo", sa.String(length=16), nullable=True, server_default="local"))
        batch_op.add_column(sa.Column("profile_model_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_ev2_subject_cfg_profile_model",
            "ev2_subject_configs",
            ["profile_model_id"],
            ["id"],
        )
        batch_op.alter_column("turma_id", existing_type=sa.Integer(), nullable=True)

    bind = op.get_bind()
    bind.execute(text("UPDATE ev2_subject_configs SET tipo = 'local' WHERE tipo IS NULL"))

    rows = bind.execute(
        text(
            """
            SELECT id, nome, disciplina_id, escala_min, escala_max
            FROM ev2_subject_configs
            WHERE tipo='local'
            ORDER BY id ASC
            """
        )
    ).fetchall()

    for row in rows:
        model_name = f"Modelo {row.nome}"
        model_id = bind.execute(
            text(
                """
                INSERT INTO ev2_subject_configs
                (turma_id, disciplina_id, nome, tipo, profile_model_id, ativo, usar_ev2, escala_min, escala_max, created_at, updated_at)
                VALUES (NULL, :disciplina_id, :nome, 'modelo', NULL, 1, 0, :escala_min, :escala_max, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                RETURNING id
                """
            ),
            {
                "disciplina_id": row.disciplina_id,
                "nome": model_name,
                "escala_min": row.escala_min,
                "escala_max": row.escala_max,
            },
        ).scalar()

        bind.execute(
            text(
                """
                INSERT INTO ev2_subject_domains (subject_config_id, domain_id, ordem, weight, ativo)
                SELECT :model_id, domain_id, ordem, weight, ativo
                FROM ev2_subject_domains
                WHERE subject_config_id = :local_id
                """
            ),
            {"model_id": model_id, "local_id": row.id},
        )
        bind.execute(
            text(
                """
                INSERT INTO ev2_subject_rubrics
                (subject_config_id, rubric_id, subject_domain_id, ordem, weight, scale_min, scale_max, ativo)
                SELECT :model_id, rubric_id, NULL, ordem, weight, scale_min, scale_max, ativo
                FROM ev2_subject_rubrics
                WHERE subject_config_id = :local_id
                """
            ),
            {"model_id": model_id, "local_id": row.id},
        )
        bind.execute(
            text(
                "UPDATE ev2_subject_configs SET profile_model_id = :model_id WHERE id = :local_id"
            ),
            {"model_id": model_id, "local_id": row.id},
        )

    with op.batch_alter_table("ev2_subject_configs") as batch_op:
        batch_op.alter_column("tipo", existing_type=sa.String(length=16), nullable=False, server_default="local")
        batch_op.drop_constraint("uq_ev2_subject_cfg_turma_nome", type_="unique")
        batch_op.create_unique_constraint(
            "uq_ev2_subject_cfg_turma_nome_tipo",
            ["turma_id", "nome", "tipo"],
        )
        batch_op.create_check_constraint("ck_ev2_subject_cfg_tipo", "tipo IN ('modelo','local')")

    op.create_index("ix_ev2_subject_cfg_tipo", "ev2_subject_configs", ["tipo"])
    op.create_index("ix_ev2_subject_cfg_profile_model_id", "ev2_subject_configs", ["profile_model_id"])


def downgrade():
    op.drop_index("ix_ev2_subject_cfg_profile_model_id", table_name="ev2_subject_configs")
    op.drop_index("ix_ev2_subject_cfg_tipo", table_name="ev2_subject_configs")

    with op.batch_alter_table("ev2_subject_configs") as batch_op:
        batch_op.drop_constraint("ck_ev2_subject_cfg_tipo", type_="check")
        batch_op.drop_constraint("uq_ev2_subject_cfg_turma_nome_tipo", type_="unique")
        batch_op.create_unique_constraint("uq_ev2_subject_cfg_turma_nome", ["turma_id", "nome"])
        batch_op.drop_constraint("fk_ev2_subject_cfg_profile_model", type_="foreignkey")
        batch_op.drop_column("profile_model_id")
        batch_op.drop_column("tipo")
        batch_op.alter_column("turma_id", existing_type=sa.Integer(), nullable=False)
