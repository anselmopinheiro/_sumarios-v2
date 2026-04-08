"""ev2 rubric descriptors and components

Revision ID: 0023_ev2_rubric_descriptors_and_components
Revises: 0022_add_ordem_peso_to_ev2_rubrics
Create Date: 2026-04-08
"""

from alembic import op
import sqlalchemy as sa

revision = "0023_ev2_rubric_descriptors_and_components"
down_revision = "0022_add_ordem_peso_to_ev2_rubrics"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("ev2_rubrics") as batch_op:
        batch_op.add_column(sa.Column("descritor_nivel_1", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("descritor_nivel_2", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("descritor_nivel_3", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("descritor_nivel_4", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("descritor_nivel_5", sa.Text(), nullable=True))

    op.create_table(
        "ev2_rubric_components",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rubrica_id", sa.Integer(), nullable=False),
        sa.Column("nome", sa.String(length=140), nullable=False),
        sa.Column("ordem", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("peso", sa.Numeric(precision=5, scale=2), nullable=False, server_default="0"),
        sa.Column("descritor_nivel_1", sa.Text(), nullable=True),
        sa.Column("descritor_nivel_2", sa.Text(), nullable=True),
        sa.Column("descritor_nivel_3", sa.Text(), nullable=True),
        sa.Column("descritor_nivel_4", sa.Text(), nullable=True),
        sa.Column("descritor_nivel_5", sa.Text(), nullable=True),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.CheckConstraint("peso >= 0 AND peso <= 100", name="ck_ev2_rubric_component_peso"),
        sa.ForeignKeyConstraint(["rubrica_id"], ["ev2_rubrics.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ev2_rubric_components_rubrica_id", "ev2_rubric_components", ["rubrica_id"], unique=False)
    op.create_index("ix_ev2_rubric_components_rubrica_ordem", "ev2_rubric_components", ["rubrica_id", "ordem"], unique=False)

    op.create_table(
        "ev2_assessment_component_scores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("assessment_id", sa.Integer(), nullable=False),
        sa.Column("component_id", sa.Integer(), nullable=False),
        sa.Column("score_level", sa.Integer(), nullable=False),
        sa.CheckConstraint("score_level >= 1 AND score_level <= 5", name="ck_ev2_assessment_component_score"),
        sa.ForeignKeyConstraint(["assessment_id"], ["ev2_assessments.id"]),
        sa.ForeignKeyConstraint(["component_id"], ["ev2_rubric_components.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "component_id", name="uq_ev2_assessment_component_once"),
    )
    op.create_index("ix_ev2_assessment_component_scores_assessment_id", "ev2_assessment_component_scores", ["assessment_id"], unique=False)
    op.create_index("ix_ev2_assessment_component_scores_component_id", "ev2_assessment_component_scores", ["component_id"], unique=False)


def downgrade():
    op.drop_index("ix_ev2_assessment_component_scores_component_id", table_name="ev2_assessment_component_scores")
    op.drop_index("ix_ev2_assessment_component_scores_assessment_id", table_name="ev2_assessment_component_scores")
    op.drop_table("ev2_assessment_component_scores")

    op.drop_index("ix_ev2_rubric_components_rubrica_ordem", table_name="ev2_rubric_components")
    op.drop_index("ix_ev2_rubric_components_rubrica_id", table_name="ev2_rubric_components")
    op.drop_table("ev2_rubric_components")

    with op.batch_alter_table("ev2_rubrics") as batch_op:
        batch_op.drop_column("descritor_nivel_5")
        batch_op.drop_column("descritor_nivel_4")
        batch_op.drop_column("descritor_nivel_3")
        batch_op.drop_column("descritor_nivel_2")
        batch_op.drop_column("descritor_nivel_1")
