import json
import os
import sqlite3
from datetime import datetime, timedelta


def get_offline_db_path(instance_path=None):
    base = instance_path or os.path.join(os.getcwd(), "instance")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "offline_queue.db")


def init_offline_db(instance_path=None):
    db_path = get_offline_db_path(instance_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS outbox (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              created_at TEXT NOT NULL,
              entity TEXT NOT NULL,
              key TEXT NOT NULL,
              action TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'pending',
              tries INTEGER NOT NULL DEFAULT 0,
              last_error TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_outbox_status_created ON outbox(status, created_at)"
        )
        conn.commit()
    return db_path


def _connect(instance_path=None):
    path = get_offline_db_path(instance_path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def enqueue_upsert_aulas_alunos(aula_id, aluno_id, payload_dict, instance_path=None):
    now = datetime.utcnow().isoformat(timespec="seconds")
    key = f"aula_id={int(aula_id)};aluno_id={int(aluno_id)}"
    payload_json = json.dumps(payload_dict, ensure_ascii=False)

    with _connect(instance_path) as conn:
        row = conn.execute(
            """
            SELECT id FROM outbox
            WHERE entity='aulas_alunos' AND action='upsert' AND key=? AND status='pending'
            ORDER BY id DESC LIMIT 1
            """,
            (key,),
        ).fetchone()

        if row:
            conn.execute(
                """
                UPDATE outbox
                SET payload_json=?, created_at=?, last_error=NULL
                WHERE id=?
                """,
                (payload_json, now, row["id"]),
            )
            outbox_id = row["id"]
        else:
            cur = conn.execute(
                """
                INSERT INTO outbox (created_at, entity, key, action, payload_json, status)
                VALUES (?, 'aulas_alunos', ?, 'upsert', ?, 'pending')
                """,
                (now, key, payload_json),
            )
            outbox_id = cur.lastrowid

        conn.commit()
    return outbox_id


def pending_count(instance_path=None):
    with _connect(instance_path) as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM outbox WHERE status='pending'").fetchone()
        return int(row["n"] if row else 0)


def list_pending(limit=200, instance_path=None):
    with _connect(instance_path) as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, entity, key, action, payload_json, status, tries, last_error
            FROM outbox
            WHERE status='pending'
            ORDER BY created_at ASC, id ASC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            items.append(item)
        return items


def mark_sent(item_id, instance_path=None):
    with _connect(instance_path) as conn:
        conn.execute(
            """
            UPDATE outbox
            SET status='sent', tries=tries+1, last_error=NULL
            WHERE id=?
            """,
            (int(item_id),),
        )
        conn.commit()


def mark_error(item_id, error, instance_path=None):
    message = str(error)[:2000]
    with _connect(instance_path) as conn:
        conn.execute(
            """
            UPDATE outbox
            SET status='pending', tries=tries+1, last_error=?
            WHERE id=?
            """,
            (message, int(item_id)),
        )
        conn.commit()


def clear_sent(older_than_days=30, instance_path=None):
    cutoff = (datetime.utcnow() - timedelta(days=int(older_than_days))).isoformat(timespec="seconds")
    with _connect(instance_path) as conn:
        conn.execute(
            "DELETE FROM outbox WHERE status='sent' AND created_at < ?",
            (cutoff,),
        )
        conn.commit()


def flush_pending(apply_fn, limit=200, instance_path=None):
    applied = 0
    errors = 0
    items = list_pending(limit=limit, instance_path=instance_path)
    for item in items:
        try:
            apply_fn(item["payload"])
            mark_sent(item["id"], instance_path=instance_path)
            applied += 1
        except Exception as exc:
            mark_error(item["id"], exc, instance_path=instance_path)
            errors += 1
    return {"applied": applied, "errors": errors, "remaining": pending_count(instance_path=instance_path)}


def get_last_error(instance_path=None):
    with _connect(instance_path) as conn:
        row = conn.execute(
            "SELECT last_error FROM outbox WHERE last_error IS NOT NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row["last_error"] if row else None
