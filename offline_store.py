import json
import logging
import os
import re
import sqlite3
import traceback
from datetime import datetime, timezone


SNAPSHOT_TABLES = {
    "snapshot_turmas": ("id",),
    "snapshot_alunos": ("id",),
    "snapshot_periodos": ("id",),
    "snapshot_modulos": ("id",),
    "snapshot_calendario_aulas": ("id",),
}

UNIQUE_VIOLATION_CODE = "23505"

logger = logging.getLogger(__name__)


def _is_missing_table_error(exc, table_name):
    msg = str(exc or "").lower()
    return f"no such table: {table_name}" in msg


def get_offline_db_path(instance_path):
    os.makedirs(instance_path, exist_ok=True)
    override = (os.environ.get("OFFLINE_DB_PATH") or "").strip()
    if override:
        return override if os.path.isabs(override) else os.path.abspath(os.path.join(instance_path, override))
    return os.path.join(instance_path, "offline.db")


def _connect(instance_path):
    conn = sqlite3.connect(get_offline_db_path(instance_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_offline_db(instance_path):
    with _connect(instance_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS snapshot_turmas (
              id INTEGER PRIMARY KEY,
              nome TEXT NOT NULL,
              ano_letivo_id INTEGER,
              tipo TEXT,
              letiva INTEGER,
              periodo_tipo TEXT,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS snapshot_alunos (
              id INTEGER PRIMARY KEY,
              turma_id INTEGER NOT NULL,
              numero INTEGER,
              nome TEXT NOT NULL,
              nome_curto TEXT,
              nee TEXT,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS snapshot_periodos (
              id INTEGER PRIMARY KEY,
              turma_id INTEGER NOT NULL,
              nome TEXT,
              tipo TEXT,
              data_inicio TEXT,
              data_fim TEXT,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS snapshot_modulos (
              id INTEGER PRIMARY KEY,
              turma_id INTEGER NOT NULL,
              nome TEXT,
              total_aulas INTEGER,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS snapshot_calendario_aulas (
              id INTEGER PRIMARY KEY,
              turma_id INTEGER NOT NULL,
              periodo_id INTEGER,
              data TEXT,
              weekday INTEGER,
              modulo_id INTEGER,
              numero_modulo INTEGER,
              total_geral INTEGER,
              tipo TEXT,
              apagado INTEGER,
              tempos_sem_aula INTEGER,
              atividade INTEGER,
              atividade_nome TEXT,
              previsao TEXT,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS outbox (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              op_type TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'pending',
              last_error TEXT
            );

            CREATE TABLE IF NOT EXISTS offline_aulas_alunos (
              aula_id INTEGER NOT NULL,
              aluno_id INTEGER NOT NULL,
              atraso INTEGER NOT NULL DEFAULT 0,
              faltas INTEGER NOT NULL DEFAULT 0,
              responsabilidade INTEGER,
              comportamento INTEGER,
              participacao INTEGER,
              trabalho_autonomo INTEGER,
              portatil_material INTEGER,
              atividade INTEGER,
              falta_disciplinar INTEGER NOT NULL DEFAULT 0,
              observacoes TEXT,
              updated_at TEXT NOT NULL,
              PRIMARY KEY (aula_id, aluno_id)
            );

            CREATE TABLE IF NOT EXISTS offline_sumarios (
              aula_id INTEGER PRIMARY KEY,
              sumario TEXT,
              observacoes TEXT,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS snapshot_runs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              started_at TEXT NOT NULL,
              finished_at TEXT,
              ok INTEGER NOT NULL DEFAULT 0,
              error TEXT,
              counts_json TEXT,
              mode TEXT
            );

            CREATE TABLE IF NOT EXISTS offline_settings (
              key TEXT PRIMARY KEY,
              value TEXT
            );

            CREATE TABLE IF NOT EXISTS offline_errors (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              created_at TEXT NOT NULL,
              operation TEXT NOT NULL,
              summary TEXT NOT NULL,
              details TEXT,
              context_json JSON
            );

            CREATE TABLE IF NOT EXISTS offline_state (
              key TEXT PRIMARY KEY,
              value TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_outbox_status_created ON outbox(status, created_at);
            CREATE INDEX IF NOT EXISTS idx_snapshot_alunos_turma ON snapshot_alunos(turma_id);
            CREATE INDEX IF NOT EXISTS idx_snapshot_aulas_turma_data ON snapshot_calendario_aulas(turma_id, data);
            CREATE INDEX IF NOT EXISTS idx_snapshot_runs_started_at ON snapshot_runs(started_at DESC);
            CREATE INDEX IF NOT EXISTS idx_offline_errors_created_at ON offline_errors(created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_offline_errors_operation ON offline_errors(operation);
            """
        )
        colunas_offline_aulas_alunos = {
            row["name"] for row in conn.execute("PRAGMA table_info(offline_aulas_alunos)").fetchall()
        }
        if "observacoes" not in colunas_offline_aulas_alunos:
            conn.execute("ALTER TABLE offline_aulas_alunos ADD COLUMN observacoes TEXT")


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_iso_utc(raw):
    if not raw:
        return None
    value = str(raw).strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _truncate_summary(text, limit=120):
    clean = " ".join((text or "").split())
    if len(clean) <= int(limit):
        return clean
    return clean[: int(limit) - 3].rstrip() + "..."


def make_error_summary(exc):
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    constraint_name = getattr(diag, "constraint_name", None) if diag else None
    code = getattr(orig, "pgcode", None) or getattr(orig, "sqlstate", None)
    message = str(exc or "")

    unique_violation = bool(code == UNIQUE_VIOLATION_CODE)
    if not unique_violation:
        lower_msg = message.lower()
        unique_violation = (
            "duplicate key value violates unique constraint" in lower_msg
            or "unique constraint" in lower_msg
        )

    if unique_violation:
        if not constraint_name:
            match = re.search(r'constraint\s+"([^"]+)"', message, flags=re.IGNORECASE)
            if match:
                constraint_name = match.group(1)
        base = "Conflito de registos (chave duplicada)"
        return f"{base} [{constraint_name}]" if constraint_name else base

    snippet = _truncate_summary(message, limit=120)
    if snippet:
        return f"{exc.__class__.__name__}: {snippet}"
    return exc.__class__.__name__


def record_offline_error(instance_path, operation, exc, context=None):
    summary = make_error_summary(exc)
    details = traceback.format_exc()
    if not details or details.strip() == "NoneType: None":
        details = f"{exc.__class__.__name__}: {exc}"
    created_at = _utc_now_iso()

    serialized_context = None
    if context is not None:
        try:
            serialized_context = json.dumps(context, ensure_ascii=False, sort_keys=True)
        except TypeError:
            serialized_context = json.dumps({"context_repr": repr(context)}, ensure_ascii=False)

    with _connect(instance_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO offline_errors (created_at, operation, summary, details, context_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                created_at,
                (str(operation or "other")[:32] or "other"),
                summary,
                details,
                serialized_context,
            ),
        )
        return int(cur.lastrowid)


def list_offline_errors(instance_path, limit=50):
    limit_clause = ""
    params = []
    if limit is not None:
        limit_clause = " LIMIT ?"
        params.append(int(limit))

    with _connect(instance_path) as conn:
        rows = conn.execute(
            f"""
            SELECT id, created_at, operation, summary, details, context_json
            FROM offline_errors
            ORDER BY created_at DESC, id DESC
            {limit_clause}
            """,
            tuple(params),
        ).fetchall()

    items = []
    for row in rows:
        item = dict(row)
        raw_context = item.get("context_json")
        if raw_context:
            try:
                item["context_json"] = json.loads(raw_context)
            except Exception:
                item["context_json"] = raw_context
        else:
            item["context_json"] = None
        items.append(item)
    return items


def count_offline_errors(instance_path):
    try:
        with _connect(instance_path) as conn:
            row = conn.execute("SELECT COUNT(*) n FROM offline_errors").fetchone()
            return int(row["n"] if row else 0)
    except sqlite3.OperationalError as exc:
        if _is_missing_table_error(exc, "offline_errors"):
            logger.warning("offline_errors table missing in %s; returning 0", get_offline_db_path(instance_path))
            return 0
        raise



def get_last_offline_error(instance_path):
    try:
        with _connect(instance_path) as conn:
            row = conn.execute(
                """
                SELECT id, created_at, operation, summary, details, context_json
                FROM offline_errors
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
    except sqlite3.OperationalError as exc:
        if _is_missing_table_error(exc, "offline_errors"):
            logger.warning("offline_errors table missing in %s; returning None", get_offline_db_path(instance_path))
            return None
        raise

    if not row:
        return None
    item = dict(row)
    raw_context = item.get("context_json")
    if raw_context:
        try:
            item["context_json"] = json.loads(raw_context)
        except Exception:
            item["context_json"] = raw_context
    else:
        item["context_json"] = None
    return item


def delete_offline_error(instance_path, error_id):
    with _connect(instance_path) as conn:
        cur = conn.execute("DELETE FROM offline_errors WHERE id=?", (int(error_id),))
        return int(cur.rowcount or 0) > 0


def clear_offline_errors(instance_path):
    with _connect(instance_path) as conn:
        cur = conn.execute("DELETE FROM offline_errors")
        return int(cur.rowcount or 0)


def set_state_datetime(instance_path, key, dt_utc):
    if dt_utc is None:
        with _connect(instance_path) as conn:
            conn.execute("DELETE FROM offline_state WHERE key=?", (str(key),))
        return

    if isinstance(dt_utc, datetime):
        dt = dt_utc
    else:
        dt = _parse_iso_utc(dt_utc)
        if dt is None:
            dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    value = dt.astimezone(timezone.utc).isoformat(timespec="seconds")
    with _connect(instance_path) as conn:
        conn.execute(
            """
            INSERT INTO offline_state (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (str(key), value),
        )


def get_state_datetime(instance_path, key):
    try:
        with _connect(instance_path) as conn:
            row = conn.execute("SELECT value FROM offline_state WHERE key=?", (str(key),)).fetchone()
    except sqlite3.OperationalError as exc:
        if _is_missing_table_error(exc, "offline_state"):
            logger.warning("offline_state table missing in %s; returning None", get_offline_db_path(instance_path))
            return None
        raise
    if not row:
        return None
    return _parse_iso_utc(row["value"])



def is_online(app, ping_fn):
    if (app.config.get("APP_DB_MODE") or "sqlite").lower() != "postgres":
        return False
    try:
        ping_fn()
        return True
    except Exception:
        return False


def _upsert_rows(conn, table_name, rows, conflict_cols):
    if not rows:
        return 0

    cols = list(rows[0].keys())
    placeholders = ",".join(["?"] * len(cols))
    update_cols = [c for c in cols if c not in conflict_cols]
    update_clause = ", ".join([f"{c}=excluded.{c}" for c in update_cols])
    sql = (
        f"INSERT INTO {table_name} ({','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT({','.join(conflict_cols)}) DO UPDATE SET {update_clause}"
    )
    conn.executemany(sql, [tuple(r.get(c) for c in cols) for r in rows])
    return len(rows)


def upsert_snapshot_batch(instance_path, snapshot_data):
    counts = {}
    with _connect(instance_path) as conn:
        for table_name, rows in snapshot_data.items():
            conflict_cols = SNAPSHOT_TABLES.get(table_name)
            if not conflict_cols:
                continue
            counts[table_name] = _upsert_rows(conn, table_name, rows or [], conflict_cols)
    return counts


def replace_snapshot(instance_path, table_name, rows):
    """Compatibilidade retroativa. Evitar em novos fluxos para não apagar snapshot local."""
    with _connect(instance_path) as conn:
        conflict_cols = SNAPSHOT_TABLES.get(table_name)
        if not conflict_cols:
            conn.execute(f"DELETE FROM {table_name}")
            if rows:
                cols = list(rows[0].keys())
                placeholders = ",".join(["?"] * len(cols))
                sql = f"INSERT INTO {table_name} ({','.join(cols)}) VALUES ({placeholders})"
                conn.executemany(sql, [tuple(r.get(c) for c in cols) for r in rows])
            return
        _upsert_rows(conn, table_name, rows or [], conflict_cols)


def list_snapshot_turmas(instance_path):
    with _connect(instance_path) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM snapshot_turmas ORDER BY nome").fetchall()]


def list_snapshot_aulas(instance_path, turma_id, limit=120):
    with _connect(instance_path) as conn:
        return [
            dict(r)
            for r in conn.execute(
                """
                SELECT *
                FROM snapshot_calendario_aulas
                WHERE turma_id=? AND COALESCE(apagado, 0)=0
                ORDER BY data DESC, id DESC
                LIMIT ?
                """,
                (int(turma_id), int(limit)),
            ).fetchall()
        ]


def list_snapshot_alunos(instance_path, turma_id):
    with _connect(instance_path) as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM snapshot_alunos WHERE turma_id=? ORDER BY (numero IS NULL), numero, nome",
                (int(turma_id),),
            ).fetchall()
        ]


def get_snapshot_aula(instance_path, aula_id):
    with _connect(instance_path) as conn:
        row = conn.execute("SELECT * FROM snapshot_calendario_aulas WHERE id=?", (int(aula_id),)).fetchone()
        return dict(row) if row else None


def get_offline_aulas_alunos(instance_path, aula_id):
    with _connect(instance_path) as conn:
        rows = conn.execute(
            "SELECT * FROM offline_aulas_alunos WHERE aula_id=?",
            (int(aula_id),),
        ).fetchall()
        return {r["aluno_id"]: dict(r) for r in rows}


def get_offline_sumario(instance_path, aula_id):
    with _connect(instance_path) as conn:
        row = conn.execute("SELECT * FROM offline_sumarios WHERE aula_id=?", (int(aula_id),)).fetchone()
        return dict(row) if row else None


def upsert_offline_aulas_alunos(instance_path, aula_id, aluno_payloads):
    ts = datetime.utcnow().isoformat(timespec="seconds")
    with _connect(instance_path) as conn:
        for item in aluno_payloads:
            aluno_id = int(item["aluno_id"])
            p = item["payload"]
            conn.execute(
                """
                INSERT INTO offline_aulas_alunos
                (aula_id, aluno_id, atraso, faltas, responsabilidade, comportamento, participacao,
                 trabalho_autonomo, portatil_material, atividade, falta_disciplinar, observacoes, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(aula_id, aluno_id) DO UPDATE SET
                  atraso=excluded.atraso,
                  faltas=excluded.faltas,
                  responsabilidade=excluded.responsabilidade,
                  comportamento=excluded.comportamento,
                  participacao=excluded.participacao,
                  trabalho_autonomo=excluded.trabalho_autonomo,
                  portatil_material=excluded.portatil_material,
                  atividade=excluded.atividade,
                  falta_disciplinar=excluded.falta_disciplinar,
                  observacoes=excluded.observacoes,
                  updated_at=excluded.updated_at
                """,
                (
                    int(aula_id),
                    aluno_id,
                    1 if p.get("atraso") else 0,
                    int(p.get("faltas") or 0),
                    p.get("responsabilidade"),
                    p.get("comportamento"),
                    p.get("participacao"),
                    p.get("trabalho_autonomo"),
                    p.get("portatil_material"),
                    p.get("atividade"),
                    int(p.get("falta_disciplinar") or 0),
                    p.get("observacoes"),
                    ts,
                ),
            )


def upsert_offline_sumario(instance_path, aula_id, sumario, observacoes):
    ts = datetime.utcnow().isoformat(timespec="seconds")
    with _connect(instance_path) as conn:
        conn.execute(
            """
            INSERT INTO offline_sumarios (aula_id, sumario, observacoes, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(aula_id) DO UPDATE SET
              sumario=excluded.sumario,
              observacoes=excluded.observacoes,
              updated_at=excluded.updated_at
            """,
            (int(aula_id), sumario, observacoes, ts),
        )


def enqueue_outbox(instance_path, op_type, payload):
    with _connect(instance_path) as conn:
        conn.execute(
            "INSERT INTO outbox (op_type, payload_json, created_at, status) VALUES (?, ?, ?, 'pending')",
            (
                op_type,
                json.dumps(payload, ensure_ascii=False),
                datetime.utcnow().isoformat(timespec="seconds"),
            ),
        )


def list_outbox(instance_path, status="pending", limit=200):
    with _connect(instance_path) as conn:
        rows = conn.execute(
            "SELECT * FROM outbox WHERE status=? ORDER BY created_at ASC, id ASC LIMIT ?",
            (status, int(limit)),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            items.append(item)
        return items


def mark_outbox(instance_path, item_id, status, last_error=None):
    with _connect(instance_path) as conn:
        conn.execute(
            "UPDATE outbox SET status=?, last_error=? WHERE id=?",
            (status, (str(last_error)[:2000] if last_error else None), int(item_id)),
        )


def outbox_status(instance_path):
    try:
        with _connect(instance_path) as conn:
            pending = conn.execute("SELECT COUNT(*) n FROM outbox WHERE status='pending'").fetchone()["n"]
            errors = conn.execute("SELECT COUNT(*) n FROM outbox WHERE status='error'").fetchone()["n"]
            last_error_row = conn.execute(
                "SELECT last_error FROM outbox WHERE last_error IS NOT NULL ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return {
                "pending": int(pending),
                "errors": int(errors),
                "last_error": last_error_row["last_error"] if last_error_row else None,
            }
    except sqlite3.OperationalError as exc:
        if _is_missing_table_error(exc, "outbox"):
            logger.warning("offline outbox table missing in %s; returning zero status", get_offline_db_path(instance_path))
            return {
                "pending": 0,
                "errors": 0,
                "last_error": None,
            }
        raise



def start_snapshot_run(instance_path, mode="manual"):
    started_at = datetime.utcnow().isoformat(timespec="seconds")
    with _connect(instance_path) as conn:
        cur = conn.execute(
            "INSERT INTO snapshot_runs (started_at, ok, mode) VALUES (?, 0, ?)",
            (started_at, mode),
        )
        return int(cur.lastrowid), started_at


def finish_snapshot_run(instance_path, run_id, ok, counts=None, error=None):
    finished_at = datetime.utcnow().isoformat(timespec="seconds")
    with _connect(instance_path) as conn:
        conn.execute(
            """
            UPDATE snapshot_runs
               SET finished_at=?, ok=?, error=?, counts_json=?
             WHERE id=?
            """,
            (
                finished_at,
                1 if ok else 0,
                (str(error)[:2000] if error else None),
                (json.dumps(counts or {}, ensure_ascii=False) if counts is not None else None),
                int(run_id),
            ),
        )


def list_snapshot_runs(instance_path, limit=20):
    with _connect(instance_path) as conn:
        rows = conn.execute(
            "SELECT * FROM snapshot_runs ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        raw = item.get("counts_json")
        item["counts"] = json.loads(raw) if raw else {}
        items.append(item)
    return items


def get_snapshot_status(instance_path):
    try:
        with _connect(instance_path) as conn:
            last = conn.execute("SELECT * FROM snapshot_runs ORDER BY id DESC LIMIT 1").fetchone()
            counts = {
                "turmas": conn.execute("SELECT COUNT(*) n FROM snapshot_turmas").fetchone()["n"],
                "alunos": conn.execute("SELECT COUNT(*) n FROM snapshot_alunos").fetchone()["n"],
                "aulas": conn.execute("SELECT COUNT(*) n FROM snapshot_calendario_aulas").fetchone()["n"],
                "periodos": conn.execute("SELECT COUNT(*) n FROM snapshot_periodos").fetchone()["n"],
                "modulos": conn.execute("SELECT COUNT(*) n FROM snapshot_modulos").fetchone()["n"],
            }
    except sqlite3.OperationalError as exc:
        if any(_is_missing_table_error(exc, t) for t in (
            "snapshot_runs",
            "snapshot_turmas",
            "snapshot_alunos",
            "snapshot_calendario_aulas",
            "snapshot_periodos",
            "snapshot_modulos",
        )):
            logger.warning("snapshot tables missing in %s; returning zero snapshot status", get_offline_db_path(instance_path))
            return {
                "last_run": None,
                "counts": {
                    "turmas": 0,
                    "alunos": 0,
                    "aulas": 0,
                    "periodos": 0,
                    "modulos": 0,
                },
            }
        raise
    return {
        "last_run": dict(last) if last else None,
        "counts": {k: int(v) for k, v in counts.items()},
    }



def get_setting(instance_path, key, default=None):
    try:
        with _connect(instance_path) as conn:
            row = conn.execute("SELECT value FROM offline_settings WHERE key=?", (key,)).fetchone()
            if not row:
                return default
            return row["value"]
    except sqlite3.OperationalError as exc:
        if _is_missing_table_error(exc, "offline_settings"):
            logger.warning("offline_settings table missing in %s; returning default for key '%s'", get_offline_db_path(instance_path), key)
            return default
        raise



def set_setting(instance_path, key, value):
    with _connect(instance_path) as conn:
        conn.execute(
            """
            INSERT INTO offline_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (str(key), str(value) if value is not None else ""),
        )
