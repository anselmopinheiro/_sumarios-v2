"""Add soft delete flag and support new calendar types"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "7bd4f0a7c5b1"
down_revision = "1d4f9c0e9c2d"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("calendario_aulas")}

    if "deleted" not in columns:
        op.add_column(
            "calendario_aulas",
            sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    tipo_col = next(
        (col for col in inspector.get_columns("calendario_aulas") if col["name"] == "tipo"),
        None,
    )
    if tipo_col and tipo_col.get("default") == "normal":
        op.alter_column(
            "calendario_aulas",
            "tipo",
            existing_type=sa.String(length=50),
            nullable=False,
            server_default="normal",
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("calendario_aulas")}

    if "deleted" in columns:
        op.drop_column("calendario_aulas", "deleted")
