"""Ensure calendario_aulas has module linkage columns"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "6f9c5b1af5c5"
down_revision = "0001_rebuild_schema"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("calendario_aulas")}

    if "modulo_id" not in columns:
        op.add_column(
            "calendario_aulas",
            sa.Column("modulo_id", sa.Integer(), sa.ForeignKey("modulos.id")),
        )
    if "numero_modulo" not in columns:
        op.add_column("calendario_aulas", sa.Column("numero_modulo", sa.Integer()))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("calendario_aulas")}

    if "numero_modulo" in columns:
        op.drop_column("calendario_aulas", "numero_modulo")
    if "modulo_id" in columns:
        op.drop_column("calendario_aulas", "modulo_id")
