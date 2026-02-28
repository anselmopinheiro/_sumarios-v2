# SCHEMA TARGET DRAFT (CORE + SUPPORT)

## CORE

### alunos/Aluno
- Colunas principais: id:INTEGER, turma_id:INTEGER, processo:VARCHAR(50), numero:INTEGER, nome:VARCHAR(255), nome_curto:VARCHAR(100), nee:TEXT, observacoes:TEXT
- Relações (FK): turma_id->turmas.id

### anos_letivos/AnoLetivo
- Colunas principais: id:INTEGER, nome:VARCHAR(20), data_inicio_ano:DATE, data_fim_ano:DATE, data_fim_semestre1:DATE, data_inicio_semestre2:DATE, descricao:VARCHAR(255), ativo:BOOLEAN, fechado:BOOLEAN
- Relações (FK): sem FKs

### aulas_alunos/AulaAluno
- Colunas principais: id:INTEGER, aula_id:INTEGER, aluno_id:INTEGER, atraso:BOOLEAN, faltas:INTEGER, responsabilidade:INTEGER, comportamento:INTEGER, participacao:INTEGER, trabalho_autonomo:INTEGER, portatil_material:INTEGER, atividade:INTEGER, falta_disciplinar:INTEGER
- Relações (FK): aluno_id->alunos.id, aula_id->calendario_aulas.id

### calendario_aulas/CalendarioAula
- Colunas principais: id:INTEGER, turma_id:INTEGER, periodo_id:INTEGER, data:DATE, weekday:INTEGER, modulo_id:INTEGER, numero_modulo:INTEGER, total_geral:INTEGER, sumarios:VARCHAR(255), tipo:VARCHAR(50), apagado:BOOLEAN, tempos_sem_aula:INTEGER
- Relações (FK): modulo_id->modulos.id, periodo_id->periodos.id, turma_id->turmas.id

### disciplinas/Disciplina
- Colunas principais: id:INTEGER, nome:VARCHAR(100), sigla:VARCHAR(20), ano_letivo_id:INTEGER
- Relações (FK): ano_letivo_id->anos_letivos.id

### dt_alunos/DTAluno
- Colunas principais: id:INTEGER, dt_turma_id:INTEGER, aluno_id:INTEGER
- Relações (FK): aluno_id->alunos.id, dt_turma_id->dt_turmas.id

### dt_disciplinas/DTDisciplina
- Colunas principais: id:INTEGER, nome:VARCHAR(120), nome_curto:VARCHAR(40), professor_nome:VARCHAR(120), ativa:BOOLEAN
- Relações (FK): sem FKs

### dt_justificacoes/DTJustificacao
- Colunas principais: id:INTEGER, dt_aluno_id:INTEGER, data:DATE, tipo:VARCHAR(20), motivo:TEXT
- Relações (FK): dt_aluno_id->dt_alunos.id

### dt_motivos_dia/DTMotivoDia
- Colunas principais: id:INTEGER, dt_turma_id:INTEGER, data:DATE, motivo:TEXT
- Relações (FK): dt_turma_id->dt_turmas.id

### dt_ocorrencia_alunos/DTOcorrenciaAluno
- Colunas principais: id:INTEGER, dt_ocorrencia_id:INTEGER, dt_aluno_id:INTEGER
- Relações (FK): dt_aluno_id->dt_alunos.id, dt_ocorrencia_id->dt_ocorrencias.id

### dt_ocorrencias/DTOcorrencia
- Colunas principais: id:INTEGER, dt_turma_id:INTEGER, data:DATE, hora_inicio:TIME, hora_fim:TIME, num_tempos:INTEGER, dt_disciplina_id:INTEGER, observacoes:TEXT, created_at:DATETIME, updated_at:DATETIME
- Relações (FK): dt_disciplina_id->dt_disciplinas.id, dt_turma_id->dt_turmas.id

### dt_turmas/DTTurma
- Colunas principais: id:INTEGER, turma_id:INTEGER, ano_letivo_id:INTEGER, observacoes:TEXT
- Relações (FK): ano_letivo_id->anos_letivos.id, turma_id->turmas.id

### entrega_parametros/EntregaParametro
- Colunas principais: id:INTEGER, entrega_id:INTEGER, parametro_definicao_id:INTEGER, valor_numerico:INTEGER, valor_texto:TEXT
- Relações (FK): entrega_id->entregas.id, parametro_definicao_id->parametro_definicoes.id

### entregas/Entrega
- Colunas principais: id:INTEGER, trabalho_id:INTEGER, trabalho_grupo_id:INTEGER, entregue:BOOLEAN, data_entrega:DATE, consecucao:INTEGER, qualidade:INTEGER, observacoes:TEXT, updated_at:DATETIME
- Relações (FK): trabalho_grupo_id->trabalho_grupos.id, trabalho_id->trabalhos.id

### exclusoes/Exclusao
- Colunas principais: id:INTEGER, turma_id:INTEGER, data:DATE, data_text:VARCHAR(255), motivo:VARCHAR(255), tipo:VARCHAR(50)
- Relações (FK): turma_id->turmas.id

### extras/Extra
- Colunas principais: id:INTEGER, turma_id:INTEGER, data:DATE, data_text:VARCHAR(255), motivo:VARCHAR(255), aulas:INTEGER, modulo_nome:VARCHAR(255), tipo:VARCHAR(50)
- Relações (FK): turma_id->turmas.id

### feriados/Feriado
- Colunas principais: id:INTEGER, ano_letivo_id:INTEGER, data:DATE, data_text:VARCHAR(255), nome:VARCHAR(255)
- Relações (FK): ano_letivo_id->anos_letivos.id

### grupo_turma_membros/GrupoTurmaMembro
- Colunas principais: id:INTEGER, grupo_turma_id:INTEGER, aluno_id:INTEGER
- Relações (FK): aluno_id->alunos.id, grupo_turma_id->grupos_turma.id

### grupos_turma/GrupoTurma
- Colunas principais: id:INTEGER, turma_id:INTEGER, nome:VARCHAR(255)
- Relações (FK): turma_id->turmas.id

### horarios/Horario
- Colunas principais: id:INTEGER, turma_id:INTEGER, weekday:INTEGER, horas:INTEGER
- Relações (FK): turma_id->turmas.id

### interrupcoes_letivas/InterrupcaoLetiva
- Colunas principais: id:INTEGER, ano_letivo_id:INTEGER, tipo:VARCHAR(50), data_inicio:DATE, data_fim:DATE, data_text:VARCHAR(255), descricao:VARCHAR(255)
- Relações (FK): ano_letivo_id->anos_letivos.id

### livros/Livro
- Colunas principais: id:INTEGER, nome:VARCHAR(255)
- Relações (FK): sem FKs

### livros_turmas/LivroTurma
- Colunas principais: livro_id:INTEGER, turma_id:INTEGER
- Relações (FK): livro_id->livros.id, turma_id->turmas.id

### modulos/Modulo
- Colunas principais: id:INTEGER, turma_id:INTEGER, nome:VARCHAR(255), total_aulas:INTEGER, tolerancia:INTEGER
- Relações (FK): turma_id->turmas.id

### offline_errors/OfflineError
- Colunas principais: id:INTEGER, created_at:DATETIME, operation:VARCHAR(32), summary:TEXT, details:TEXT, context_json:JSON
- Relações (FK): sem FKs

### offline_state/OfflineState
- Colunas principais: key:VARCHAR(64), value:TEXT
- Relações (FK): sem FKs

### parametro_definicoes/ParametroDefinicao
- Colunas principais: id:INTEGER, trabalho_id:INTEGER, nome:VARCHAR(120), tipo:VARCHAR(20), ordem:INTEGER
- Relações (FK): trabalho_id->trabalhos.id

### periodos/Periodo
- Colunas principais: id:INTEGER, nome:VARCHAR(100), tipo:VARCHAR(20), data_inicio:DATE, data_fim:DATE, turma_id:INTEGER, modulo_id:INTEGER
- Relações (FK): modulo_id->modulos.id, turma_id->turmas.id

### sumario_historico/AulaSumarioHistorico
- Colunas principais: id:INTEGER, calendario_aula_id:INTEGER, created_at:DATETIME, acao:VARCHAR(50), sumario_anterior:TEXT, sumario_novo:TEXT, autor:VARCHAR(100)
- Relações (FK): calendario_aula_id->calendario_aulas.id

### trabalho_grupo_membros/TrabalhoGrupoMembro
- Colunas principais: id:INTEGER, trabalho_grupo_id:INTEGER, aluno_id:INTEGER
- Relações (FK): aluno_id->alunos.id, trabalho_grupo_id->trabalho_grupos.id

### trabalho_grupos/TrabalhoGrupo
- Colunas principais: id:INTEGER, trabalho_id:INTEGER, nome:VARCHAR(255)
- Relações (FK): trabalho_id->trabalhos.id

### trabalhos/Trabalho
- Colunas principais: id:INTEGER, turma_id:INTEGER, titulo:VARCHAR(255), descricao:TEXT, modo:VARCHAR(20), data_limite:DATE, created_at:DATETIME
- Relações (FK): turma_id->turmas.id

### turmas/Turma
- Colunas principais: id:INTEGER, nome:VARCHAR(50), tipo:VARCHAR(20), periodo_tipo:VARCHAR(20), ano_letivo_id:INTEGER, carga_segunda:FLOAT, carga_terca:FLOAT, carga_quarta:FLOAT, carga_quinta:FLOAT, carga_sexta:FLOAT, tempo_segunda:INTEGER, tempo_terca:INTEGER
- Relações (FK): ano_letivo_id->anos_letivos.id

### turmas_disciplinas/TurmaDisciplina
- Colunas principais: id:INTEGER, turma_id:INTEGER, disciplina_id:INTEGER, horas_semanais:FLOAT
- Relações (FK): disciplina_id->disciplinas.id, turma_id->turmas.id

## SUPPORT

## Nota de compatibilidade SQLite/Postgres

- Nao foram detectados tipos explicitamente PG-only via introspecao textual dos tipos.
