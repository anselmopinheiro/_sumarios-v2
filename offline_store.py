import json
import os
import sqlite3
from datetime import datetime


SNAPSHOT_TABLES = {
    "snapshot_turmas": ("id",),
    "snapshot_alunos": ("id",),
    "snapshot_periodos": ("id",),
    "snapshot_modulos": ("id",),
    "snapshot_calendario_aulas": ("id",),
}


def get_offline_db_path(instance_path):
    os.makedirs(instance_path, exist_ok=True)
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
              updated_at TEXT NOT NULL,
              PRIMARY KEY (aula_id, aluno_id)
            );

            CREATE TABLE IF NOT EXISTS offline_sumarios (
              aula_id INTEGER PRIMARY KEY,
              sumario TEXT,
              observacoes TEXT,
              updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_outbox_status_created ON outbox(status, created_at);
            CREATE INDEX IF NOT EXISTS idx_snapshot_alunos_turma ON snapshot_alunos(turma_id);
            CREATE INDEX IF NOT EXISTS idx_snapshot_aulas_turma_data ON snapshot_calendario_aulas(turma_id, data);
            """
        )


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
                 trabalho_autonomo, portatil_material, atividade, falta_disciplinar, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
