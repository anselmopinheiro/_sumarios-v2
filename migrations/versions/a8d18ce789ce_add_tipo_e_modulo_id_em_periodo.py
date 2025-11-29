"""add tipo e modulo_id em Periodo

Revision ID: a8d18ce789ce
Revises: c59d534248e0
Create Date: 2025-11-28 21:48:57.464877

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a8d18ce789ce'
down_revision = 'c59d534248e0'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands ajustados pelo humano, com batch_alter_table ###
    with op.batch_alter_table('periodos', schema=None) as batch_op:
        # 1) tipo inicialmente PERMITE NULL
        batch_op.add_column(sa.Column('tipo', sa.String(length=20), nullable=True))

        # 2) modulo_id opcional
        batch_op.add_column(sa.Column('modulo_id', sa.Integer(), nullable=True))

        # 3) FK com NOME (antes estava None)
        batch_op.create_foreign_key(
            'fk_periodos_modulo_id_modulos',  # nome do constraint
            'modulos',                        # tabela referenciada
            ['modulo_id'],                    # coluna local
            ['id']                            # coluna remota
        )

    # 4) Preencher a nova coluna para linhas já existentes
    #    Todas as linhas atuais de periodos passam a ser "anual" por defeito
    op.execute("UPDATE periodos SET tipo = 'anual' WHERE tipo IS NULL")

    # (Opcional) Se quiseres MESMO forçar NOT NULL a nível de BD:
    # com SQLite isto implica um novo batch_alter_table,
    # mas podes deixar para outra migration ou nem o fazer já.


def downgrade():
    # ### commands ajustados ###
    with op.batch_alter_table('periodos', schema=None) as batch_op:
        # 1) remover FK (usar o MESMO nome que no upgrade)
        batch_op.drop_constraint('fk_periodos_modulo_id_modulos', type_='foreignkey')

        # 2) remover colunas
        batch_op.drop_column('modulo_id')
        batch_op.drop_column('tipo')

    # ### end Alembic commands ###
