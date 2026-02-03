"""Add dt motivos dia table"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "9c2a1d4f8b7e"
down_revision = "8c1f2d5a9b0e"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "dt_motivos_dia" not in tables:
        op.create_table(
            "dt_motivos_dia",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("dt_turma_id", sa.Integer(), nullable=False),
            sa.Column("data", sa.Date(), nullable=False),
            sa.Column("motivo", sa.Text()),
            sa.ForeignKeyConstraint(["dt_turma_id"], ["dt_turmas.id"]),
            sa.UniqueConstraint("dt_turma_id", "data", name="uq_dt_motivo_dia"),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "dt_motivos_dia" in tables:
        op.drop_table("dt_motivos_dia")
