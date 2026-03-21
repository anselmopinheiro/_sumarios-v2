"""trabalho tipo_atividade and reusable optional-domain models

Revision ID: 0015_trabalho_tipo_and_optional_domain_models
Revises: 0014_aula_trabalho_link
Create Date: 2026-03-21
"""

from alembic import op
import sqlalchemy as sa

revision = "0015_trabalho_tipo_and_optional_domain_models"
down_revision = "0014_aula_trabalho_link"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("trabalhos") as batch_op:
        batch_op.add_column(sa.Column("tipo_atividade", sa.String(length=20), nullable=False, server_default="trabalho"))

    op.create_table(
        "dominio_opcional_modelos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nome", sa.String(length=140), nullable=False),
        sa.Column("descricao", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("nome", name="uq_dominio_opcional_modelo_nome"),
    )

    op.create_table(
        "dominio_opcional_modelo_dominios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("modelo_id", sa.Integer(), sa.ForeignKey("dominio_opcional_modelos.id"), nullable=False),
        sa.Column("nome", sa.String(length=120), nullable=False),
        sa.Column("peso", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("ordem", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "dominio_opcional_modelo_rubricas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dominio_modelo_id", sa.Integer(), sa.ForeignKey("dominio_opcional_modelo_dominios.id"), nullable=False),
        sa.Column("nome", sa.String(length=140), nullable=False),
        sa.Column("peso", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("ordem", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_table("dominio_opcional_modelo_rubricas")
    op.drop_table("dominio_opcional_modelo_dominios")
    op.drop_table("dominio_opcional_modelos")
    with op.batch_alter_table("trabalhos") as batch_op:
        batch_op.drop_column("tipo_atividade")
