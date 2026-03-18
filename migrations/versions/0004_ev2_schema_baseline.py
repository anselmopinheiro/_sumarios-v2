"""add ev2 schema baseline tables

Revision ID: 0004_ev2_schema_baseline
Revises: 0003_dt_contacts_and_ee_foundation
Create Date: 2026-03-17
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_ev2_schema_baseline"
down_revision = "0003_dt_contacts_and_ee_foundation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ev2_domains",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nome", sa.String(length=120), nullable=False),
        sa.Column("descricao", sa.Text(), nullable=True),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nome"),
    )

    op.create_table(
        "ev2_extra_params",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("codigo", sa.String(length=80), nullable=False),
        sa.Column("nome", sa.String(length=140), nullable=False),
        sa.Column("descricao", sa.Text(), nullable=True),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("codigo"),
    )

    op.create_table(
        "ev2_rubrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("domain_id", sa.Integer(), nullable=False),
        sa.Column("codigo", sa.String(length=80), nullable=False),
        sa.Column("nome", sa.String(length=140), nullable=False),
        sa.Column("descricao", sa.Text(), nullable=True),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(["domain_id"], ["ev2_domains.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("domain_id", "codigo", name="uq_ev2_rubric_domain_codigo"),
    )
    op.create_index("ix_ev2_rubrics_domain", "ev2_rubrics", ["domain_id"])

    op.create_table(
        "ev2_subject_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("turma_id", sa.Integer(), nullable=False),
        sa.Column("disciplina_id", sa.Integer(), nullable=False),
        sa.Column("nome", sa.String(length=140), nullable=False),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("usar_ev2", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["disciplina_id"], ["disciplinas.id"]),
        sa.ForeignKeyConstraint(["turma_id"], ["turmas.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("turma_id", "disciplina_id", "nome", name="uq_ev2_subject_cfg_nome"),
    )
    op.create_index(
        "ix_ev2_subject_cfg_turma_disciplina",
        "ev2_subject_configs",
        ["turma_id", "disciplina_id"],
    )

    op.create_table(
        "ev2_subject_type_weights",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subject_config_id", sa.Integer(), nullable=False),
        sa.Column("evaluation_type", sa.String(length=32), nullable=False),
        sa.Column("weight", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.CheckConstraint(
            "evaluation_type IN ('observacao_direta','portfolio','projetos','trabalhos')",
            name="ck_ev2_subject_weight_type",
        ),
        sa.CheckConstraint("weight >= 0 AND weight <= 100", name="ck_ev2_subject_weight_range"),
        sa.ForeignKeyConstraint(["subject_config_id"], ["ev2_subject_configs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subject_config_id", "evaluation_type", name="uq_ev2_subject_weight_type"),
    )
    op.create_index(
        "ix_ev2_subject_weight_config",
        "ev2_subject_type_weights",
        ["subject_config_id"],
    )

    op.create_table(
        "ev2_subject_rubrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subject_config_id", sa.Integer(), nullable=False),
        sa.Column("rubric_id", sa.Integer(), nullable=False),
        sa.Column("weight", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("scale_min", sa.Integer(), nullable=False),
        sa.Column("scale_max", sa.Integer(), nullable=False),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.CheckConstraint("weight >= 0 AND weight <= 100", name="ck_ev2_subject_rubric_weight"),
        sa.CheckConstraint("scale_min < scale_max", name="ck_ev2_subject_rubric_scale"),
        sa.ForeignKeyConstraint(["rubric_id"], ["ev2_rubrics.id"]),
        sa.ForeignKeyConstraint(["subject_config_id"], ["ev2_subject_configs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subject_config_id", "rubric_id", name="uq_ev2_subject_rubric_once"),
    )
    op.create_index(
        "ix_ev2_subject_rubric_config",
        "ev2_subject_rubrics",
        ["subject_config_id"],
    )

    op.create_table(
        "ev2_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subject_config_id", sa.Integer(), nullable=False),
        sa.Column("disciplina_id", sa.Integer(), nullable=False),
        sa.Column("aula_id", sa.Integer(), nullable=True),
        sa.Column("evaluation_type", sa.String(length=32), nullable=False),
        sa.Column("titulo", sa.String(length=255), nullable=False),
        sa.Column("descricao", sa.Text(), nullable=True),
        sa.Column("data", sa.Date(), nullable=False),
        sa.Column("group_mode", sa.String(length=20), nullable=False, server_default="individual"),
        sa.Column("peso_evento", sa.Numeric(precision=5, scale=2), nullable=False, server_default="100"),
        sa.Column("extra_component_weight", sa.Numeric(precision=5, scale=2), nullable=False, server_default="0"),
        sa.Column("config_snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint(
            "evaluation_type IN ('observacao_direta','portfolio','projetos','trabalhos')",
            name="ck_ev2_event_type",
        ),
        sa.CheckConstraint("group_mode IN ('individual','grupo')", name="ck_ev2_event_group_mode"),
        sa.CheckConstraint("peso_evento >= 0 AND peso_evento <= 100", name="ck_ev2_event_peso"),
        sa.CheckConstraint(
            "extra_component_weight >= 0 AND extra_component_weight <= 100",
            name="ck_ev2_event_extra_weight",
        ),
        sa.ForeignKeyConstraint(["aula_id"], ["calendario_aulas.id"]),
        sa.ForeignKeyConstraint(["disciplina_id"], ["disciplinas.id"]),
        sa.ForeignKeyConstraint(["subject_config_id"], ["ev2_subject_configs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ev2_events_config_data", "ev2_events", ["subject_config_id", "data"])
    op.create_index("ix_ev2_events_disciplina_data", "ev2_events", ["disciplina_id", "data"])
    op.create_index("ix_ev2_events_aula_type", "ev2_events", ["aula_id", "evaluation_type"])
    op.create_index("ix_ev2_events_aula_data", "ev2_events", ["aula_id", "data"])

    op.create_table(
        "ev2_event_students",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("aluno_id", sa.Integer(), nullable=False),
        sa.Column("group_key", sa.String(length=80), nullable=True),
        sa.Column("tempos_totais", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("tempos_presentes", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("estado_assiduidade", sa.String(length=20), nullable=False, server_default="presente_total"),
        sa.Column("pontualidade_manual", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("elegivel_avaliacao", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("observacoes", sa.Text(), nullable=True),
        sa.CheckConstraint("tempos_totais >= 1", name="ck_ev2_event_student_tempos_totais"),
        sa.CheckConstraint(
            "tempos_presentes >= 0 AND tempos_presentes <= tempos_totais",
            name="ck_ev2_event_student_tempos_presentes",
        ),
        sa.CheckConstraint(
            "estado_assiduidade IN ('presente_total','parcial','ausente_total')",
            name="ck_ev2_event_student_estado_assiduidade",
        ),
        sa.ForeignKeyConstraint(["aluno_id"], ["alunos.id"]),
        sa.ForeignKeyConstraint(["event_id"], ["ev2_events.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "aluno_id", name="uq_ev2_event_student"),
    )
    op.create_index("ix_ev2_event_students_event", "ev2_event_students", ["event_id"])
    op.create_index("ix_ev2_event_students_aluno", "ev2_event_students", ["aluno_id"])
    op.create_index(
        "ix_ev2_event_students_aluno_event",
        "ev2_event_students",
        ["aluno_id", "event_id"],
    )

    op.create_table(
        "ev2_assessments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_student_id", sa.Integer(), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("rubric_id", sa.Integer(), nullable=True),
        sa.Column("extra_param_id", sa.Integer(), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="nao_observado"),
        sa.Column("score_numeric", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("weight", sa.Numeric(precision=5, scale=2), nullable=False, server_default="0"),
        sa.Column("counts_for_grade", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("observacoes", sa.Text(), nullable=True),
        sa.CheckConstraint("tipo IN ('rubrica','extra_param')", name="ck_ev2_assessment_tipo"),
        sa.CheckConstraint("state IN ('avaliado','ausente','nao_observado')", name="ck_ev2_assessment_state"),
        sa.CheckConstraint("weight >= 0 AND weight <= 100", name="ck_ev2_assessment_weight"),
        sa.CheckConstraint(
            "(rubric_id IS NOT NULL AND extra_param_id IS NULL) OR "
            "(rubric_id IS NULL AND extra_param_id IS NOT NULL)",
            name="ck_ev2_assessment_target_one",
        ),
        sa.CheckConstraint(
            "(tipo = 'rubrica' AND rubric_id IS NOT NULL AND extra_param_id IS NULL) OR "
            "(tipo = 'extra_param' AND rubric_id IS NULL AND extra_param_id IS NOT NULL)",
            name="ck_ev2_assessment_tipo_target",
        ),
        sa.CheckConstraint(
            "(state = 'avaliado' AND score_numeric IS NOT NULL) OR "
            "(state IN ('ausente','nao_observado') AND score_numeric IS NULL)",
            name="ck_ev2_assessment_state_score",
        ),
        sa.ForeignKeyConstraint(["event_student_id"], ["ev2_event_students.id"]),
        sa.ForeignKeyConstraint(["extra_param_id"], ["ev2_extra_params.id"]),
        sa.ForeignKeyConstraint(["rubric_id"], ["ev2_rubrics.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_student_id", "extra_param_id", name="uq_ev2_assessment_student_extra"),
        sa.UniqueConstraint("event_student_id", "rubric_id", name="uq_ev2_assessment_student_rubric"),
    )
    op.create_index("ix_ev2_assessments_student", "ev2_assessments", ["event_student_id"])
    op.create_index(
        "ix_ev2_assessments_student_tipo",
        "ev2_assessments",
        ["event_student_id", "tipo"],
    )
    op.create_index("ix_ev2_assessments_rubric", "ev2_assessments", ["rubric_id"])
    op.create_index("ix_ev2_assessments_extra", "ev2_assessments", ["extra_param_id"])
    op.create_index("ix_ev2_assessments_state", "ev2_assessments", ["state"])


def downgrade():
    op.drop_index("ix_ev2_assessments_state", table_name="ev2_assessments")
    op.drop_index("ix_ev2_assessments_extra", table_name="ev2_assessments")
    op.drop_index("ix_ev2_assessments_rubric", table_name="ev2_assessments")
    op.drop_index("ix_ev2_assessments_student_tipo", table_name="ev2_assessments")
    op.drop_index("ix_ev2_assessments_student", table_name="ev2_assessments")
    op.drop_table("ev2_assessments")

    op.drop_index("ix_ev2_event_students_aluno_event", table_name="ev2_event_students")
    op.drop_index("ix_ev2_event_students_aluno", table_name="ev2_event_students")
    op.drop_index("ix_ev2_event_students_event", table_name="ev2_event_students")
    op.drop_table("ev2_event_students")

    op.drop_index("ix_ev2_events_aula_data", table_name="ev2_events")
    op.drop_index("ix_ev2_events_aula_type", table_name="ev2_events")
    op.drop_index("ix_ev2_events_disciplina_data", table_name="ev2_events")
    op.drop_index("ix_ev2_events_config_data", table_name="ev2_events")
    op.drop_table("ev2_events")

    op.drop_index("ix_ev2_subject_rubric_config", table_name="ev2_subject_rubrics")
    op.drop_table("ev2_subject_rubrics")

    op.drop_index("ix_ev2_subject_weight_config", table_name="ev2_subject_type_weights")
    op.drop_table("ev2_subject_type_weights")

    op.drop_index("ix_ev2_subject_cfg_turma_disciplina", table_name="ev2_subject_configs")
    op.drop_table("ev2_subject_configs")

    op.drop_index("ix_ev2_rubrics_domain", table_name="ev2_rubrics")
    op.drop_table("ev2_rubrics")

    op.drop_table("ev2_extra_params")
    op.drop_table("ev2_domains")
