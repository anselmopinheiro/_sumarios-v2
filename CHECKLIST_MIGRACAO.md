# Checklist Flask vs PHP (fase atual)

| Funcionalidade | Flask | PHP (fase atual) | Estado |
|---|---|---|---|
| Autenticação | não existe login explícito | login por sessão + password hash | parcial (novo) |
| Gestão de turmas | completo | listagem + criação | parcial |
| Gestão de disciplinas | completo | não implementado | pendente |
| Módulos | completo | schema criado | parcial |
| Calendário por turma | completo | listagem por turma | parcial |
| Edição de sumários | completo inline | edição em modal | parcial |
| Exceções (extra/greve/falta/etc.) | completo | schema parcial | pendente |
| Direção de turma | completo | não implementado | pendente |
| Avaliação diária | completo | migration base criada | pendente |
| Importação CSV | alunos no Flask | turmas com dry-run+preview | parcial |
| Exportação CSV | vários exports | pendente | pendente |

## Inventário de modelos/tabelas no Flask
- `anos_letivos`, `turmas`, `disciplinas`, `turmas_disciplinas`, `livros`, `livros_turmas`
- `modulos`, `periodos`, `calendario_aulas`
- `alunos`, `aulas_alunos`
- `dt_turmas`, `dt_alunos`, `dt_justificacoes`, `dt_motivos_dia`
- `interrupcoes_letivas`, `feriados`, `horarios`, `exclusoes`, `extras`

## Inventário de fluxos/rotas no Flask
- dashboard `/`
- backups (`/backups`, download, trigger)
- livros CRUD + gerar
- turmas CRUD, clone, exportações, alunos, disciplinas
- calendário por turma (principal, diário, semanal, previsão, pendentes, outras datas)
- edição/apagamento de aulas, gerar/reset calendário
- direção de turma (CRUD, mapa mensal, alunos, justificações)
- anos letivos CRUD + ativo/fechar/abrir
- calendário escolar (interrupções/feriados CRUD + import/export)
- API JSON calendário escolar

## Regras de negócio identificadas
- períodos válidos por turma: `anual|semestre1|semestre2` + `modular`
- turmas regulares sem módulos recebem módulo automático `Geral`
- tipos `greve/servico_oficial/faltei/outros` podem não contar para numeração
- `calendario_aulas` mantém `numero_modulo` e `total_geral`
- existem vistas para sumários pendentes (aulas normais passadas sem sumário)
- parsing de datas PT para interrupções/feriados (ex.: intervalos e listas curtas)
