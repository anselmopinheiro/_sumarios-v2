"""Add periodo_tipo to turmas"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c3f9a9d8b21c"
down_revision = "94a7ef4a7d7c"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("turmas")}

    if "periodo_tipo" not in columns:
        op.add_column(
            "turmas",
            sa.Column(
                "periodo_tipo",
                sa.String(length=20),
                nullable=False,
                server_default=sa.text("'anual'"),
            ),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("turmas")}

    if "periodo_tipo" in columns:
        op.drop_column("turmas", "periodo_tipo")
