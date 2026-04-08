"""trabalhos: campos de grupo e avaliação individual por aluno

Revision ID: 0013_trabalhos_group_fields_and_individual_eval
Revises: 0012_ev2_themes_and_group_theme_assignment
Create Date: 2026-03-21
"""

from alembic import op
import sqlalchemy as sa


revision = "0013_trabalhos_group_fields_and_individual_eval"
down_revision = "0012_ev2_themes_and_group_theme_assignment"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("trabalhos") as batch_op:
        batch_op.add_column(sa.Column("tema_global", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("usar_tema_por_grupo", sa.Boolean(), nullable=False, server_default=sa.text("0")))
        batch_op.add_column(sa.Column("peso_dominios", sa.Float(), nullable=False, server_default="1.0"))
        batch_op.add_column(sa.Column("peso_criterios_extra", sa.Float(), nullable=False, server_default="0.0"))

    with op.batch_alter_table("trabalho_grupos") as batch_op:
        batch_op.add_column(sa.Column("tema", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("data_entrega", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("observacoes", sa.Text(), nullable=True))

    with op.batch_alter_table("parametro_definicoes") as batch_op:
        batch_op.add_column(sa.Column("escala", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("peso", sa.Float(), nullable=False, server_default="1.0"))

    with op.batch_alter_table("entregas") as batch_op:
        batch_op.add_column(sa.Column("aluno_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_entregas_aluno_id", ["aluno_id"], unique=False)
        batch_op.create_foreign_key("fk_entregas_aluno", "alunos", ["aluno_id"], ["id"])
        batch_op.drop_constraint("uq_entrega_trabalho_grupo", type_="unique")
        batch_op.create_unique_constraint(
            "uq_entrega_trabalho_grupo_aluno",
            ["trabalho_id", "trabalho_grupo_id", "aluno_id"],
        )


def downgrade():
    with op.batch_alter_table("entregas") as batch_op:
        batch_op.drop_constraint("uq_entrega_trabalho_grupo_aluno", type_="unique")
        batch_op.create_unique_constraint("uq_entrega_trabalho_grupo", ["trabalho_id", "trabalho_grupo_id"])
        batch_op.drop_constraint("fk_entregas_aluno", type_="foreignkey")
        batch_op.drop_index("ix_entregas_aluno_id")
        batch_op.drop_column("aluno_id")

    with op.batch_alter_table("parametro_definicoes") as batch_op:
        batch_op.drop_column("peso")
        batch_op.drop_column("escala")

    with op.batch_alter_table("trabalho_grupos") as batch_op:
        batch_op.drop_column("observacoes")
        batch_op.drop_column("data_entrega")
        batch_op.drop_column("tema")

    with op.batch_alter_table("trabalhos") as batch_op:
        batch_op.drop_column("peso_criterios_extra")
        batch_op.drop_column("peso_dominios")
        batch_op.drop_column("usar_tema_por_grupo")
        batch_op.drop_column("tema_global")
