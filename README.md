# _sumarios-v2

Aplicação Flask para gestão de turmas, calendários de aulas, sumários e avaliação diária.

## Funcionalidades principais
- **Calendários de aula**: geração por turma respeitando o tipo de período (anual/1.º semestre/2.º semestre) e impedindo novas gerações se já existirem aulas.
- **Edição inline**: atualizar sumário, previsão, tipo, tempos sem aula e observações diretamente nas vistas principal, diária, semanal ou "Outras datas", com botões individuais e um botão flutuante para guardar tudo.
- **Aulas que não contam**: tipos greve/serviço oficial/faltei/outros não avançam contagem de aulas/sumários; exibem badge vermelho e podem registar tempos sem aula.
- **Aulas extra e "Outras datas"**: criar aulas extra, listar especiais, mudar tipos em massa, exportar/importar JSON/CSV e adicionar observações.
- **Sumários pendentes**: página dedicada que mostra apenas aulas normais anteriores à data atual sem sumário preenchido.
- **Avaliação diária de alunos**: registo de pontualidade, faltas e notas (por defeito 3) para responsabilidade, comportamento, participação, trabalho autónomo, portátil/material e atividade; mapas de médias diárias e mapa específico de atividades com exportação XLS.
- **Gestão de alunos**: criação/edição, importação CSV (campos processo, número, nome, nome curto, NEE, observações), seleção múltipla para copiar/mover entre turmas (apenas para turmas de anos letivos abertos como destino).
- **Calendário escolar**: gestão de anos letivos, interrupções e feriados, com importação/exportação JSON e interface em Bootstrap.
- **Backups e importações**: calendários e calendário escolar podem ser exportados/importados em JSON; sumários e aulas especiais têm exportação CSV (UTF-8 BOM) e JSON.

## Instalação (do zero)
1. **Criar ambiente**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
   ```
2. **Instalar dependências**
   ```bash
   pip install -r requirements.txt
   ```
3. **Configurar variáveis (opcional)**
   - `FLASK_APP=app.py`
   - `FLASK_ENV=development` (para reloading automático)

4. **Criar base de dados**
   - Por omissão é usado `sqlite:///gestor_lectivo.db` na raiz do projeto.
   - Para um arranque limpo basta executar:
     ```bash
     flask db upgrade
     ```
     (a aplicação também cria as tabelas e colunas recentes automaticamente no primeiro arranque se a BD estiver vazia ou desatualizada).

5. **Popular dados iniciais (opcional)**
   ```bash
   python seed.py
   python seed_interrupcoes.py
   ```

6. **Executar**
   ```bash
   flask run
   ```

## Utilização rápida
- **Anos letivos**: criar/editar e marcar como ativo/aberto. Turmas são agrupadas por ano aberto/fechado na listagem.
- **Turmas**: definir `periodo_tipo` (anual/semestres) e cargas semanais. A geração de calendário obedece ao período escolhido e é bloqueada se a turma já tiver aulas.
- **Calendários de turma**: edição inline, observações e previsões auto-redimensionáveis, badges de metadados e link para avaliação de alunos. Ações disponíveis também nas vistas diária e semanal, com navegação por data/semana e filtros de turma/período.
- **Aulas extra e "Outras datas"**: criar aulas extra apenas para turmas de anos abertos/ativos, ajustar número de aulas e tempos sem aula, aplicar mudança de tipo em massa por data, filtrar por turma/tipo/período e exportar/importar JSON/CSV.
- **Sumários pendentes**: aceder pelo menu para preencher rapidamente aulas normais anteriores à data corrente.
- **Avaliação de alunos**: cada aula tem página para lançar faltas, pontualidade e notas (default 3). Mapas diários mostram média por dia (com número de sumário no cabeçalho) e total de faltas; existe mapa separado para atividades.
- **Alunos**: importar CSV mesmo em anos fechados, copiar/mover entre turmas (somente para destino em ano aberto), e gerir dados individuais.
- **Importações/Backups**:
  - **Calendário**: importar JSON em bloco (por turma ou lista simples) via "Importar calendário".
  - **Calendário escolar**: importar/exportar JSON via "Calendário escolar" → "Importar calendário".
  - **Sumários e aulas especiais**: exportação JSON/CSV com cabeçalhos acentuados preservados; os ficheiros recebem data no nome.

## Otimizações técnicas
- Índices adicionados às tabelas de calendários, alunos e avaliações para acelerar listagens e mapas.
- Criação automática de tabelas/colunas novas e sincronização do `alembic_version` em bases antigas, reduzindo erros de arranque.
- Seletores de turmas filtram para anos letivos ativos e abertos em formulários de extras, calendário global e importações, evitando ações sobre anos fechados.
