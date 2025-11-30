"""Add soft delete flag to calendario_aulas"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "3d647f5d3b8f"
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
            sa.Column("apagado", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        )

        # SQLite does not support dropping a default with ALTER TABLE, so only try to
        # clear it on dialects that can handle the operation.
        if bind.dialect.name != "sqlite":
            op.alter_column("calendario_aulas", "apagado", server_default=None)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("calendario_aulas")}

    if "apagado" in columns:
        op.drop_column("calendario_aulas", "apagado")
