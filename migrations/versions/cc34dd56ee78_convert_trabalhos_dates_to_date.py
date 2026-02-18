"""convert trabalhos dates to date

Revision ID: cc34dd56ee78
Revises: bb23cc45dd67
Create Date: 2026-02-18 19:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "cc34dd56ee78"
down_revision = "bb23cc45dd67"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.execute(
            "ALTER TABLE trabalhos ALTER COLUMN data_limite TYPE date USING (data_limite::date)"
        )
        op.execute(
            "ALTER TABLE entregas ALTER COLUMN data_entrega TYPE date USING (data_entrega::date)"
        )
    else:
        with op.batch_alter_table("trabalhos", recreate="always") as batch_op:
            batch_op.alter_column("data_limite", existing_type=sa.DateTime(), type_=sa.Date(), existing_nullable=True)
        with op.batch_alter_table("entregas", recreate="always") as batch_op:
            batch_op.alter_column("data_entrega", existing_type=sa.DateTime(), type_=sa.Date(), existing_nullable=True)


def downgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.execute(
            "ALTER TABLE trabalhos ALTER COLUMN data_limite TYPE timestamp USING (data_limite::timestamp)"
        )
        op.execute(
            "ALTER TABLE entregas ALTER COLUMN data_entrega TYPE timestamp USING (data_entrega::timestamp)"
        )
    else:
        with op.batch_alter_table("trabalhos", recreate="always") as batch_op:
            batch_op.alter_column("data_limite", existing_type=sa.Date(), type_=sa.DateTime(), existing_nullable=True)
        with op.batch_alter_table("entregas", recreate="always") as batch_op:
            batch_op.alter_column("data_entrega", existing_type=sa.Date(), type_=sa.DateTime(), existing_nullable=True)
