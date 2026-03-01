"""Baseline v1 initial schema

Revision ID: 0001_initial
Revises: 
Create Date: 2026-03-01 19:00:00

"""
from alembic import op
import sqlalchemy as sa

revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('anos_letivos',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('nome', sa.String(length=20), nullable=False, unique=True),
        sa.Column('data_inicio_ano', sa.Date(), nullable=False),
        sa.Column('data_fim_ano', sa.Date(), nullable=False),
        sa.Column('data_fim_semestre1', sa.Date(), nullable=False),
        sa.Column('data_inicio_semestre2', sa.Date(), nullable=False),
        sa.Column('descricao', sa.String(length=255)),
        sa.Column('ativo', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('fechado', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.UniqueConstraint('nome'),
    )
    op.create_table('dt_disciplinas',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('nome', sa.String(length=120), nullable=False, unique=True),
        sa.Column('nome_curto', sa.String(length=40)),
        sa.Column('professor_nome', sa.String(length=120)),
        sa.Column('ativa', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.UniqueConstraint('nome'),
    )
    op.create_table('livros',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('nome', sa.String(length=255), nullable=False, unique=True),
        sa.UniqueConstraint('nome'),
    )
    op.create_table('offline_errors',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('operation', sa.String(length=32), nullable=False),
        sa.Column('summary', sa.String(), nullable=False),
        sa.Column('details', sa.String()),
        sa.Column('context_json', sa.JSON()),
    )
    op.create_table('offline_state',
        sa.Column('key', sa.String(length=64), primary_key=True, nullable=False),
        sa.Column('value', sa.String()),
    )
    op.create_table('disciplinas',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('nome', sa.String(length=100), nullable=False),
        sa.Column('sigla', sa.String(length=20)),
        sa.Column('ano_letivo_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['ano_letivo_id'], ['anos_letivos.id']),
    )
    op.create_table('feriados',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('ano_letivo_id', sa.Integer(), nullable=False),
        sa.Column('data', sa.Date()),
        sa.Column('data_text', sa.String(length=255)),
        sa.Column('nome', sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(['ano_letivo_id'], ['anos_letivos.id']),
    )
    op.create_table('interrupcoes_letivas',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('ano_letivo_id', sa.Integer(), nullable=False),
        sa.Column('tipo', sa.String(length=50), nullable=False),
        sa.Column('data_inicio', sa.Date()),
        sa.Column('data_fim', sa.Date()),
        sa.Column('data_text', sa.String(length=255)),
        sa.Column('descricao', sa.String(length=255)),
        sa.ForeignKeyConstraint(['ano_letivo_id'], ['anos_letivos.id']),
    )
    op.create_table('turmas',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('nome', sa.String(length=50), nullable=False),
        sa.Column('tipo', sa.String(length=20), nullable=False),
        sa.Column('periodo_tipo', sa.String(length=20), nullable=False),
        sa.Column('ano_letivo_id', sa.Integer()),
        sa.Column('carga_segunda', sa.Float()),
        sa.Column('carga_terca', sa.Float()),
        sa.Column('carga_quarta', sa.Float()),
        sa.Column('carga_quinta', sa.Float()),
        sa.Column('carga_sexta', sa.Float()),
        sa.Column('tempo_segunda', sa.Integer()),
        sa.Column('tempo_terca', sa.Integer()),
        sa.Column('tempo_quarta', sa.Integer()),
        sa.Column('tempo_quinta', sa.Integer()),
        sa.Column('tempo_sexta', sa.Integer()),
        sa.Column('letiva', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.ForeignKeyConstraint(['ano_letivo_id'], ['anos_letivos.id']),
    )
    op.create_table('alunos',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('turma_id', sa.Integer(), nullable=False),
        sa.Column('processo', sa.String(length=50)),
        sa.Column('numero', sa.Integer()),
        sa.Column('nome', sa.String(length=255), nullable=False),
        sa.Column('nome_curto', sa.String(length=100)),
        sa.Column('nee', sa.String()),
        sa.Column('observacoes', sa.String()),
        sa.ForeignKeyConstraint(['turma_id'], ['turmas.id']),
    )
    op.create_table('dt_turmas',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('turma_id', sa.Integer(), nullable=False),
        sa.Column('ano_letivo_id', sa.Integer(), nullable=False),
        sa.Column('observacoes', sa.String()),
        sa.ForeignKeyConstraint(['turma_id'], ['turmas.id']),
        sa.UniqueConstraint('turma_id', 'ano_letivo_id', name='uq_dt_turma_ano'),
        sa.ForeignKeyConstraint(['ano_letivo_id'], ['anos_letivos.id']),
    )
    op.create_table('exclusoes',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('turma_id', sa.Integer(), nullable=False),
        sa.Column('data', sa.Date()),
        sa.Column('data_text', sa.String(length=255)),
        sa.Column('motivo', sa.String(length=255)),
        sa.Column('tipo', sa.String(length=50)),
        sa.ForeignKeyConstraint(['turma_id'], ['turmas.id']),
    )
    op.create_table('extras',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('turma_id', sa.Integer(), nullable=False),
        sa.Column('data', sa.Date()),
        sa.Column('data_text', sa.String(length=255)),
        sa.Column('motivo', sa.String(length=255)),
        sa.Column('aulas', sa.Integer(), nullable=False),
        sa.Column('modulo_nome', sa.String(length=255)),
        sa.Column('tipo', sa.String(length=50)),
        sa.ForeignKeyConstraint(['turma_id'], ['turmas.id']),
    )
    op.create_table('grupos_turma',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('turma_id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(['turma_id'], ['turmas.id']),
        sa.UniqueConstraint('turma_id', 'nome', name='uq_grupo_turma_nome'),
    )
    op.create_table('horarios',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('turma_id', sa.Integer(), nullable=False),
        sa.Column('weekday', sa.Integer(), nullable=False),
        sa.Column('horas', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['turma_id'], ['turmas.id']),
    )
    op.create_table('livros_turmas',
        sa.Column('livro_id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('turma_id', sa.Integer(), primary_key=True, nullable=False),
        sa.ForeignKeyConstraint(['livro_id'], ['livros.id']),
        sa.ForeignKeyConstraint(['turma_id'], ['turmas.id']),
    )
    op.create_table('modulos',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('turma_id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(length=255), nullable=False),
        sa.Column('total_aulas', sa.Integer(), nullable=False),
        sa.Column('tolerancia', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['turma_id'], ['turmas.id']),
    )
    op.create_table('trabalhos',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('turma_id', sa.Integer(), nullable=False),
        sa.Column('titulo', sa.String(length=255), nullable=False),
        sa.Column('descricao', sa.String()),
        sa.Column('modo', sa.String(length=20), nullable=False, server_default=sa.text('individual')),
        sa.Column('data_limite', sa.Date()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['turma_id'], ['turmas.id']),
    )
    op.create_table('turmas_disciplinas',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('turma_id', sa.Integer(), nullable=False),
        sa.Column('disciplina_id', sa.Integer(), nullable=False),
        sa.Column('horas_semanais', sa.Float()),
        sa.ForeignKeyConstraint(['turma_id'], ['turmas.id']),
        sa.UniqueConstraint('turma_id', 'disciplina_id', name='uq_turma_disciplina'),
        sa.ForeignKeyConstraint(['disciplina_id'], ['disciplinas.id']),
    )
    op.create_table('dt_alunos',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('dt_turma_id', sa.Integer(), nullable=False),
        sa.Column('aluno_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['dt_turma_id'], ['dt_turmas.id']),
        sa.ForeignKeyConstraint(['aluno_id'], ['alunos.id']),
    )
    op.create_table('dt_motivos_dia',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('dt_turma_id', sa.Integer(), nullable=False),
        sa.Column('data', sa.Date(), nullable=False),
        sa.Column('motivo', sa.String()),
        sa.ForeignKeyConstraint(['dt_turma_id'], ['dt_turmas.id']),
        sa.UniqueConstraint('dt_turma_id', 'data', name='uq_dt_motivo_dia'),
    )
    op.create_table('dt_ocorrencias',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('dt_turma_id', sa.Integer(), nullable=False),
        sa.Column('data', sa.Date(), nullable=False),
        sa.Column('hora_inicio', sa.Time()),
        sa.Column('hora_fim', sa.Time()),
        sa.Column('num_tempos', sa.Integer()),
        sa.Column('dt_disciplina_id', sa.Integer(), nullable=False),
        sa.Column('observacoes', sa.String()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['dt_disciplina_id'], ['dt_disciplinas.id']),
        sa.ForeignKeyConstraint(['dt_turma_id'], ['dt_turmas.id']),
    )
    op.create_table('grupo_turma_membros',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('grupo_turma_id', sa.Integer(), nullable=False),
        sa.Column('aluno_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['grupo_turma_id'], ['grupos_turma.id']),
        sa.UniqueConstraint('grupo_turma_id', 'aluno_id', name='uq_grupo_turma_membro'),
        sa.ForeignKeyConstraint(['aluno_id'], ['alunos.id']),
    )
    op.create_table('parametro_definicoes',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('trabalho_id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(length=120), nullable=False),
        sa.Column('tipo', sa.String(length=20), nullable=False, server_default=sa.text('numerico')),
        sa.Column('ordem', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.ForeignKeyConstraint(['trabalho_id'], ['trabalhos.id']),
        sa.UniqueConstraint('trabalho_id', 'nome', name='uq_parametro_trabalho_nome'),
    )
    op.create_table('periodos',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('nome', sa.String(length=100), nullable=False),
        sa.Column('tipo', sa.String(length=20), nullable=False),
        sa.Column('data_inicio', sa.Date(), nullable=False),
        sa.Column('data_fim', sa.Date(), nullable=False),
        sa.Column('turma_id', sa.Integer(), nullable=False),
        sa.Column('modulo_id', sa.Integer()),
        sa.ForeignKeyConstraint(['turma_id'], ['turmas.id']),
        sa.ForeignKeyConstraint(['modulo_id'], ['modulos.id']),
    )
    op.create_table('trabalho_grupos',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('trabalho_id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(['trabalho_id'], ['trabalhos.id']),
        sa.UniqueConstraint('trabalho_id', 'nome', name='uq_trabalho_grupo_nome'),
    )
    op.create_table('calendario_aulas',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('turma_id', sa.Integer(), nullable=False),
        sa.Column('periodo_id', sa.Integer(), nullable=False),
        sa.Column('data', sa.Date(), nullable=False),
        sa.Column('weekday', sa.Integer(), nullable=False),
        sa.Column('modulo_id', sa.Integer()),
        sa.Column('numero_modulo', sa.Integer()),
        sa.Column('total_geral', sa.Integer()),
        sa.Column('sumarios', sa.String(length=255)),
        sa.Column('tipo', sa.String(length=50), nullable=False),
        sa.Column('apagado', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('tempos_sem_aula', sa.Integer()),
        sa.Column('observacoes', sa.String()),
        sa.Column('observacoes_html', sa.String()),
        sa.Column('sumario', sa.String()),
        sa.Column('previsao', sa.String()),
        sa.Column('atividade', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('atividade_nome', sa.String()),
        sa.ForeignKeyConstraint(['periodo_id'], ['periodos.id']),
        sa.ForeignKeyConstraint(['turma_id'], ['turmas.id']),
        sa.ForeignKeyConstraint(['modulo_id'], ['modulos.id']),
    )
    op.create_table('dt_justificacoes',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('dt_aluno_id', sa.Integer(), nullable=False),
        sa.Column('data', sa.Date(), nullable=False),
        sa.Column('tipo', sa.String(length=20), nullable=False),
        sa.Column('motivo', sa.String()),
        sa.ForeignKeyConstraint(['dt_aluno_id'], ['dt_alunos.id']),
    )
    op.create_table('dt_ocorrencia_alunos',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('dt_ocorrencia_id', sa.Integer(), nullable=False),
        sa.Column('dt_aluno_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['dt_ocorrencia_id'], ['dt_ocorrencias.id']),
        sa.ForeignKeyConstraint(['dt_aluno_id'], ['dt_alunos.id']),
        sa.UniqueConstraint('dt_ocorrencia_id', 'dt_aluno_id', name='uq_dt_ocorrencia_aluno'),
    )
    op.create_table('entregas',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('trabalho_id', sa.Integer(), nullable=False),
        sa.Column('trabalho_grupo_id', sa.Integer(), nullable=False),
        sa.Column('entregue', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('data_entrega', sa.Date()),
        sa.Column('consecucao', sa.Integer()),
        sa.Column('qualidade', sa.Integer()),
        sa.Column('observacoes', sa.String()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.UniqueConstraint('trabalho_id', 'trabalho_grupo_id', name='uq_entrega_trabalho_grupo'),
        sa.ForeignKeyConstraint(['trabalho_id'], ['trabalhos.id']),
        sa.ForeignKeyConstraint(['trabalho_grupo_id'], ['trabalho_grupos.id']),
    )
    op.create_table('trabalho_grupo_membros',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('trabalho_grupo_id', sa.Integer(), nullable=False),
        sa.Column('aluno_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['trabalho_grupo_id'], ['trabalho_grupos.id']),
        sa.UniqueConstraint('trabalho_grupo_id', 'aluno_id', name='uq_trabalho_grupo_membro'),
        sa.ForeignKeyConstraint(['aluno_id'], ['alunos.id']),
    )
    op.create_table('aulas_alunos',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('aula_id', sa.Integer(), nullable=False),
        sa.Column('aluno_id', sa.Integer(), nullable=False),
        sa.Column('atraso', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('faltas', sa.Integer(), nullable=False),
        sa.Column('responsabilidade', sa.Integer(), server_default=sa.text('3')),
        sa.Column('comportamento', sa.Integer(), server_default=sa.text('3')),
        sa.Column('participacao', sa.Integer(), server_default=sa.text('3')),
        sa.Column('trabalho_autonomo', sa.Integer(), server_default=sa.text('3')),
        sa.Column('portatil_material', sa.Integer(), server_default=sa.text('3')),
        sa.Column('atividade', sa.Integer(), server_default=sa.text('3')),
        sa.Column('falta_disciplinar', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('observacoes', sa.String()),
        sa.UniqueConstraint('aula_id', 'aluno_id', name='uq_aula_aluno'),
        sa.ForeignKeyConstraint(['aula_id'], ['calendario_aulas.id']),
        sa.ForeignKeyConstraint(['aluno_id'], ['alunos.id']),
    )
    op.create_table('entrega_parametros',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('entrega_id', sa.Integer(), nullable=False),
        sa.Column('parametro_definicao_id', sa.Integer(), nullable=False),
        sa.Column('valor_numerico', sa.Integer()),
        sa.Column('valor_texto', sa.String()),
        sa.UniqueConstraint('entrega_id', 'parametro_definicao_id', name='uq_entrega_parametro'),
        sa.ForeignKeyConstraint(['entrega_id'], ['entregas.id']),
        sa.ForeignKeyConstraint(['parametro_definicao_id'], ['parametro_definicoes.id']),
    )
    op.create_table('sumario_historico',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('calendario_aula_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('acao', sa.String(length=50), nullable=False),
        sa.Column('sumario_anterior', sa.String()),
        sa.Column('sumario_novo', sa.String()),
        sa.Column('autor', sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(['calendario_aula_id'], ['calendario_aulas.id']),
    )
    op.create_index('ix_offline_errors_created_at', 'offline_errors', ['created_at'], unique=False)
    op.create_index('ix_offline_errors_operation', 'offline_errors', ['operation'], unique=False)
    op.create_index('ix_alunos_turma_numero', 'alunos', ['turma_id', 'numero'], unique=False)
    op.create_index('ix_grupos_turma_turma_id', 'grupos_turma', ['turma_id'], unique=False)
    op.create_index('ix_trabalhos_turma_id', 'trabalhos', ['turma_id'], unique=False)
    op.create_index('ix_dt_alunos_turma_aluno', 'dt_alunos', ['dt_turma_id', 'aluno_id'], unique=False)
    op.create_index('ix_dt_ocorrencias_data', 'dt_ocorrencias', ['data'], unique=False)
    op.create_index('ix_dt_ocorrencias_dt_disciplina_id', 'dt_ocorrencias', ['dt_disciplina_id'], unique=False)
    op.create_index('ix_dt_ocorrencias_dt_turma_id', 'dt_ocorrencias', ['dt_turma_id'], unique=False)
    op.create_index('ix_grupo_turma_membros_aluno_id', 'grupo_turma_membros', ['aluno_id'], unique=False)
    op.create_index('ix_grupo_turma_membros_grupo_turma_id', 'grupo_turma_membros', ['grupo_turma_id'], unique=False)
    op.create_index('ix_parametro_definicoes_trabalho_id', 'parametro_definicoes', ['trabalho_id'], unique=False)
    op.create_index('ix_trabalho_grupos_trabalho_id', 'trabalho_grupos', ['trabalho_id'], unique=False)
    op.create_index('ix_cal_aulas_modulo', 'calendario_aulas', ['modulo_id'], unique=False)
    op.create_index('ix_cal_aulas_periodo', 'calendario_aulas', ['periodo_id', 'data'], unique=False)
    op.create_index('ix_cal_aulas_turma_data', 'calendario_aulas', ['turma_id', 'data', 'apagado'], unique=False)
    op.create_index('ix_dt_ocorrencia_alunos_aluno', 'dt_ocorrencia_alunos', ['dt_aluno_id'], unique=False)
    op.create_index('ix_dt_ocorrencia_alunos_ocorrencia', 'dt_ocorrencia_alunos', ['dt_ocorrencia_id'], unique=False)
    op.create_index('ix_entregas_trabalho_grupo_id', 'entregas', ['trabalho_grupo_id'], unique=False)
    op.create_index('ix_entregas_trabalho_id', 'entregas', ['trabalho_id'], unique=False)
    op.create_index('ix_trabalho_grupo_membros_aluno_id', 'trabalho_grupo_membros', ['aluno_id'], unique=False)
    op.create_index('ix_trabalho_grupo_membros_trabalho_grupo_id', 'trabalho_grupo_membros', ['trabalho_grupo_id'], unique=False)
    op.create_index('ix_aulas_alunos_aluno', 'aulas_alunos', ['aluno_id'], unique=False)
    op.create_index('ix_aulas_alunos_aula', 'aulas_alunos', ['aula_id'], unique=False)
    op.create_index('ix_entrega_parametros_entrega_id', 'entrega_parametros', ['entrega_id'], unique=False)
    op.create_index('ix_entrega_parametros_parametro_definicao_id', 'entrega_parametros', ['parametro_definicao_id'], unique=False)
    op.create_index('ix_sumario_hist_aula_data', 'sumario_historico', ['calendario_aula_id', 'created_at'], unique=False)


def downgrade():
    op.drop_index('ix_sumario_hist_aula_data', table_name='sumario_historico')
    op.drop_index('ix_entrega_parametros_parametro_definicao_id', table_name='entrega_parametros')
    op.drop_index('ix_entrega_parametros_entrega_id', table_name='entrega_parametros')
    op.drop_index('ix_aulas_alunos_aula', table_name='aulas_alunos')
    op.drop_index('ix_aulas_alunos_aluno', table_name='aulas_alunos')
    op.drop_index('ix_trabalho_grupo_membros_trabalho_grupo_id', table_name='trabalho_grupo_membros')
    op.drop_index('ix_trabalho_grupo_membros_aluno_id', table_name='trabalho_grupo_membros')
    op.drop_index('ix_entregas_trabalho_id', table_name='entregas')
    op.drop_index('ix_entregas_trabalho_grupo_id', table_name='entregas')
    op.drop_index('ix_dt_ocorrencia_alunos_ocorrencia', table_name='dt_ocorrencia_alunos')
    op.drop_index('ix_dt_ocorrencia_alunos_aluno', table_name='dt_ocorrencia_alunos')
    op.drop_index('ix_cal_aulas_turma_data', table_name='calendario_aulas')
    op.drop_index('ix_cal_aulas_periodo', table_name='calendario_aulas')
    op.drop_index('ix_cal_aulas_modulo', table_name='calendario_aulas')
    op.drop_index('ix_trabalho_grupos_trabalho_id', table_name='trabalho_grupos')
    op.drop_index('ix_parametro_definicoes_trabalho_id', table_name='parametro_definicoes')
    op.drop_index('ix_grupo_turma_membros_grupo_turma_id', table_name='grupo_turma_membros')
    op.drop_index('ix_grupo_turma_membros_aluno_id', table_name='grupo_turma_membros')
    op.drop_index('ix_dt_ocorrencias_dt_turma_id', table_name='dt_ocorrencias')
    op.drop_index('ix_dt_ocorrencias_dt_disciplina_id', table_name='dt_ocorrencias')
    op.drop_index('ix_dt_ocorrencias_data', table_name='dt_ocorrencias')
    op.drop_index('ix_dt_alunos_turma_aluno', table_name='dt_alunos')
    op.drop_index('ix_trabalhos_turma_id', table_name='trabalhos')
    op.drop_index('ix_grupos_turma_turma_id', table_name='grupos_turma')
    op.drop_index('ix_alunos_turma_numero', table_name='alunos')
    op.drop_index('ix_offline_errors_operation', table_name='offline_errors')
    op.drop_index('ix_offline_errors_created_at', table_name='offline_errors')
    op.drop_table('sumario_historico')
    op.drop_table('entrega_parametros')
    op.drop_table('aulas_alunos')
    op.drop_table('trabalho_grupo_membros')
    op.drop_table('entregas')
    op.drop_table('dt_ocorrencia_alunos')
    op.drop_table('dt_justificacoes')
    op.drop_table('calendario_aulas')
    op.drop_table('trabalho_grupos')
    op.drop_table('periodos')
    op.drop_table('parametro_definicoes')
    op.drop_table('grupo_turma_membros')
    op.drop_table('dt_ocorrencias')
    op.drop_table('dt_motivos_dia')
    op.drop_table('dt_alunos')
    op.drop_table('turmas_disciplinas')
    op.drop_table('trabalhos')
    op.drop_table('modulos')
    op.drop_table('livros_turmas')
    op.drop_table('horarios')
    op.drop_table('grupos_turma')
    op.drop_table('extras')
    op.drop_table('exclusoes')
    op.drop_table('dt_turmas')
    op.drop_table('alunos')
    op.drop_table('turmas')
    op.drop_table('interrupcoes_letivas')
    op.drop_table('feriados')
    op.drop_table('disciplinas')
    op.drop_table('offline_state')
    op.drop_table('offline_errors')
    op.drop_table('livros')
    op.drop_table('dt_disciplinas')
    op.drop_table('anos_letivos')
