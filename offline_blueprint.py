import json
from datetime import datetime, timezone
from threading import Lock
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from models import Aluno, AnoLetivo, CalendarioAula, Modulo, Periodo, Turma, db
from offline_store import (
    clear_offline_errors,
    count_offline_errors,
    delete_offline_error,
    enqueue_outbox,
    finish_snapshot_run,
    get_last_offline_error,
    get_offline_aulas_alunos,
    get_offline_sumario,
    get_setting,
    get_snapshot_aula,
    get_snapshot_status,
    get_state_datetime,
    is_online,
    list_offline_errors,
    list_outbox,
    list_snapshot_aulas,
    list_snapshot_alunos,
    list_snapshot_runs,
    list_snapshot_turmas,
    outbox_status,
    record_offline_error,
    set_setting,
    set_state_datetime,
    start_snapshot_run,
    upsert_offline_aulas_alunos,
    upsert_offline_sumario,
    upsert_snapshot_batch,
)
from sync import sync_outbox


offline_bp = Blueprint("offline", __name__, url_prefix="/offline")
SNAPSHOT_RUN_LOCK = Lock()
LISBON_TZ = ZoneInfo("Europe/Lisbon")
STATE_LAST_SYNC_OK_AT = "last_sync_ok_at"
STATE_LAST_SNAPSHOT_OK_AT = "last_snapshot_ok_at"


def _get_online_state():
    cached_fn = current_app.extensions.get("is_remote_online")
    if callable(cached_fn):
        return bool(cached_fn())
    return is_online(current_app, lambda: db.session.execute(sa.text("SELECT 1")))


def _remote_db_meta():
    uri = current_app.config.get("SQLALCHEMY_DATABASE_URI") or ""
    mode = current_app.config.get("SUPABASE_DB_MODE", "direct")
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


def _parse_utc_datetime(raw):
    if not raw:
        return None
    if isinstance(raw, datetime):
        dt = raw
    else:
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


def _fmt_dt_pt(raw, fallback="-"):
    dt = _parse_utc_datetime(raw)
    if not dt:
        return fallback
    return dt.astimezone(LISBON_TZ).strftime("%d/%m/%Y %H:%M")


def _safe_record_offline_error(operation, exc, context=None):
    try:
        record_offline_error(current_app.instance_path, operation, exc, context=context)
    except Exception:
        current_app.logger.exception("Falha ao registar erro offline (operation=%s).", operation)


def _mark_success_state(key):
    try:
        set_state_datetime(current_app.instance_path, key, datetime.now(timezone.utc))
    except Exception:
        current_app.logger.exception("Falha ao atualizar estado offline '%s'.", key)


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_turma_info_from_context(context):
    if not isinstance(context, dict):
        return None, None
    turma_id = _safe_int(context.get("turma_id"))
    turma_nome = context.get("turma_nome")
    if turma_nome is not None:
        turma_nome = str(turma_nome)
    return turma_id, turma_nome


def _resolve_turma_from_payload_or_aula(payload, turma_ids_set, aula_turma_cache, instance_path):
    turma_id = _safe_int(payload.get("turma_id"))
    if turma_id is None:
        aula_id = _safe_int(payload.get("aula_id"))
        if aula_id is not None:
            if aula_id not in aula_turma_cache:
                aula = get_snapshot_aula(instance_path, aula_id)
                aula_turma_cache[aula_id] = _safe_int((aula or {}).get("turma_id"))
            turma_id = aula_turma_cache.get(aula_id)
    return turma_id if turma_id in turma_ids_set else None


def _build_turma_pending_counts(instance_path, turmas):
    stats = {int(t["id"]): 0 for t in turmas}
    if not stats:
        return stats

    turma_ids_set = set(stats.keys())
    aula_turma_cache = {}
    for item in list_outbox(instance_path, status="pending", limit=5000):
        payload = item.get("payload") or {}
        turma_id = _resolve_turma_from_payload_or_aula(payload, turma_ids_set, aula_turma_cache, instance_path)
        if turma_id is not None:
            stats[turma_id] += 1
    return stats


def _build_turma_error_counts(errors):
    counts = {}
    for item in errors:
        turma_id, _ = _extract_turma_info_from_context(item.get("context_json"))
        if turma_id is None:
            continue
        counts[turma_id] = int(counts.get(turma_id, 0)) + 1
    return counts


def _normalized_limit(raw_limit, default=50, max_limit=500):
    try:
        limit = int(raw_limit if raw_limit is not None else default)
    except (TypeError, ValueError):
        limit = default
    return max(1, min(max_limit, limit))


def _load_filtered_errors(instance_path, turma_id=None, limit=50):
    all_errors = list_offline_errors(instance_path, limit=None)
    filtered = []
    for item in all_errors:
        ctx_turma_id, _ = _extract_turma_info_from_context(item.get("context_json"))
        if turma_id is not None and ctx_turma_id != turma_id:
            continue
        filtered.append(item)
    return filtered[: int(limit)]


def _serialize_error_for_ui(item):
    context = item.get("context_json")
    if context is None:
        context_pretty = ""
    elif isinstance(context, (dict, list)):
        context_pretty = json.dumps(context, ensure_ascii=False, indent=2, sort_keys=True)
    else:
        context_pretty = str(context)

    created_at = item.get("created_at")
    turma_id, turma_nome = _extract_turma_info_from_context(context)
    return {
        "id": item.get("id"),
        "created_at": created_at,
        "created_at_display": _fmt_dt_pt(created_at),
        "operation": item.get("operation") or "other",
        "summary": item.get("summary") or "Erro sem resumo.",
        "details": item.get("details") or "",
        "context_pretty": context_pretty,
        "context_json": context,
        "turma_id": turma_id,
        "turma_nome": turma_nome or "-",
    }


def _error_counts_payload(instance_path):
    error_count = count_offline_errors(instance_path)
    last_error = get_last_offline_error(instance_path)
    last_error_at = last_error.get("created_at") if last_error else None
    return {
        "error_count": error_count,
        "last_error_at": last_error_at,
        "last_error_at_display": _fmt_dt_pt(last_error_at, fallback="Sem erros"),
    }


def _serialize_errors_payload(instance_path, turma_id=None, limit=50):
    limit = _normalized_limit(limit)
    items = [_serialize_error_for_ui(item) for item in _load_filtered_errors(instance_path, turma_id=turma_id, limit=limit)]
    errors_meta = _error_counts_payload(instance_path)
    all_errors = list_offline_errors(instance_path, limit=None)
    turma_error_counts = _build_turma_error_counts(all_errors)
    return {
        "ok": True,
        "items": items,
        "filter_turma_id": turma_id,
        "limit": limit,
        "error_count": errors_meta["error_count"],
        "last_error_at": errors_meta["last_error_at"],
        "last_error_at_display": errors_meta["last_error_at_display"],
        "turma_error_counts": {str(k): int(v) for k, v in turma_error_counts.items()},
    }


def _normalize_payload(item):
    def _int(name, default=0, mn=None, mx=None):
        try:
            value = int(item.get(name, default))
        except (TypeError, ValueError):
            value = default
        if mn is not None:
            value = max(mn, value)
        if mx is not None:
            value = min(mx, value)
        return value

    observacoes_raw = item.get("observacoes")
    observacoes = None
    if observacoes_raw is not None:
        observacoes = str(observacoes_raw).replace("\r\n", "\n").replace("\r", "\n").strip()
        if len(observacoes) > 500:
            observacoes = observacoes[:500]
        observacoes = observacoes or None

    return {
        "atraso": bool(item.get("atraso")),
        "faltas": _int("faltas", 0, 0, 6),
        "responsabilidade": _int("responsabilidade", 3, 1, 5),
        "comportamento": _int("comportamento", 3, 1, 5),
        "participacao": _int("participacao", 3, 1, 5),
        "trabalho_autonomo": _int("trabalho_autonomo", 3, 1, 5),
        "portatil_material": _int("portatil_material", 3, 1, 5),
        "atividade": _int("atividade", 3, 1, 5),
        "falta_disciplinar": _int("falta_disciplinar", 0, 0, 2),
        "observacoes": observacoes,
        "updated_at": datetime.utcnow().isoformat(timespec="seconds"),
    }


def snapshot_remote_to_local(mode="manual"):
    app = current_app
    target = _remote_db_meta()

    if not SNAPSHOT_RUN_LOCK.acquire(blocking=False):
        app.logger.info("Snapshot ja em execucao; pedido ignorado.")
        return {"ok": False, "error": "Snapshot ja em execucao."}

    run_id, started_at = start_snapshot_run(app.instance_path, mode=mode)

    if not _get_online_state():
        msg = "Sem ligacao a BD remota."
        app.logger.warning(
            "Snapshot offline abortado: sem ligacao remota (host=%s port=%s db=%s mode=%s)",
            target["host"],
            target["port"],
            target["db"],
            target["mode"],
        )
        finish_snapshot_run(app.instance_path, run_id, ok=False, error=msg)
        _safe_record_offline_error(
            "snapshot",
            RuntimeError(msg),
            context={"mode": mode, "phase": "remote_healthcheck", "target": target},
        )
        return {"ok": False, "error": msg, "run_id": run_id, "started_at": started_at}

    try:
        ano_ativo = AnoLetivo.query.filter_by(ativo=True).first()
        ano_id = ano_ativo.id if ano_ativo else None

        turmas_q = Turma.query
        if ano_id:
            turmas_q = turmas_q.filter(Turma.ano_letivo_id == ano_id)
        turmas = turmas_q.order_by(Turma.nome).all()
        turma_ids = [t.id for t in turmas]

        alunos = []
        aulas = []
        periodos = []
        modulos = []
        if turma_ids:
            alunos = Aluno.query.filter(Aluno.turma_id.in_(turma_ids)).all()
            aulas = CalendarioAula.query.filter(CalendarioAula.turma_id.in_(turma_ids)).all()
            periodos = Periodo.query.filter(Periodo.turma_id.in_(turma_ids)).all()
            modulos = Modulo.query.filter(Modulo.turma_id.in_(turma_ids)).all()

        now = datetime.utcnow().isoformat(timespec="seconds")
        payload = {
            "snapshot_turmas": [
                {
                    "id": t.id,
                    "nome": t.nome,
                    "ano_letivo_id": t.ano_letivo_id,
                    "tipo": t.tipo,
                    "letiva": 1 if bool(t.letiva) else 0,
                    "periodo_tipo": t.periodo_tipo,
                    "updated_at": now,
                }
                for t in turmas
            ],
            "snapshot_alunos": [
                {
                    "id": a.id,
                    "turma_id": a.turma_id,
                    "numero": a.numero,
                    "nome": a.nome,
                    "nome_curto": a.nome_curto,
                    "nee": a.nee,
                    "updated_at": now,
                }
                for a in alunos
            ],
            "snapshot_periodos": [
                {
                    "id": p.id,
                    "turma_id": p.turma_id,
                    "nome": p.nome,
                    "tipo": p.tipo,
                    "data_inicio": p.data_inicio.isoformat() if p.data_inicio else None,
                    "data_fim": p.data_fim.isoformat() if p.data_fim else None,
                    "updated_at": now,
                }
                for p in periodos
            ],
            "snapshot_modulos": [
                {
                    "id": m.id,
                    "turma_id": m.turma_id,
                    "nome": m.nome,
                    "total_aulas": m.total_aulas,
                    "updated_at": now,
                }
                for m in modulos
            ],
            "snapshot_calendario_aulas": [
                {
                    "id": a.id,
                    "turma_id": a.turma_id,
                    "periodo_id": a.periodo_id,
                    "data": a.data.isoformat() if a.data else None,
                    "weekday": a.weekday,
                    "modulo_id": a.modulo_id,
                    "numero_modulo": a.numero_modulo,
                    "total_geral": a.total_geral,
                    "tipo": a.tipo,
                    "apagado": 1 if bool(a.apagado) else 0,
                    "tempos_sem_aula": a.tempos_sem_aula,
                    "atividade": 1 if bool(a.atividade) else 0,
                    "atividade_nome": a.atividade_nome,
                    "previsao": a.previsao,
                    "updated_at": now,
                }
                for a in aulas
            ],
        }

        counts = upsert_snapshot_batch(app.instance_path, payload)
        finish_snapshot_run(app.instance_path, run_id, ok=True, counts=counts)
        _mark_success_state(STATE_LAST_SNAPSHOT_OK_AT)

        app.logger.info(
            "Snapshot offline atualizado (host=%s port=%s db=%s mode=%s): turmas=%s alunos=%s aulas=%s",
            target["host"],
            target["port"],
            target["db"],
            target["mode"],
            counts.get("snapshot_turmas", 0),
            counts.get("snapshot_alunos", 0),
            counts.get("snapshot_calendario_aulas", 0),
        )

        return {
            "ok": True,
            "run_id": run_id,
            "started_at": started_at,
            "turmas": counts.get("snapshot_turmas", 0),
            "alunos": counts.get("snapshot_alunos", 0),
            "aulas": counts.get("snapshot_calendario_aulas", 0),
            "periodos": counts.get("snapshot_periodos", 0),
            "modulos": counts.get("snapshot_modulos", 0),
        }
    except Exception as exc:
        app.logger.exception(
            "Falha ao atualizar snapshot offline (host=%s port=%s db=%s mode=%s): %s",
            target["host"],
            target["port"],
            target["db"],
            target["mode"],
            exc,
        )
        finish_snapshot_run(app.instance_path, run_id, ok=False, error=str(exc))
        _safe_record_offline_error(
            "snapshot",
            exc,
            context={"mode": mode, "phase": "snapshot_remote_to_local", "target": target},
        )
        if target["mode"] == "pooler":
            app.logger.warning(
                "Dica Supabase pooler: confirme porta/URL (pooler=6543, direct=5432), role e password."
            )
        return {"ok": False, "error": "Sem ligacao a BD remota.", "run_id": run_id, "started_at": started_at}
    finally:
        SNAPSHOT_RUN_LOCK.release()


def refresh_snapshot_from_remote():
    return snapshot_remote_to_local(mode="manual")


@offline_bp.route("/")
def dashboard():
    instance_path = current_app.instance_path

    online = _get_online_state()
    status = outbox_status(instance_path)
    snapshot = get_snapshot_status(instance_path)
    snapshot_last_run = (snapshot or {}).get("last_run") or {}
    snapshot_last_run_at = snapshot_last_run.get("finished_at") or snapshot_last_run.get("started_at")
    snapshot_last_run_ok = bool(snapshot_last_run and int(snapshot_last_run.get("ok") or 0) == 1)

    all_errors = list_offline_errors(instance_path, limit=None)
    turma_error_counts = _build_turma_error_counts(all_errors)

    turmas_raw = list_snapshot_turmas(instance_path)
    turma_pending_counts = _build_turma_pending_counts(instance_path, turmas_raw)

    turmas = []
    for turma in turmas_raw:
        turma_id = int(turma["id"])
        pending = int(turma_pending_counts.get(turma_id, 0))
        error_ops = int(turma_error_counts.get(turma_id, 0))

        if error_ops > 0:
            status_label = "Erro"
            status_badge = "text-bg-danger"
        elif pending > 0:
            status_label = "Pendentes"
            status_badge = "text-bg-warning"
        else:
            status_label = "OK"
            status_badge = "text-bg-success"

        row = dict(turma)
        row.update(
            {
                "updated_at_display": _fmt_dt_pt(turma.get("updated_at")),
                "pending": pending,
                "error_ops": error_ops,
                "status_label": status_label,
                "status_badge": status_badge,
            }
        )
        turmas.append(row)

    errors = [_serialize_error_for_ui(item) for item in _load_filtered_errors(instance_path, turma_id=None, limit=50)]
    errors_meta = _error_counts_payload(instance_path)

    last_sync_ok_at = get_state_datetime(instance_path, STATE_LAST_SYNC_OK_AT)
    last_snapshot_ok_at = get_state_datetime(instance_path, STATE_LAST_SNAPSHOT_OK_AT)

    return render_template(
        "offline_dashboard.html",
        online=online,
        status=status,
        snapshot=snapshot,
        snapshot_last_run_at_display=_fmt_dt_pt(snapshot_last_run_at),
        snapshot_last_run_status=("OK" if snapshot_last_run_ok else ("ERRO" if snapshot_last_run else "-")),
        turmas=turmas,
        errors=errors,
        error_count=errors_meta["error_count"],
        last_error_at=errors_meta["last_error_at"],
        last_error_at_display=errors_meta["last_error_at_display"],
        last_sync_ok_at=last_sync_ok_at,
        last_sync_ok_at_display=_fmt_dt_pt(last_sync_ok_at),
        last_snapshot_ok_at=last_snapshot_ok_at,
        last_snapshot_ok_at_display=_fmt_dt_pt(last_snapshot_ok_at),
    )


@offline_bp.route("/errors", methods=["GET"])
def list_errors():
    turma_id = request.args.get("turma_id", type=int)
    limit = _normalized_limit(request.args.get("limit"), default=50, max_limit=500)
    payload = _serialize_errors_payload(current_app.instance_path, turma_id=turma_id, limit=limit)
    return jsonify(payload)


@offline_bp.route("/status")
def status_page():
    errors_meta = _error_counts_payload(current_app.instance_path)
    last_sync_ok = get_state_datetime(current_app.instance_path, STATE_LAST_SYNC_OK_AT)
    last_snapshot_ok = get_state_datetime(current_app.instance_path, STATE_LAST_SNAPSHOT_OK_AT)
    payload = {
        "ok": True,
        "online": _get_online_state(),
        "snapshot": get_snapshot_status(current_app.instance_path),
        "outbox": outbox_status(current_app.instance_path),
        "errors": errors_meta,
        "state": {
            "last_sync_ok_at": last_sync_ok.isoformat() if last_sync_ok else None,
            "last_snapshot_ok_at": last_snapshot_ok.isoformat() if last_snapshot_ok else None,
        },
        "settings": {
            "enabled": get_setting(current_app.instance_path, "snapshot_enabled", "1"),
            "interval_seconds": get_setting(current_app.instance_path, "snapshot_interval_seconds", "60"),
        },
    }
    if request.accept_mimetypes.best == "application/json" or request.args.get("format") == "json":
        return jsonify(payload)
    return render_template("offline_status.html", payload=payload)


@offline_bp.route("/history")
def history_page():
    runs = list_snapshot_runs(current_app.instance_path, limit=50)
    return render_template("offline_history.html", runs=runs)


@offline_bp.route("/settings", methods=["GET", "POST"])
def settings_page():
    if request.method == "POST":
        enabled = "1" if request.form.get("snapshot_enabled") else "0"
        interval = request.form.get("snapshot_interval_seconds") or "60"
        try:
            interval = str(max(15, int(interval)))
        except Exception:
            interval = "60"

        set_setting(current_app.instance_path, "snapshot_enabled", enabled)
        set_setting(current_app.instance_path, "snapshot_interval_seconds", interval)
        flash("Definicoes offline guardadas.", "success")
        return redirect(url_for("offline.settings_page"))

    settings = {
        "snapshot_enabled": get_setting(current_app.instance_path, "snapshot_enabled", "1"),
        "snapshot_interval_seconds": get_setting(current_app.instance_path, "snapshot_interval_seconds", "60"),
    }
    return render_template("offline_settings.html", settings=settings)


@offline_bp.route("/snapshot", methods=["POST", "GET"])
def snapshot_now():
    result = snapshot_remote_to_local(mode="manual")
    if request.accept_mimetypes.best == "application/json" or request.args.get("format") == "json":
        code = 200 if result.get("ok") else 503
        return jsonify(result), code

    if result.get("ok"):
        flash(
            (
                "Snapshot atualizado: "
                f"{result['turmas']} turma(s), {result['alunos']} aluno(s), {result['aulas']} aula(s), "
                f"{result.get('periodos', 0)} periodo(s), {result.get('modulos', 0)} modulo(s)."
            ),
            "success",
        )
    else:
        flash(result.get("error") or "Falha ao atualizar snapshot.", "error")

    next_page = request.form.get("next") or request.args.get("next")
    if next_page == "dashboard":
        return redirect(url_for("offline.dashboard"))
    return redirect(url_for("offline.dashboard"))


@offline_bp.route("/health/db", methods=["GET"])
def healthcheck_db():
    target = _remote_db_meta()
    if (current_app.config.get("APP_DB_MODE") or "sqlite").lower() != "postgres":
        return jsonify({"ok": False, "error": "APP_DB_MODE nao esta em postgres.", **target}), 400

    try:
        db.session.execute(sa.text("SELECT 1"))
        return jsonify({"ok": True, **target})
    except Exception as exc:
        current_app.logger.exception(
            "Healthcheck DB falhou (host=%s port=%s db=%s mode=%s): %s",
            target["host"],
            target["port"],
            target["db"],
            target["mode"],
            exc,
        )
        return jsonify({"ok": False, "error": str(exc), **target}), 503


@offline_bp.route("/turmas")
def turmas():
    return render_template("offline_turmas.html", turmas=list_snapshot_turmas(current_app.instance_path))


@offline_bp.route("/turma/<int:turma_id>/aulas")
def turma_aulas(turma_id):
    aulas = list_snapshot_aulas(current_app.instance_path, turma_id)
    turma = next((t for t in list_snapshot_turmas(current_app.instance_path) if int(t["id"]) == int(turma_id)), None)
    return render_template("offline_aulas.html", turma=turma, aulas=aulas)


@offline_bp.route("/aula/<int:aula_id>/presencas", methods=["GET", "POST"])
def aula_presencas(aula_id):
    aula = get_snapshot_aula(current_app.instance_path, aula_id)
    if not aula:
        flash("Aula nao encontrada no snapshot offline.", "error")
        return redirect(url_for("offline.turmas"))

    alunos = list_snapshot_alunos(current_app.instance_path, aula["turma_id"])

    if request.method == "POST":
        payload_items = []
        for aluno in alunos:
            aluno_id = int(aluno["id"])
            payload = _normalize_payload(
                {
                    "atraso": bool(request.form.get(f"atraso_{aluno_id}")),
                    "faltas": request.form.get(f"faltas_{aluno_id}"),
                    "responsabilidade": request.form.get(f"responsabilidade_{aluno_id}"),
                    "comportamento": request.form.get(f"comportamento_{aluno_id}"),
                    "participacao": request.form.get(f"participacao_{aluno_id}"),
                    "trabalho_autonomo": request.form.get(f"trabalho_autonomo_{aluno_id}"),
                    "portatil_material": request.form.get(f"portatil_material_{aluno_id}"),
                    "atividade": request.form.get(f"atividade_{aluno_id}"),
                    "falta_disciplinar": request.form.get(f"falta_disciplinar_{aluno_id}"),
                    "observacoes": request.form.get(f"observacoes_{aluno_id}"),
                }
            )
            payload_items.append({"aluno_id": aluno_id, "payload": payload})

        upsert_offline_aulas_alunos(current_app.instance_path, aula_id, payload_items)
        enqueue_outbox(
            current_app.instance_path,
            "UPSERT_AULAS_ALUNOS",
            {
                "aula_id": int(aula_id),
                "items": payload_items,
                "updated_at": datetime.utcnow().isoformat(timespec="seconds"),
            },
        )
        flash("Presencas/avaliacoes guardadas localmente.", "success")
        return redirect(url_for("offline.aula_presencas", aula_id=aula_id))

    offline_map = get_offline_aulas_alunos(current_app.instance_path, aula_id)
    sumario = get_offline_sumario(current_app.instance_path, aula_id) or {}
    return render_template(
        "offline_presencas.html",
        aula=aula,
        alunos=alunos,
        offline_map=offline_map,
        status=outbox_status(current_app.instance_path),
        sumario=sumario,
    )


@offline_bp.route("/aula/<int:aula_id>/sumario", methods=["POST"])
def aula_sumario(aula_id):
    sumario = request.form.get("sumario")
    observacoes = request.form.get("observacoes")
    upsert_offline_sumario(current_app.instance_path, aula_id, sumario, observacoes)
    enqueue_outbox(
        current_app.instance_path,
        "UPDATE_SUMARIO",
        {
            "aula_id": int(aula_id),
            "sumario": sumario,
            "observacoes": observacoes,
            "updated_at": datetime.utcnow().isoformat(timespec="seconds"),
        },
    )
    flash("Sumario/observacoes guardados localmente.", "success")
    return redirect(url_for("offline.aula_presencas", aula_id=aula_id))


@offline_bp.route("/sync", methods=["GET", "POST"])
def sync_page():
    if request.method == "POST":
        result = sync_outbox(current_app, limit=500)

        if result.get("ok") and int(result.get("errored", 0)) == 0:
            _mark_success_state(STATE_LAST_SYNC_OK_AT)
            flash(
                f"Sincronizacao concluida. Aplicados: {result.get('applied', 0)} | erros: {result.get('errored', 0)}",
                "success",
            )
        elif result.get("ok"):
            flash(
                f"Sincronizacao com erros. Aplicados: {result.get('applied', 0)} | erros: {result.get('errored', 0)}",
                "warning",
            )
        else:
            _safe_record_offline_error(
                "sync",
                RuntimeError(result.get("error") or "Nao foi possivel sincronizar agora."),
                context={
                    "phase": "sync_page",
                    "applied": int(result.get("applied", 0)),
                    "errored": int(result.get("errored", 0)),
                    "pending": int(result.get("pending", 0)),
                    "errors": int(result.get("errors", 0)),
                },
            )
            flash(result.get("error") or "Nao foi possivel sincronizar agora.", "error")

        next_page = request.form.get("next") or request.args.get("next")
        if next_page == "dashboard":
            return redirect(url_for("offline.dashboard"))
        return redirect(url_for("offline.sync_page"))

    return render_template("offline_sync.html", status=outbox_status(current_app.instance_path))


@offline_bp.route("/errors/<int:error_id>", methods=["DELETE"])
def delete_error(error_id):
    ok = delete_offline_error(current_app.instance_path, error_id)
    if not ok:
        payload = {"ok": False, **_error_counts_payload(current_app.instance_path)}
        payload["message"] = "Erro nao encontrado."
        payload["turma_error_counts"] = {
            str(k): int(v)
            for k, v in _build_turma_error_counts(list_offline_errors(current_app.instance_path, limit=None)).items()
        }
        return jsonify(payload), 404

    payload = {"ok": True, **_error_counts_payload(current_app.instance_path)}
    payload["turma_error_counts"] = {
        str(k): int(v)
        for k, v in _build_turma_error_counts(list_offline_errors(current_app.instance_path, limit=None)).items()
    }
    return jsonify(payload)


@offline_bp.route("/errors/clear", methods=["POST"])
def clear_errors():
    deleted = clear_offline_errors(current_app.instance_path)
    payload = {"ok": True, "deleted": int(deleted), **_error_counts_payload(current_app.instance_path)}
    payload["turma_error_counts"] = {}
    return jsonify(payload)
