"""ev2 profile domain associations and rubric ordering

Revision ID: 0016_ev2_profile_domains_and_rubric_order
Revises: 0015_trabalho_tipo_and_optional_domain_models
Create Date: 2026-03-21
"""

from alembic import op
import sqlalchemy as sa

revision = "0016_ev2_profile_domains_and_rubric_order"
down_revision = "0015_trabalho_tipo_and_optional_domain_models"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ev2_subject_domains",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subject_config_id", sa.Integer(), sa.ForeignKey("ev2_subject_configs.id"), nullable=False),
        sa.Column("domain_id", sa.Integer(), sa.ForeignKey("ev2_domains.id"), nullable=False),
        sa.Column("ordem", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("weight", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("subject_config_id", "domain_id", name="uq_ev2_subject_domain_once"),
        sa.CheckConstraint("weight >= 0 AND weight <= 100", name="ck_ev2_subject_domain_weight"),
    )
    op.create_index("ix_ev2_subject_domain_config", "ev2_subject_domains", ["subject_config_id"])
    op.create_index("ix_ev2_subject_domain_domain", "ev2_subject_domains", ["domain_id"])

    with op.batch_alter_table("ev2_subject_rubrics") as batch_op:
        batch_op.add_column(sa.Column("subject_domain_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("ordem", sa.Integer(), nullable=False, server_default="0"))
        batch_op.create_foreign_key(
            "fk_ev2_subject_rubric_subject_domain",
            "ev2_subject_domains",
            ["subject_domain_id"],
            ["id"],
        )


def downgrade():
    with op.batch_alter_table("ev2_subject_rubrics") as batch_op:
        batch_op.drop_constraint("fk_ev2_subject_rubric_subject_domain", type_="foreignkey")
        batch_op.drop_column("ordem")
        batch_op.drop_column("subject_domain_id")

    op.drop_index("ix_ev2_subject_domain_domain", table_name="ev2_subject_domains")
    op.drop_index("ix_ev2_subject_domain_config", table_name="ev2_subject_domains")
    op.drop_table("ev2_subject_domains")
