from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from models import db
from offline_store import list_outbox, mark_outbox, outbox_status


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


def _ensure_safe_table_name(table_name):
    allowed = {"aulas_alunos", "sumario_historico", "calendario_aulas", "turmas", "alunos"}
    if table_name not in allowed:
        raise ValueError(f"Tabela não permitida para sequence repair: {table_name}")
    return table_name


def _repair_sequence_for_table(app, table_name):
    table_name = _ensure_safe_table_name(table_name)
    table_fq = f"public.{table_name}"
    seq_name = db.session.execute(
        text("SELECT pg_get_serial_sequence(:table_fq, 'id')"),
        {"table_fq": table_fq},
    ).scalar()

    if not seq_name:
        seq_name = f"public.{table_name}_id_seq"
        app.logger.warning(
            "sequence ausente; a criar default para tabela=%s usando %s",
            table_name,
            seq_name,
        )
        db.session.execute(text(f"CREATE SEQUENCE IF NOT EXISTS {seq_name}"))
        db.session.execute(
            text(
                f"ALTER TABLE {table_fq} "
                f"ALTER COLUMN id SET DEFAULT nextval('{seq_name}')"
            )
        )
        db.session.execute(
            text(f"ALTER SEQUENCE {seq_name} OWNED BY {table_fq}.id")
        )

    max_id = db.session.execute(text(f"SELECT COALESCE(MAX(id), 1) FROM {table_fq}")).scalar() or 1
    db.session.execute(text("SELECT setval(:seq_name, :max_id, true)"), {"seq_name": seq_name, "max_id": int(max_id)})
    db.session.commit()
    app.logger.info("sequence repaired | table=%s | sequence=%s | max_id=%s", table_name, seq_name, max_id)


def _is_pk_duplicate(exc, constraint_name):
    message = str(exc)
    return (
        "duplicate key value violates unique constraint" in message
        and constraint_name in message
    )


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
                     participacao, trabalho_autonomo, portatil_material, atividade, falta_disciplinar)
                    VALUES
                    (:aula_id, :aluno_id, :atraso, :faltas, :responsabilidade, :comportamento,
                     :participacao, :trabalho_autonomo, :portatil_material, :atividade, :falta_disciplinar)
                    ON CONFLICT (aula_id, aluno_id) DO UPDATE SET
                      atraso = EXCLUDED.atraso,
                      faltas = EXCLUDED.faltas,
                      responsabilidade = EXCLUDED.responsabilidade,
                      comportamento = EXCLUDED.comportamento,
                      participacao = EXCLUDED.participacao,
                      trabalho_autonomo = EXCLUDED.trabalho_autonomo,
                      portatil_material = EXCLUDED.portatil_material,
                      atividade = EXCLUDED.atividade,
                      falta_disciplinar = EXCLUDED.falta_disciplinar
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
        return {"ok": False, "error": "APP_DB_MODE não está em postgres.", **outbox_status(app.instance_path)}

    try:
        db.session.execute(text("SELECT 1"))
    except Exception as exc:
        db.session.rollback()
        app.logger.exception(
            "Sync outbox sem ligação remota (host=%s port=%s db=%s mode=%s): %s",
            target["host"],
            target["port"],
            target["db"],
            target["mode"],
            exc,
        )
        if target["mode"] == "pooler":
            app.logger.warning(
                "Dica Supabase pooler: teste direct (5432), valide password/role e parâmetros de timeout."
            )
        return {"ok": False, "error": f"BD remota indisponível: {exc}", **outbox_status(app.instance_path)}

    applied = 0
    errored = 0
    items = list_outbox(app.instance_path, status="pending", limit=limit)

    for item in items:
        try:
            _apply_outbox_item(item)
            db.session.commit()
            mark_outbox(app.instance_path, item["id"], "sent", None)
            applied += 1
        except IntegrityError as exc:
            db.session.rollback()
            if item.get("op_type") == "UPSERT_AULAS_ALUNOS" and _is_pk_duplicate(exc, "aulas_alunos_pkey"):
                app.logger.warning(
                    "PK duplicate em aulas_alunos; a tentar sequence repair + retry | outbox_id=%s",
                    item["id"],
                )
                try:
                    _repair_sequence_for_table(app, "aulas_alunos")
                    _apply_outbox_item(item)
                    db.session.commit()
                    app.logger.info("sequence repaired and retry succeeded | outbox_id=%s", item["id"])
                    mark_outbox(app.instance_path, item["id"], "sent", None)
                    applied += 1
                    continue
                except Exception as retry_exc:
                    db.session.rollback()
                    app.logger.exception(
                        "Retry após sequence repair falhou | outbox_id=%s: %s",
                        item["id"],
                        retry_exc,
                    )
            app.logger.exception("Erro de integridade ao sincronizar outbox id=%s: %s", item["id"], exc)
            mark_outbox(app.instance_path, item["id"], "error", str(exc))
            errored += 1
        except Exception as exc:
            db.session.rollback()
            app.logger.exception("Erro ao sincronizar outbox id=%s: %s", item["id"], exc)
            mark_outbox(app.instance_path, item["id"], "error", str(exc))
            errored += 1

    return {"ok": True, "applied": applied, "errored": errored, **outbox_status(app.instance_path)}
