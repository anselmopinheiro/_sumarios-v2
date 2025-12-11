"""Add weekday tempo columns to turmas"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "2c60e0f613b9"
down_revision = "1d4f9c0e9c2d"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("turmas")}

    tempo_columns = {
        "tempo_segunda": sa.Column("tempo_segunda", sa.Integer(), nullable=True),
        "tempo_terca": sa.Column("tempo_terca", sa.Integer(), nullable=True),
        "tempo_quarta": sa.Column("tempo_quarta", sa.Integer(), nullable=True),
        "tempo_quinta": sa.Column("tempo_quinta", sa.Integer(), nullable=True),
        "tempo_sexta": sa.Column("tempo_sexta", sa.Integer(), nullable=True),
    }

    for name, column in tempo_columns.items():
        if name not in columns:
            op.add_column("turmas", column)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("turmas")}

    for name in [
        "tempo_sexta",
        "tempo_quinta",
        "tempo_quarta",
        "tempo_terca",
        "tempo_segunda",
    ]:
        if name in columns:
            op.drop_column("turmas", name)
