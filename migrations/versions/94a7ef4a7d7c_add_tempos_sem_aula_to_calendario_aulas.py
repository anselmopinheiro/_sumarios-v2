"""Add tempos_sem_aula column to calendario_aulas"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "94a7ef4a7d7c"
down_revision = "7c7c6a6e9c1c"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("calendario_aulas")}

    if "tempos_sem_aula" not in columns:
        op.add_column(
            "calendario_aulas",
            sa.Column(
                "tempos_sem_aula",
                sa.Integer(),
                nullable=True,
                server_default=sa.text("0"),
            ),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("calendario_aulas")}

    if "tempos_sem_aula" in columns:
        op.drop_column("calendario_aulas", "tempos_sem_aula")
