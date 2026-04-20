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
3. **Configurar variáveis (desenvolvimento)**
   - Copiar o template e preencher valores:
     ```bash
     cp .env.example .env
     ```
   - A app carrega automaticamente `.env` **apenas em desenvolvimento** (`FLASK_ENV=development`).
   - O ficheiro `.env` deve manter-se local e já está no `.gitignore`.

4. **Criar base de dados**
   - Por omissão é usado `sqlite:///instance/gestor_lectivo.db` (sempre local).
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


## Supabase / PostgreSQL
- A app usa uma configuração única via `APP_DB_MODE`:
  - `APP_DB_MODE=sqlite` usa ficheiro local (`SQLITE_PATH`, default `gestor_lectivo.db`).
  - `APP_DB_MODE=postgres` usa `DATABASE_URL` (normaliza `postgres://` e força `sslmode=require` quando falta).
- Para backend Flask tradicional, preferir **Direct connection** (ligações long-lived). O **Pooler** é mais indicado para workloads serverless/funções com muitas ligações curtas.

### Arrancar em SQLite (dev/offline)
```bash
export APP_DB_MODE=sqlite
export SQLITE_PATH=gestor_lectivo.db
flask db upgrade
python app.py
```

### Arrancar em Supabase Postgres
```bash
export APP_DB_MODE=postgres
export DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/postgres?sslmode=require'
export SUPABASE_DB_MODE=direct   # direct|pooler
export SUPABASE_DB_PORT=5432     # 6543 para pooler
export SQLALCHEMY_ECHO=0
flask db upgrade
python app.py
```

### Modo offline (snapshot + outbox local)
Quando `APP_DB_MODE=postgres` e a ligação remota falha, a app ativa o fluxo offline em `/offline`.

1. Preparar snapshot antes de ficar sem rede:
   ```bash
   flask offline snapshot
   ```
2. Sem rede, usar `/offline` para:
   - escolher turma/aula do snapshot;
   - lançar presenças/avaliação por aluno;
   - guardar sumário/observações locais.
3. Quando a rede regressar, sincronizar:
   - pela UI em `/offline/sync`, ou
   - via botão "Sincronizar" no dashboard offline.

> O armazenamento offline usa sempre `instance/offline.db` (SQLite local), independentemente da base principal.


### Healthcheck da ligação remota
```bash
flask offline healthcheck
# ou HTTP:
curl -s http://127.0.0.1:5000/api/health/db
```

### Exportar schema atual do SQLite (baseline)
```bash
python tools/dump_sqlite_schema.py --sqlite-path gestor_lectivo.db --output tools/schema_sqlite.json
```

### Migrações de schema (Alembic)
Em PostgreSQL, o schema deve ser criado por migrações Alembic (não por DDL em runtime):
```bash
export DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/postgres?sslmode=require'
flask db upgrade
```

> Nota: durante a migração inicial para Supabase, aplique em base **vazia**. Se já existir schema antigo/parcial, faça reset do schema `public` antes de correr `flask db upgrade` para evitar conflitos de baseline.

### Reparar sequences no Supabase (PK id duplicada)
Se aparecer erro `duplicate key value violates unique constraint ..._pkey` em tabelas com `id`:

1. Via CLI da app (recomendado):
```bash
flask supabase-fix-sequences
```
2. Ou via Supabase SQL Editor: usar `db/supabase_fix_sequences.sql`.

### Migração de dados SQLite -> Postgres
Depois do schema criado no Postgres, migrar os dados:
```bash
python tools/migrate_sqlite_to_postgres.py
```

Opções úteis:
- `--sqlite-path instance/gestor_lectivo.db`
- `--database-url 'postgresql+psycopg://...'`
- `--wipe` para limpar o destino antes da importação.

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

## Grelha de Avaliação — Navegação e Edição Rápida

A grelha de avaliação suporta:

### EV2 (avaliação da aula) — fluxo compacto por aluno
- A grelha está centrada no aluno (uma linha por aluno).
- O grupo passa a ser um organizador leve (coluna **Grupo** + separadores compactos), sem linha pesada de avaliação própria.
- Apenas um domínio fica visível de cada vez, selecionado por tabs no topo.
- Ações rápidas disponíveis na barra:
  - aplicar **valor da célula** ao grupo do aluno-base;
  - aplicar **rubrica** ao grupo;
  - aplicar **domínio** ao grupo;
  - copiar domínio para aluno atual, grupo atual ou todos, apenas para destinos compatíveis.
- Ações da rubrica ativa (**Aplicar automático** e **Limpar avaliações**) ficam numa barra contextual acima da grelha:
  - selecionar a rubrica pelo cabeçalho ou por uma célula da coluna;
  - a barra mostra `Nome completo (Nome curto)` e aplica as ações à rubrica selecionada.
- Os blocos **Descritivo** e **Grupos desta avaliação** aparecem em acordeões independentes, fechados por defeito, com resumo no cabeçalho para poupar espaço vertical da grelha.
- Regras de segurança mantidas:
  - copiar apenas valores preenchidos;
  - nunca copiar vazios para apagar;
  - nunca sobrescrever overrides individuais;
  - sem autosave (continua obrigatório clicar em **Guardar**).

### Navegação por teclado
- Setas → mover entre células
- Enter → descer
- Tab / Shift+Tab → navegação padrão

### Atalhos de edição
- 0–9 → definir valor diretamente
- Delete / Backspace → limpar célula
- + → incrementar valor
- - → decrementar valor

### Persistência
- As alterações NÃO são guardadas automaticamente
- O utilizador deve usar o botão **Guardar**
- O estado “Alterações por guardar” indica modificações pendentes

## Otimizações técnicas
- Índices adicionados às tabelas de calendários, alunos e avaliações para acelerar listagens e mapas.
- Criação automática de tabelas/colunas novas e sincronização do `alembic_version` em bases antigas, reduzindo erros de arranque.
- Seletores de turmas filtram para anos letivos ativos e abertos em formulários de extras, calendário global e importações, evitando ações sobre anos fechados.

## Estratégia de Salvaguarda de Dados — Versão 2

### Problema a resolver
O SQLite não é adequado à sincronização concorrente de ficheiros binários. Sincronizar a base de dados ativa via OneDrive/Google Drive/Dropbox pode gerar conflitos e corrupção.

### Princípios adotados
- O ficheiro da base de dados ativa **nunca é sincronizado**.
- Cada computador trabalha sempre com **uma base de dados local**.
- A salvaguarda é feita através de **backups automáticos versionados**.
- **Apenas os backups** são sincronizados entre computadores.
- O **restauro é sempre manual e consciente**.

### Arquitetura (V2)
```
instance/
  gestor_lectivo.db          ← base de dados ativa (local)
  backups/
    2026-02-01_22-15-00.db
    2026-02-02_08-30-12.db
```

### Exclusões obrigatórias
- `instance/gestor_lectivo.db` nunca é sincronizado nem versionado em Git.
- `instance/backups/` pode ser sincronizada via cloud.

### Política de backups
**Quando é criado um backup**
- No arranque da aplicação (uma vez por sessão).

**Como é criado**
- Cópia integral do ficheiro SQLite.
- Nome baseado em data/hora e hostname (`YYYY-MM-DD_HH-MM-SS__HOSTNAME.db`).
- Preservação de permissões e metadata.
- Rotação automática (mantém os últimos 30 backups por defeito).

**Localização**
- `instance/backups/`

### Interface de backups
- A rota `/backups` lista os backups disponíveis, mostra o último backup e permite descarregar.
- O restauro é sempre manual (não existe qualquer automatismo de reposição).

### Fluxo de trabalho entre computadores
**Computador A**
1. Trabalha normalmente.
2. A aplicação cria backups automáticos.
3. Apenas a pasta `instance/backups/` é sincronizada para a cloud.

**Computador B**
1. Recebe os backups via cloud.
2. O utilizador escolhe manualmente o backup pretendido.
3. O ficheiro escolhido é copiado para `instance/gestor_lectivo.db`.
4. A aplicação é iniciada normalmente.

### Decisões técnicas explícitas
- Não é permitido abrir a aplicação diretamente sobre uma base de dados sincronizada.
- Não é permitida escrita concorrente sobre o mesmo ficheiro SQLite.
- O Git é utilizado apenas para código, nunca para dados.
- O OneDrive é utilizado apenas para transporte de backups, não como sistema de base de dados.

### Evolução prevista (futura)
Está prevista a migração para um sistema servidor (MySQL/PostgreSQL), permitindo:
- Acesso simultâneo.
- Histórico imutável.
- Conformidade legal reforçada.
- Backups transacionais.


### Snapshot automático (60s)
Em desenvolvimento/local:
```bash
pip install -r requirements.txt
export DEV_LOCAL_SCHEDULER=1
export SNAPSHOT_INTERVAL_SECONDS=60
python app.py
```

> Nota: o scheduler local usa `APScheduler`. Se faltar a dependência, o log mostra `DEV_LOCAL_SCHEDULER=1 mas APScheduler não está disponível.`

Em produção/serverless, use cron para chamar:
```bash
curl -X POST https://SEU_HOST/offline/snapshot?format=json
```

### Variáveis recomendadas (.env)
```env
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/postgres?sslmode=require
OFFLINE_DB_PATH=instance/offline.db
SUPABASE_DB_MODE=direct
DEV_LOCAL_SCHEDULER=1
SNAPSHOT_INTERVAL_SECONDS=60
```
