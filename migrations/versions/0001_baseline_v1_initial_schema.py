"""Baseline v1 initial schema

Revision ID: 0001_baseline_v1
Revises: 
Create Date: 2026-03-01 18:35:00

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '0001_baseline_v1'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Baseline migration gerada para criar todo o schema definido em models.py
    from models import db

    bind = op.get_bind()
    db.metadata.create_all(bind=bind, checkfirst=True)


def downgrade():
    from models import db

    bind = op.get_bind()
    db.metadata.drop_all(bind=bind, checkfirst=True)
