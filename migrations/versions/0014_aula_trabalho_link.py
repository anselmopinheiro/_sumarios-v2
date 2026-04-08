"""persist aula->trabalho selection for projeto/trabalho shell tabs

Revision ID: 0014_aula_trabalho_link
Revises: 0013_trabalhos_group_fields_and_individual_eval
Create Date: 2026-03-21
"""

from alembic import op
import sqlalchemy as sa

revision = "0014_aula_trabalho_link"
down_revision = "0013_trabalhos_group_fields_and_individual_eval"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "aula_trabalho_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("aula_id", sa.Integer(), sa.ForeignKey("calendario_aulas.id"), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False, server_default="trabalho"),
        sa.Column("trabalho_id", sa.Integer(), sa.ForeignKey("trabalhos.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("aula_id", "tipo", name="uq_aula_trabalho_link"),
    )
    op.create_index("ix_aula_trabalho_links_aula_id", "aula_trabalho_links", ["aula_id"], unique=False)
    op.create_index("ix_aula_trabalho_links_trabalho_id", "aula_trabalho_links", ["trabalho_id"], unique=False)


def downgrade():
    op.drop_index("ix_aula_trabalho_links_trabalho_id", table_name="aula_trabalho_links")
    op.drop_index("ix_aula_trabalho_links_aula_id", table_name="aula_trabalho_links")
    op.drop_table("aula_trabalho_links")
