"""Ensure turmas has per-weekday load columns"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "1d4f9c0e9c2d"
down_revision = "6f9c5b1af5c5"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("turmas")}

    weekday_columns = {
        "carga_segunda": sa.Column("carga_segunda", sa.Float(), nullable=True),
        "carga_terca": sa.Column("carga_terca", sa.Float(), nullable=True),
        "carga_quarta": sa.Column("carga_quarta", sa.Float(), nullable=True),
        "carga_quinta": sa.Column("carga_quinta", sa.Float(), nullable=True),
        "carga_sexta": sa.Column("carga_sexta", sa.Float(), nullable=True),
    }

    for name, column in weekday_columns.items():
        if name not in columns:
            op.add_column("turmas", column)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("turmas")}

    for name in [
        "carga_sexta",
        "carga_quinta",
        "carga_quarta",
        "carga_terca",
        "carga_segunda",
    ]:
        if name in columns:
            op.drop_column("turmas", name)
