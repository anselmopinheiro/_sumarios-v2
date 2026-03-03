# Supabase (PostgreSQL) — Bootstrap de migrations Flask do zero

Este guia garante que uma base nova Supabase é criada **exclusivamente por migrations** (sem auto-criação de tabelas no arranque da app).

## 1) Pré-requisitos
- `Flask`, `Flask-SQLAlchemy`, `Flask-Migrate`, `SQLAlchemy`, `psycopg` instalados.
- `DATABASE_URL` da instância Supabase (DB Postgres) disponível.
- Modelos SQLAlchemy já definidos.

## 2) Variáveis de ambiente recomendadas

```bash
export DATABASE_URL="postgresql+psycopg://USER:PASSWORD@HOST:5432/postgres"
export FLASK_ENV=development
export APP_DB_MODE=postgres
export SKIP_DB_BOOTSTRAP=1
```

> `SKIP_DB_BOOTSTRAP=1` evita lógica de bootstrap com queries automáticas durante `flask db ...`.

## 3) Inicializar migrations (apenas se necessário)

Se a pasta `migrations/` não existir ainda:

```bash
flask --app app db init
```

Isto cria:
- `migrations/env.py`
- `migrations/script.py.mako`
- `migrations/versions/`

## 4) Gerar migration inicial

```bash
flask --app app db migrate -m "0001_initial"
```

A revisão gerada deve ficar em `migrations/versions/`.

## 5) Aplicar migration na base Supabase nova

```bash
flask --app app db upgrade
```

## 6) Verificar no Supabase SQL Editor

```sql
select table_schema, table_name
from information_schema.tables
where table_schema = 'public'
order by table_name;
```

## 7) Confirmar ligação do autogenerate ao metadata

No `migrations/env.py`, validar que o `target_metadata` aponta para metadata dos modelos, por exemplo:

```python
target_metadata = db.metadata
```

ou equivalente (ex.: `Base.metadata`, ou helper que devolve metadata do `db`).

## 8) Boas práticas
- Não comitar `.env` reais.
- Usar apenas `.env.example` no repositório.
- Nunca expor `SUPABASE_SERVICE_ROLE_KEY` em endpoints/respostas.
- Ativar RLS nas tabelas públicas no Supabase.
- Produção: variáveis reais no host/secret manager, não em ficheiros versionados.

## 9) Troubleshooting rápido
- Se `flask db migrate` ou `upgrade` executar queries inesperadas no startup da app:
  - confirmar `SKIP_DB_BOOTSTRAP=1` no ambiente do comando;
  - confirmar no log da app a mensagem de bootstrap ignorado.
