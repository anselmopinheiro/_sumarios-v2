from __future__ import annotations

from datetime import date, datetime

from flask import Blueprint, Response, jsonify, render_template, request

from ev2_export_service import export_map_to_csv, export_map_to_xml
from ev2_map_builders import (
    build_annual_map,
    build_final_summary_map,
    build_monthly_map,
    build_period_map,
    build_semester_map,
    build_weekly_map,
)


ev2_bp = Blueprint(
    "ev2",
    __name__,
    url_prefix="/ev2",
    template_folder="app/templates",
    static_folder="app/static",
)


def _parse_date_form(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _as_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    txt = str(value).strip().lower()
    if txt in {"1", "true", "yes", "on", "sim"}:
        return True
    if txt in {"0", "false", "no", "off", "nao", "não", ""}:
        return False
    return default


def _ev2_build_map_from_request(map_type: str):
    turma_id = request.args.get("turma_id", type=int)
    disciplina_id = request.args.get("disciplina_id", type=int)
    aluno_id = request.args.get("aluno_id", type=int)
    include_raw = _as_bool(request.args.get("include_raw"), default=False)

    if not turma_id or not disciplina_id:
        return None, jsonify({"error": "Missing required params: turma_id, disciplina_id"}), 400

    try:
        if map_type == "weekly":
            ref = _parse_date_form(request.args.get("reference_date")) or date.today()
            map_data = build_weekly_map(
                turma_id=turma_id,
                disciplina_id=disciplina_id,
                reference_date=ref,
                include_raw=include_raw,
            )
        elif map_type == "monthly":
            today = date.today()
            year = request.args.get("year", type=int) or today.year
            month = request.args.get("month", type=int) or today.month
            map_data = build_monthly_map(
                turma_id=turma_id,
                disciplina_id=disciplina_id,
                year=year,
                month=month,
                include_raw=include_raw,
            )
        elif map_type == "period":
            periodo_id = request.args.get("periodo_id", type=int)
            if not periodo_id:
                return None, jsonify({"error": "Missing required param: periodo_id"}), 400
            map_data = build_period_map(
                turma_id=turma_id,
                disciplina_id=disciplina_id,
                periodo_id=periodo_id,
                include_raw=include_raw,
            )
        elif map_type == "semester":
            ano_letivo_id = request.args.get("ano_letivo_id", type=int)
            semestre = request.args.get("semestre", type=int)
            if not ano_letivo_id or semestre not in (1, 2):
                return None, jsonify({"error": "Params required: ano_letivo_id and semestre in {1,2}"}), 400
            map_data = build_semester_map(
                turma_id=turma_id,
                disciplina_id=disciplina_id,
                ano_letivo_id=ano_letivo_id,
                semestre=semestre,
                include_raw=include_raw,
            )
        elif map_type == "annual":
            ano_letivo_id = request.args.get("ano_letivo_id", type=int)
            if not ano_letivo_id:
                return None, jsonify({"error": "Missing required param: ano_letivo_id"}), 400
            map_data = build_annual_map(
                turma_id=turma_id,
                disciplina_id=disciplina_id,
                ano_letivo_id=ano_letivo_id,
                include_raw=include_raw,
            )
        elif map_type == "final":
            data_inicio = _parse_date_form(request.args.get("data_inicio"))
            data_fim = _parse_date_form(request.args.get("data_fim"))
            if not data_inicio or not data_fim:
                return None, jsonify({"error": "Params required: data_inicio, data_fim (YYYY-MM-DD)"}), 400
            map_data = build_final_summary_map(
                turma_id=turma_id,
                disciplina_id=disciplina_id,
                data_inicio=data_inicio,
                data_fim=data_fim,
                include_raw=include_raw,
            )
        else:
            return None, jsonify({"error": f"Unsupported map_type: {map_type}"}), 400

        if aluno_id:
            rows = [r for r in map_data.get("rows", []) if r.get("aluno_id") == aluno_id]
            map_data = {**map_data, "rows": rows}
            totals = dict(map_data.get("totals") or {})
            totals["alunos"] = len(rows)
            totals["eventos_total"] = sum((r.get("eventos") or 0) for r in rows)
            map_data["totals"] = totals

        return map_data, None, None
    except ValueError as exc:
        return None, jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return None, jsonify({"error": "Failed to build EV2 map", "details": str(exc)}), 500


@ev2_bp.get("/maps/<string:map_type>")
def ev2_map_endpoint(map_type: str):
    map_data, err_resp, err_code = _ev2_build_map_from_request(map_type)
    if err_resp is not None:
        return err_resp, err_code
    return jsonify(map_data)


@ev2_bp.get("/maps/<string:map_type>/export/<string:fmt>")
def ev2_map_export_endpoint(map_type: str, fmt: str):
    map_data, err_resp, err_code = _ev2_build_map_from_request(map_type)
    if err_resp is not None:
        return err_resp, err_code

    fmt = (fmt or "").lower()
    if fmt not in {"csv", "xml"}:
        return jsonify({"error": "Unsupported export format. Use csv or xml."}), 400

    include_debug = _as_bool(request.args.get("include_debug"), default=False)

    if fmt == "csv":
        payload = export_map_to_csv(map_data, include_debug=include_debug)
        mimetype = "text/csv; charset=utf-8"
    else:
        payload = export_map_to_xml(map_data, include_debug=include_debug)
        mimetype = "application/xml; charset=utf-8"

    turma_id = request.args.get("turma_id", type=int)
    disciplina_id = request.args.get("disciplina_id", type=int)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"ev2_{map_type}_turma{turma_id}_disc{disciplina_id}_{stamp}.{fmt}"

    return Response(
        payload,
        mimetype=mimetype,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@ev2_bp.get("/events")
def ev2_events_list():
    return jsonify({"status": "ok", "route": "events_list"})


@ev2_bp.post("/events")
def ev2_events_create():
    return jsonify({"status": "ok", "route": "events_create"})


@ev2_bp.get("/events/<int:event_id>")
def ev2_event_detail(event_id: int):
    return jsonify({"status": "ok", "route": "event_detail", "event_id": event_id})


@ev2_bp.post("/events/<int:event_id>/students")
def ev2_event_add_students(event_id: int):
    return jsonify({"status": "ok", "route": "event_add_students", "event_id": event_id})


@ev2_bp.post("/events/<int:event_id>/assessments")
def ev2_event_submit_assessments(event_id: int):
    return jsonify({"status": "ok", "route": "event_submit_assessments", "event_id": event_id})


# minimal placeholder UI routes
@ev2_bp.get("/ui/alunos")
def ev2_ui_alunos():
    return render_template("ev2/alunos.html")


@ev2_bp.get("/ui/trabalhos")
def ev2_ui_trabalhos():
    return render_template("ev2/trabalhos.html")


@ev2_bp.get("/ui/mapas")
def ev2_ui_mapas():
    return render_template("ev2/mapas.html")


@ev2_bp.get("/ui/config")
def ev2_ui_config():
    return render_template("ev2/config.html")
