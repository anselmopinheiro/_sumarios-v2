import re

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from models import db
from offline_store import (
    get_snapshot_aula,
    list_outbox,
    list_snapshot_turmas,
    mark_outbox,
    outbox_status,
    record_offline_error,
)


def _target_from_app(app):
    uri = app.config.get("SQLALCHEMY_DATABASE_URI") or ""
    mode = app.config.get("SUPABASE_DB_MODE", "direct")
    try:
        parsed = make_url(uri)
        return {
            "host": parsed.host or "-",
            "port": parsed.port or "-",
            "db": parsed.database or "-",
            "mode": mode,
        }
    except Exception:
        return {"host": "-", "port": "-", "db": "-", "mode": mode}


def _record_sync_error(app, exc, context):
    try:
        record_offline_error(app.instance_path, "sync", exc, context=context)
    except Exception:
        app.logger.exception("Falha ao registar erro de sync no offline_errors.")


def _quote_ident(ident):
    return '"' + str(ident).replace('"', '""') + '"'


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _table_for_op(op_type):
    if op_type == "UPSERT_AULAS_ALUNOS":
        return "aulas_alunos"
    if op_type == "UPDATE_SUMARIO":
        return "calendario_aulas"
    return "other"


def _build_item_error_context(app, item, turma_lookup, aula_turma_cache, extra=None):
    payload = item.get("payload") or {}
    op_type = item.get("op_type")
    context = {
        "outbox_id": int(item.get("id") or 0),
        "op_type": op_type,
        "table": _table_for_op(op_type),
    }

    aula_id = _safe_int(payload.get("aula_id"))
    if aula_id is not None:
        context["aula_id"] = aula_id

    if op_type == "UPSERT_AULAS_ALUNOS":
        items = payload.get("items") or []
        context["aluno_count"] = len(items)
        if len(items) == 1:
            aluno_id = _safe_int((items[0] or {}).get("aluno_id"))
            if aluno_id is not None:
                context["aluno_id"] = aluno_id
        elif len(items) > 1:
            context["aluno_ids"] = [
                int(i["aluno_id"])
                for i in items[:20]
                if _safe_int((i or {}).get("aluno_id")) is not None
            ]

    turma_id = _safe_int(payload.get("turma_id"))
    if turma_id is None and aula_id is not None:
        if aula_id not in aula_turma_cache:
            aula = get_snapshot_aula(app.instance_path, aula_id)
            aula_turma_cache[aula_id] = _safe_int((aula or {}).get("turma_id"))
        turma_id = aula_turma_cache.get(aula_id)

    if turma_id is not None:
        context["turma_id"] = turma_id
        turma_nome = turma_lookup.get(turma_id)
        if turma_nome:
            context["turma_nome"] = turma_nome

    if extra:
        context.update(extra)
    return context


def _extract_pk_table_name(exc):
    # prioridade: metadata do driver (psycopg)
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    if diag:
        table_name = getattr(diag, "table_name", None)
        constraint_name = getattr(diag, "constraint_name", None)
        if table_name:
            return table_name
        if constraint_name and constraint_name.endswith("_pkey"):
            return constraint_name[:-5]

    # fallback textual
    message = str(exc)
    match = re.search(r'constraint\s+"([a-zA-Z0-9_]+)_pkey"', message)
    if match:
        return match.group(1)

    # fallback para mensagens sem constraint explicita
    match = re.search(r"Key \(id\)=", message)
    if match:
        return "aulas_alunos"
    return None


def _is_unique_violation(exc):
    orig = getattr(exc, "orig", None)
    pgcode = getattr(orig, "pgcode", None)
    if pgcode == "23505":
        return True
    return "duplicate key value violates unique constraint" in str(exc)


def _repair_sequence_for_table(app, schema_name, table_name):
    schema_q = _quote_ident(schema_name)
    table_q = _quote_ident(table_name)
    table_fq = f"{schema_name}.{table_name}"

    seq_name = db.session.execute(
        text("SELECT pg_get_serial_sequence(:table_fq, 'id')"),
        {"table_fq": table_fq},
    ).scalar()

    if not seq_name:
        seq_name = f"{schema_name}.{table_name}_id_seq"
        seq_q = f"{schema_q}.{_quote_ident(table_name + '_id_seq')}"
        app.logger.warning(
            "sequence ausente; a criar default para tabela=%s.%s usando %s",
            schema_name,
            table_name,
            seq_name,
        )
        db.session.execute(text(f"CREATE SEQUENCE IF NOT EXISTS {seq_q}"))
        db.session.execute(
            text(
                f"ALTER TABLE {schema_q}.{table_q} "
                f"ALTER COLUMN id SET DEFAULT nextval('{seq_name}')"
            )
        )
        db.session.execute(text(f"ALTER SEQUENCE {seq_q} OWNED BY {schema_q}.{table_q}.id"))

    max_id = db.session.execute(text(f"SELECT COALESCE(MAX(id), 1) FROM {schema_q}.{table_q}")).scalar() or 1
    db.session.execute(
        text("SELECT setval(:seq_name, :max_id, true)"),
        {"seq_name": seq_name, "max_id": int(max_id)},
    )
    app.logger.info(
        "FIX SEQ OK | table=%s.%s | sequence=%s | max_id=%s",
        schema_name,
        table_name,
        seq_name,
        max_id,
    )


def fix_sequences_remote(app, schema_name="public"):
    if (app.config.get("APP_DB_MODE") or "sqlite").lower() != "postgres":
        return {"ok": False, "error": "APP_DB_MODE nao esta em postgres.", "tables": []}

    rows = db.session.execute(
        text(
            """
            SELECT c.table_schema, c.table_name
            FROM information_schema.columns c
            JOIN information_schema.tables t
              ON t.table_schema = c.table_schema
             AND t.table_name = c.table_name
            WHERE c.table_schema = :schema_name
              AND c.column_name = 'id'
              AND t.table_type = 'BASE TABLE'
            ORDER BY c.table_name
            """
        ),
        {"schema_name": schema_name},
    ).fetchall()

    fixed_tables = []
    for row in rows:
        _repair_sequence_for_table(app, row.table_schema, row.table_name)
        fixed_tables.append(f"{row.table_schema}.{row.table_name}")

    db.session.commit()
    return {"ok": True, "tables": fixed_tables}


def _apply_outbox_item(item):
    if item["op_type"] == "UPSERT_AULAS_ALUNOS":
        aula_id = int(item["payload"]["aula_id"])
        for aluno_item in item["payload"].get("items", []):
            aluno_id = int(aluno_item["aluno_id"])
            payload = aluno_item.get("payload") or {}
            # intencionalmente sem coluna id (somente chave natural aula_id+aluno_id)
            db.session.execute(
                text(
                    """
                    INSERT INTO aulas_alunos
                    (aula_id, aluno_id, atraso, faltas, responsabilidade, comportamento,
                     participacao, trabalho_autonomo, portatil_material, atividade, falta_disciplinar, observacoes)
                    VALUES
                    (:aula_id, :aluno_id, :atraso, :faltas, :responsabilidade, :comportamento,
                     :participacao, :trabalho_autonomo, :portatil_material, :atividade, :falta_disciplinar, :observacoes)
                    ON CONFLICT (aula_id, aluno_id) DO UPDATE SET
                      atraso = EXCLUDED.atraso,
                      faltas = EXCLUDED.faltas,
                      responsabilidade = EXCLUDED.responsabilidade,
                      comportamento = EXCLUDED.comportamento,
                      participacao = EXCLUDED.participacao,
                      trabalho_autonomo = EXCLUDED.trabalho_autonomo,
                      portatil_material = EXCLUDED.portatil_material,
                      atividade = EXCLUDED.atividade,
                      falta_disciplinar = EXCLUDED.falta_disciplinar,
                      observacoes = EXCLUDED.observacoes
                    """
                ),
                {
                    "aula_id": aula_id,
                    "aluno_id": aluno_id,
                    "atraso": bool(payload.get("atraso")),
                    "faltas": int(payload.get("faltas") or 0),
                    "responsabilidade": payload.get("responsabilidade"),
                    "comportamento": payload.get("comportamento"),
                    "participacao": payload.get("participacao"),
                    "trabalho_autonomo": payload.get("trabalho_autonomo"),
                    "portatil_material": payload.get("portatil_material"),
                    "atividade": payload.get("atividade"),
                    "falta_disciplinar": int(payload.get("falta_disciplinar") or 0),
                    "observacoes": payload.get("observacoes"),
                },
            )

    elif item["op_type"] == "UPDATE_SUMARIO":
        payload = item["payload"]
        db.session.execute(
            text(
                """
                UPDATE calendario_aulas
                SET sumario=:sumario, observacoes=:observacoes
                WHERE id=:aula_id
                """
            ),
            {
                "aula_id": int(payload["aula_id"]),
                "sumario": payload.get("sumario"),
                "observacoes": payload.get("observacoes"),
            },
        )


def sync_outbox(app, limit=200):
    target = _target_from_app(app)
    db_mode = (app.config.get("APP_DB_MODE") or "sqlite").lower()
    if db_mode != "postgres":
        _record_sync_error(
            app,
            RuntimeError("APP_DB_MODE nao esta em postgres."),
            {"phase": "preflight", "target": target},
        )
        return {"ok": False, "error": "APP_DB_MODE nao esta em postgres.", **outbox_status(app.instance_path)}

    try:
        db.session.execute(text("SELECT 1"))
    except Exception as exc:
        db.session.rollback()
        app.logger.exception(
            "Sync outbox sem ligacao remota (host=%s port=%s db=%s mode=%s): %s",
            target["host"],
            target["port"],
            target["db"],
            target["mode"],
            exc,
        )
        if target["mode"] == "pooler":
            app.logger.warning(
                "Dica Supabase pooler: teste direct (5432), valide password/role e parametros de timeout."
            )
        _record_sync_error(app, exc, {"phase": "remote_healthcheck", "target": target})
        return {"ok": False, "error": f"BD remota indisponivel: {exc}", **outbox_status(app.instance_path)}

    applied = 0
    errored = 0
    items = list_outbox(app.instance_path, status="pending", limit=limit)
    turma_lookup = {int(t["id"]): t.get("nome") for t in list_snapshot_turmas(app.instance_path)}
    aula_turma_cache = {}

    for item in items:
        try:
            _apply_outbox_item(item)
            db.session.commit()
            mark_outbox(app.instance_path, item["id"], "sent", None)
            applied += 1
        except IntegrityError as exc:
            db.session.rollback()
            duplicate_table = _extract_pk_table_name(exc)
            if not duplicate_table and item.get("op_type") == "UPSERT_AULAS_ALUNOS":
                duplicate_table = "aulas_alunos"

            if _is_unique_violation(exc) and duplicate_table:
                app.logger.warning(
                    "PK duplicate detectada (%s_pkey); a executar fix sequences + retry | outbox_id=%s | op_type=%s",
                    duplicate_table,
                    item["id"],
                    item.get("op_type"),
                )
                try:
                    fix_sequences_remote(app, schema_name="public")
                    app.logger.info("sequence repaired | table=%s", duplicate_table)
                    _apply_outbox_item(item)
                    db.session.commit()
                    app.logger.info("sequence repaired and retry succeeded | outbox_id=%s", item["id"])
                    mark_outbox(app.instance_path, item["id"], "sent", None)
                    applied += 1
                    continue
                except Exception as retry_exc:
                    db.session.rollback()
                    app.logger.exception(
                        "Retry apos fix sequences falhou | outbox_id=%s: %s",
                        item["id"],
                        retry_exc,
                    )
                    mark_outbox(
                        app.instance_path,
                        item["id"],
                        "error",
                        f"retry_failed_after_sequence_repair: {retry_exc}",
                    )
                    _record_sync_error(
                        app,
                        retry_exc,
                        _build_item_error_context(
                            app,
                            item,
                            turma_lookup,
                            aula_turma_cache,
                            extra={
                                "phase": "retry_after_sequence_repair",
                                "detected_duplicate_table": duplicate_table,
                            },
                        ),
                    )
                    errored += 1
                    continue

            app.logger.exception("Erro de integridade ao sincronizar outbox id=%s: %s", item["id"], exc)
            mark_outbox(app.instance_path, item["id"], "error", str(exc))
            _record_sync_error(
                app,
                exc,
                _build_item_error_context(
                    app,
                    item,
                    turma_lookup,
                    aula_turma_cache,
                    extra={"phase": "apply_integrity_error", "detected_duplicate_table": duplicate_table},
                ),
            )
            errored += 1
        except Exception as exc:
            db.session.rollback()
            app.logger.exception("Erro ao sincronizar outbox id=%s: %s", item["id"], exc)
            mark_outbox(app.instance_path, item["id"], "error", str(exc))
            _record_sync_error(
                app,
                exc,
                _build_item_error_context(app, item, turma_lookup, aula_turma_cache, extra={"phase": "apply_exception"}),
            )
            errored += 1

    return {"ok": True, "applied": applied, "errored": errored, **outbox_status(app.instance_path)}
