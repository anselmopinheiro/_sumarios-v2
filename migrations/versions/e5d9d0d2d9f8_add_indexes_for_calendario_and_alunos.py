"""Add indexes for calendars and alunos

Revision ID: e5d9d0d2d9f8
Revises: c3f9a9d8b21c
Create Date: 2025-02-04 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e5d9d0d2d9f8'
down_revision = 'c3f9a9d8b21c'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        'ix_cal_aulas_turma_data',
        'calendario_aulas',
        ['turma_id', 'data', 'apagado'],
        unique=False,
    )
    op.create_index(
        'ix_cal_aulas_periodo',
        'calendario_aulas',
        ['periodo_id', 'data'],
        unique=False,
    )
    op.create_index(
        'ix_cal_aulas_modulo',
        'calendario_aulas',
        ['modulo_id'],
        unique=False,
    )
    op.create_index(
        'ix_alunos_turma_numero',
        'alunos',
        ['turma_id', 'numero'],
        unique=False,
    )
    op.create_index(
        'ix_aulas_alunos_aula',
        'aulas_alunos',
        ['aula_id'],
        unique=False,
    )
    op.create_index(
        'ix_aulas_alunos_aluno',
        'aulas_alunos',
        ['aluno_id'],
        unique=False,
    )


def downgrade():
    op.drop_index('ix_aulas_alunos_aluno', table_name='aulas_alunos')
    op.drop_index('ix_aulas_alunos_aula', table_name='aulas_alunos')
    op.drop_index('ix_alunos_turma_numero', table_name='alunos')
    op.drop_index('ix_cal_aulas_modulo', table_name='calendario_aulas')
    op.drop_index('ix_cal_aulas_periodo', table_name='calendario_aulas')
    op.drop_index('ix_cal_aulas_turma_data', table_name='calendario_aulas')
