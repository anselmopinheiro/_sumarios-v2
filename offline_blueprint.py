from datetime import datetime

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
import sqlalchemy as sa

from models import Aluno, AnoLetivo, CalendarioAula, Modulo, Periodo, Turma, db
from offline_store import (
    enqueue_outbox,
    get_snapshot_aula,
    get_offline_aulas_alunos,
    is_online,
    list_snapshot_aulas,
    list_snapshot_alunos,
    list_snapshot_turmas,
    outbox_status,
    replace_snapshot,
    upsert_offline_aulas_alunos,
    upsert_offline_sumario,
)
from sync import sync_outbox

offline_bp = Blueprint("offline", __name__, url_prefix="/offline")


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


def refresh_snapshot_from_remote():
    app = current_app
    if not is_online(app, lambda: db.session.execute(sa.text("SELECT 1"))):
        return {"ok": False, "error": "Sem ligação à BD remota."}

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
    replace_snapshot(
        app.instance_path,
        "snapshot_turmas",
        [
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
    )
    replace_snapshot(
        app.instance_path,
        "snapshot_alunos",
        [
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
    )
    replace_snapshot(
        app.instance_path,
        "snapshot_periodos",
        [
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
    )
    replace_snapshot(
        app.instance_path,
        "snapshot_modulos",
        [
            {
                "id": m.id,
                "turma_id": m.turma_id,
                "nome": m.nome,
                "total_aulas": m.total_aulas,
                "updated_at": now,
            }
            for m in modulos
        ],
    )
    replace_snapshot(
        app.instance_path,
        "snapshot_calendario_aulas",
        [
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
    )

    return {
        "ok": True,
        "turmas": len(turmas),
        "alunos": len(alunos),
        "aulas": len(aulas),
    }


@offline_bp.route("/")
def dashboard():
    status = outbox_status(current_app.instance_path)
    turmas = list_snapshot_turmas(current_app.instance_path)
    return render_template("offline_dashboard.html", status=status, turmas=turmas)


@offline_bp.route("/snapshot", methods=["POST"])
def snapshot_now():
    result = refresh_snapshot_from_remote()
    if result.get("ok"):
        flash(
            f"Snapshot atualizado: {result['turmas']} turma(s), {result['alunos']} aluno(s), {result['aulas']} aula(s).",
            "success",
        )
    else:
        flash(result.get("error") or "Falha ao atualizar snapshot.", "error")
    return redirect(url_for("offline.dashboard"))


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
    return render_template(
        "offline_presencas.html",
        aula=aula,
        alunos=alunos,
        offline_map=offline_map,
        status=outbox_status(current_app.instance_path),
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
