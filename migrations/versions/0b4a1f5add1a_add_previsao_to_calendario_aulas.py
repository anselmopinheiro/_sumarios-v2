from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0b4a1f5add1a"
down_revision = "94a7ef4a7d7c"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("calendario_aulas")}

    if "previsao" not in columns:
        op.add_column(
            "calendario_aulas",
            sa.Column("previsao", sa.Text(), nullable=True),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("calendario_aulas")}

    if "previsao" in columns:
        op.drop_column("calendario_aulas", "previsao")
