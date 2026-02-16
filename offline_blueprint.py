from datetime import datetime

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from models import Aluno, AnoLetivo, CalendarioAula, Modulo, Periodo, Turma, db
from offline_store import (
    enqueue_outbox,
    finish_snapshot_run,
    get_offline_aulas_alunos,
    get_offline_sumario,
    get_setting,
    get_snapshot_aula,
    get_snapshot_status,
    is_online,
    list_snapshot_aulas,
    list_snapshot_alunos,
    list_snapshot_runs,
    list_snapshot_turmas,
    outbox_status,
    set_setting,
    start_snapshot_run,
    upsert_offline_aulas_alunos,
    upsert_offline_sumario,
    upsert_snapshot_batch,
)
from sync import sync_outbox

offline_bp = Blueprint("offline", __name__, url_prefix="/offline")


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
        "updated_at": datetime.utcnow().isoformat(timespec="seconds"),
    }


def snapshot_remote_to_local(mode="manual"):
    app = current_app
    target = _remote_db_meta()
    run_id, started_at = start_snapshot_run(app.instance_path, mode=mode)

    if not _get_online_state():
        app.logger.warning(
            "Snapshot offline abortado: sem ligação remota (host=%s port=%s db=%s mode=%s)",
            target["host"],
            target["port"],
            target["db"],
            target["mode"],
        )
        finish_snapshot_run(app.instance_path, run_id, ok=False, error="Sem ligação à BD remota.")
        return {"ok": False, "error": "Sem ligação à BD remota.", "run_id": run_id, "started_at": started_at}

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
        if target["mode"] == "pooler":
            app.logger.warning(
                "Dica Supabase pooler: confirme porta/URL (pooler=6543, direct=5432), role e password."
            )
        return {"ok": False, "error": "Sem ligação à BD remota.", "run_id": run_id, "started_at": started_at}


def refresh_snapshot_from_remote():
    return snapshot_remote_to_local(mode="manual")


@offline_bp.route("/")
def dashboard():
    status = outbox_status(current_app.instance_path)
    turmas = list_snapshot_turmas(current_app.instance_path)
    snapshot = get_snapshot_status(current_app.instance_path)
    return render_template("offline_dashboard.html", status=status, turmas=turmas, snapshot=snapshot)


@offline_bp.route("/status")
def status_page():
    payload = {
        "ok": True,
        "online": _get_online_state(),
        "snapshot": get_snapshot_status(current_app.instance_path),
        "outbox": outbox_status(current_app.instance_path),
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
        flash("Definições offline guardadas.", "success")
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
                f"{result.get('periodos', 0)} período(s), {result.get('modulos', 0)} módulo(s)."
            ),
            "success",
        )
    else:
        flash(result.get("error") or "Falha ao atualizar snapshot.", "error")
    return redirect(url_for("offline.dashboard"))


@offline_bp.route("/health/db", methods=["GET"])
def healthcheck_db():
    target = _remote_db_meta()
    if (current_app.config.get("APP_DB_MODE") or "sqlite").lower() != "postgres":
        return jsonify({"ok": False, "error": "APP_DB_MODE não está em postgres.", **target}), 400

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
        flash("Aula não encontrada no snapshot offline.", "error")
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
        flash("Presenças/avaliações guardadas localmente.", "success")
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
    flash("Sumário/observações guardados localmente.", "success")
    return redirect(url_for("offline.aula_presencas", aula_id=aula_id))


@offline_bp.route("/sync", methods=["GET", "POST"])
def sync_page():
    if request.method == "POST":
        result = sync_outbox(current_app, limit=500)
        if result.get("ok"):
            flash(
                f"Sincronização concluída. Aplicados: {result.get('applied', 0)} | erros: {result.get('errored', 0)}",
                "success",
            )
        else:
            flash(result.get("error") or "Não foi possível sincronizar agora.", "error")
        return redirect(url_for("offline.sync_page"))

    return render_template("offline_sync.html", status=outbox_status(current_app.instance_path))
