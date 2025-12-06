"""Add apagado flag to calendario_aulas for soft delete"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "7c7c6a6e9c1c"
down_revision = "1d4f9c0e9c2d"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("calendario_aulas")}

    if "apagado" not in columns:
        op.add_column(
            "calendario_aulas",
            sa.Column(
                "apagado",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("calendario_aulas")}

    if "apagado" in columns:
        op.drop_column("calendario_aulas", "apagado")
