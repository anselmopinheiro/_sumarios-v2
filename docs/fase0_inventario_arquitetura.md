# Fase 0 — Inventário e mapa da arquitectura

## 1) Inventário do repositório (real)

### Árvore de pastas (nível útil)
- `app.py`, `config.py`, `models.py`, `sync.py`, `offline_store.py`, `offline_queue.py`, `offline_blueprint.py`, `calendario_service.py`
- `index.py` (entrypoint alternativo), `api/index.py` (app mínima)
- `migrations/env.py`, `migrations/versions/*.py`
- `templates/`, `static/`, `tests/`, `tools/`, `db/`, `exports/`

### Entrypoints/scripts relevantes
- **App principal (factory):** `app.py` (`create_app`) e execução direta em `__main__`.
- **Entrypoints alternativos:** `index.py`, `api/index.py`.
- **Seeds/scripts:** `seed.py`, `seed_interrupcoes.py`, scripts em `tools/`.
- **Migrações:** `migrations/env.py` + versões em `migrations/versions/`.

### Módulos por responsabilidade
- **Config:** `config.py`
- **Modelos ORM:** `models.py`
- **Rotas HTTP principais:** `app.py`
- **Blueprint offline:** `offline_blueprint.py`
- **Persistência offline (snapshot/outbox/state/errors):** `offline_store.py`
- **Fila offline legacy:** `offline_queue.py`
- **Sincronização remoto/local + sequences:** `sync.py`
- **Serviços de calendário e import/export:** `calendario_service.py`

---

## 2) Mapa de arquitectura (fluxo de inicialização)

```text
Config (config.py)
  -> create_app() (app.py)
      1. Flask(instance_relative_config=True)
      2. app.config.from_object(Config)
      3. logging + tx logging
      4. _setup_dual_db_engines(app) [engine_local/engine_remote em app.extensions]
      5. db.init_app(app)
      6. Migrate(app, db)
      7. app.register_blueprint(offline_bp)
      8. init offline DBs + ensures runtime
      9. define/serve routes
```

### Provas no código
- Factory e ordem base: `create_app`, `from_object`, `db.init_app`, `Migrate`, `register_blueprint`.
- Engines em runtime: `_setup_dual_db_engines` grava `engine_local`, `session_local_factory`, `engine_remote`, `session_remote_factory` em `app.extensions`.

---

## 3) DB mode switch (SQLite vs Postgres)

## Em `config.py`
- `APP_DB_MODE` default: `sqlite`; valores aceites: `sqlite|postgres`; inválido cai para `sqlite`.
- `SQLITE_PATH` default: `gestor_lectivo.db` (resolvido para absoluto relativo à raiz do repo).
- `SQLALCHEMY_DATABASE_URI` default: `sqlite:///...SQLITE_PATH`.
- Se `APP_DB_MODE=postgres` **e** `DATABASE_URL` definido, URI passa a `normalize_database_url(DATABASE_URL)`.
- `normalize_database_url(...)`:
  - troca `postgres://` por `postgresql://`;
  - injeta driver (`psycopg` ou `psycopg2`) se disponível;
  - garante `sslmode=require` quando ausente;
  - define `connect_timeout` e `statement_timeout`;
  - ajusta porta por `SUPABASE_DB_PORT` ou por `SUPABASE_DB_MODE` (`pooler=6543`, `direct=5432`).

## Em `app.py` (runtime)
- `_setup_dual_db_engines(app)` cria:
  - `engine_local` sempre em `sqlite:///<instance_path>/offline.db`.
  - `engine_remote` só quando `APP_DB_MODE=postgres` e URI remota existe.
- `before_request` usa healthcheck remoto para decidir estado online/offline e redirecionar `/` para `/offline/` quando offline.

---

## 4) Paths exactos de dados

## SQLite principal
- **Default real (código):** `<repo>/gestor_lectivo.db` (absolutizado por `config._absolute_sqlite_path`).
- **Override:** `SQLITE_PATH` (relativo ou absoluto).

## Offline SQLite
- **Default em `offline_store`:** `<instance_path>/offline.db`.
- **Override:** `OFFLINE_DB_PATH` (relativo a `instance_path` ou absoluto).
- **Inicialização:** `offline_store.init_offline_db(app.instance_path)` chamado durante startup.

## Backups
- Pasta de backups em config:
  - `DB_BACKUP_DIR` absoluto, se definido;
  - senão `<instance_path>/backups`.
- Política:
  - `BACKUP_KEEP` default 30;
  - `BACKUP_ON_STARTUP` default ligado;
  - `BACKUP_ON_COMMIT` default ligado;
  - debounce/threshold/check interval configuráveis.

---

## 5) Inconsistências detectadas nesta fase

## P0 — Duas resoluções diferentes para o “offline DB path”
- `offline_store.get_offline_db_path(...)` respeita `OFFLINE_DB_PATH`.
- `_setup_dual_db_engines` em `app.py` força `sqlite:///<instance_path>/offline.db` sem usar `OFFLINE_DB_PATH`.
- Impacto: risco de parte do sistema escrever/ler em ficheiros diferentes quando `OFFLINE_DB_PATH` é customizado.

**Proposta de unificação (incremental):**
1. Extrair resolvedor único de caminho offline (ex.: `offline_store.get_offline_db_path`).
2. Fazer `_setup_dual_db_engines` consumir esse resolvedor.
3. Logar no arranque o caminho efetivo do offline DB.
4. Adicionar teste de configuração para garantir que `OFFLINE_DB_PATH` afeta engine local e store.

## P0 — Divergência documentação vs default real do SQLite principal
- README afirma default `sqlite:///instance/gestor_lectivo.db`.
- `config.py` default efetivo é `sqlite:///<repo>/gestor_lectivo.db`.

**Proposta:** alinhar documentação e código (preferencialmente manter tudo em `instance/` por consistência operacional no Windows).

---

## 6) Variáveis de ambiente e defaults

| Variável | Default | Onde usada | Impacto |
|---|---:|---|---|
| `SECRET_KEY` | `dev` | `config.py` | Sessão/segurança Flask em dev. |
| `APP_DB_MODE` | `sqlite` | `config.py`, checks em `app.py`/`offline_blueprint.py`/`sync.py` | Escolhe backend principal e healthchecks remotos. |
| `SQLITE_PATH` | `gestor_lectivo.db` | `config.py` | Caminho da DB principal SQLite. |
| `DATABASE_URL` | vazio | `config.py`, `migrations/env.py` (indiretamente via config) | URI remota Postgres/Supabase. |
| `SUPABASE_DB_MODE` | `direct` | `config.py`, metadata em `offline_blueprint.py`/`sync.py` | Seleção de modo de conexão e porta sugerida. |
| `SUPABASE_DB_PORT` | vazio | `config.py` | Override de porta no netloc da URL. |
| `SUPABASE_CONNECT_TIMEOUT` | `5` | `config.py`, `app.py` | Timeout de conexão DB. |
| `SUPABASE_STATEMENT_TIMEOUT_MS` | `15000` | `config.py`, `app.py` | Timeout de statements via `options`. |
| `SQLALCHEMY_ECHO` | `0` | `config.py` | Verbosidade SQL. |
| `DB_BACKUP_DIR` | `<instance>/backups` | `config.py`, `app.py` | Destino de backups SQLite. |
| `BACKUP_KEEP` | `30` | `config.py`, `app.py` | Rotação de backups. |
| `BACKUP_ON_STARTUP` | ligado | `config.py`, `app.py` | Backup no arranque. |
| `BACKUP_ON_COMMIT` | ligado | `config.py`, `app.py` | Backups automáticos por alterações. |
| `BACKUP_DEBOUNCE_SECONDS` | `300` | `config.py`, `app.py` | Debounce de backup automático. |
| `BACKUP_CHANGE_THRESHOLD` | `15` | `config.py`, `app.py` | Limiar para disparar backup automático. |
| `BACKUP_CHECK_INTERVAL_SECONDS` | `30` | `config.py`, `app.py` | Intervalo do scheduler de backup. |
| `CSV_EXPORT_DIR` | `<repo>/exports` | `config.py`, `app.py` | Exportações CSV. |
| `BACKUP_JSON_DIR` | `<repo>/exports/backups` | `config.py`, `app.py` | Exportações JSON de backup. |
| `OFFLINE_DB_PATH` | `<instance>/offline.db` | `offline_store.py`, docs README/.env.example | Caminho do armazenamento offline. |
| `FLASK_ENV` | `development` | `app.py` | Carregamento automático do `.env`. |
| `FLASK_DEBUG` | `0` | `app.py` | Debug mode e comportamento de arranque. |
| `FLASK_USE_RELOADER` | `1` | `app.py` | Reloader no `app.run`. |
| `DEV_LOCAL_SCHEDULER` | `0` | `app.py` | Ativa scheduler local de snapshot. |
| `SNAPSHOT_INTERVAL_SECONDS` | `60` | `app.py` | Frequência do snapshot automático local. |
| `COMPUTERNAME` | sem default | `app.py` | Nome do host para naming de backups (Windows). |
| `WERKZEUG_RUN_MAIN` | sem default | `app.py` | Deteção de processo primário/duplicado no arranque. |

> Variáveis recomendadas no README e `.env.example` incluem: `APP_DB_MODE`, `DATABASE_URL`, `OFFLINE_DB_PATH`, `SUPABASE_DB_MODE`, `SUPABASE_DB_PORT`, `DEV_LOCAL_SCHEDULER`, `SNAPSHOT_INTERVAL_SECONDS`, etc.

---

## 7) Rotas e blueprints (inventário da fase 0)

- **Blueprint registado:** `offline_bp` (`offline_blueprint.py`) com `url_prefix="/offline"`, registado em `create_app()`.
- **Rotas principais com `@app.route/@app.get`:** concentradas em `app.py`.
- **Rotas do offline blueprint:** concentradas em `offline_blueprint.py`.
- **Entrypoints alternativos com routes simples:** `index.py` (`/health`) e `api/index.py` (`/`).

> Nesta fase foi feito apenas inventário estrutural; classificação/validação completa de rotas fica para a Fase 1.
