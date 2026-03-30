"""ev2 subject config by turma

Revision ID: 0017_ev2_subject_config_by_turma
Revises: 0016_ev2_profile_domains_and_rubric_order
Create Date: 2026-03-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0017_ev2_subject_config_by_turma"
down_revision = "0016_ev2_profile_domains_and_rubric_order"
branch_labels = None
depends_on = None


def _dedupe_turma_nome(bind):
    rows = bind.execute(
        text(
            """
            SELECT id, turma_id, nome
            FROM ev2_subject_configs
            ORDER BY turma_id ASC, nome ASC, updated_at DESC, id DESC
            """
        )
    ).fetchall()

    seen = set()
    updates = []
    for row in rows:
        key = (row.turma_id, row.nome)
        if key not in seen:
            seen.add(key)
            continue

        suffix_idx = 2
        new_name = f"{row.nome} [{suffix_idx}]"
        while (row.turma_id, new_name) in seen:
            suffix_idx += 1
            new_name = f"{row.nome} [{suffix_idx}]"
        seen.add((row.turma_id, new_name))
        updates.append((row.id, new_name))

    for row_id, new_name in updates:
        bind.execute(
            text("UPDATE ev2_subject_configs SET nome = :nome WHERE id = :id"),
            {"id": row_id, "nome": new_name},
        )


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    _dedupe_turma_nome(bind)

    uniques = {u["name"] for u in insp.get_unique_constraints("ev2_subject_configs")}
    indexes = {i["name"] for i in insp.get_indexes("ev2_subject_configs")}

    with op.batch_alter_table("ev2_subject_configs") as batch_op:
        if "uq_ev2_subject_cfg_nome" in uniques:
            batch_op.drop_constraint("uq_ev2_subject_cfg_nome", type_="unique")
        batch_op.alter_column("disciplina_id", existing_type=sa.Integer(), nullable=True)
        batch_op.create_unique_constraint(
            "uq_ev2_subject_cfg_turma_nome",
            ["turma_id", "nome"],
        )

    if "ix_ev2_subject_cfg_turma_disciplina" in indexes:
        op.drop_index("ix_ev2_subject_cfg_turma_disciplina", table_name="ev2_subject_configs")
    if "ix_ev2_subject_cfg_turma" not in indexes:
        op.create_index("ix_ev2_subject_cfg_turma", "ev2_subject_configs", ["turma_id"])


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    uniques = {u["name"] for u in insp.get_unique_constraints("ev2_subject_configs")}
    indexes = {i["name"] for i in insp.get_indexes("ev2_subject_configs")}

    with op.batch_alter_table("ev2_subject_configs") as batch_op:
        if "uq_ev2_subject_cfg_turma_nome" in uniques:
            batch_op.drop_constraint("uq_ev2_subject_cfg_turma_nome", type_="unique")
        batch_op.alter_column("disciplina_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_unique_constraint(
            "uq_ev2_subject_cfg_nome",
            ["turma_id", "disciplina_id", "nome"],
        )

    if "ix_ev2_subject_cfg_turma" in indexes:
        op.drop_index("ix_ev2_subject_cfg_turma", table_name="ev2_subject_configs")
    if "ix_ev2_subject_cfg_turma_disciplina" not in indexes:
        op.create_index(
            "ix_ev2_subject_cfg_turma_disciplina",
            "ev2_subject_configs",
            ["turma_id", "disciplina_id"],
        )
