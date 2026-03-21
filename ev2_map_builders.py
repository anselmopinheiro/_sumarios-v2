from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from models import Aluno, AnoLetivo, EV2Event, EV2SubjectConfig, Periodo
from ev2_calculation_service import aggregate_period_results


def _week_range(reference_date: date) -> Tuple[date, date]:
    start = reference_date - timedelta(days=reference_date.weekday())
    end = start + timedelta(days=6)
    return start, end


def _month_range(year: int, month: int) -> Tuple[date, date]:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _period_range(periodo_id: int) -> Tuple[date, date, Periodo]:
    periodo = Periodo.query.get(periodo_id)
    if not periodo:
        raise ValueError(f"Periodo {periodo_id} not found")
    return periodo.data_inicio, periodo.data_fim, periodo


def _semester_range(ano_letivo_id: int, semestre: int) -> Tuple[date, date, AnoLetivo]:
    ano = AnoLetivo.query.get(ano_letivo_id)
    if not ano:
        raise ValueError(f"AnoLetivo {ano_letivo_id} not found")
    if semestre == 1:
        return ano.data_inicio_ano, ano.data_fim_semestre1, ano
    if semestre == 2:
        return ano.data_inicio_semestre2, ano.data_fim_ano, ano
    raise ValueError("semestre must be 1 or 2")


def _annual_range(ano_letivo_id: int) -> Tuple[date, date, AnoLetivo]:
    ano = AnoLetivo.query.get(ano_letivo_id)
    if not ano:
        raise ValueError(f"AnoLetivo {ano_letivo_id} not found")
    return ano.data_inicio_ano, ano.data_fim_ano, ano


def _ordered_students(turma_id: int) -> List[Aluno]:
    """Fully deterministic ordering by (numero, nome, id)."""
    return (
        Aluno.query.filter_by(turma_id=turma_id)
        .order_by(Aluno.numero.is_(None), Aluno.numero, Aluno.nome, Aluno.id)
        .all()
    )


def _event_allows_active_config_fallback(event: EV2Event) -> bool:
    snap = event.config_snapshot if isinstance(event.config_snapshot, dict) else {}
    if snap.get("allow_active_config_fallback") is True:
        return True
    titulo = (event.titulo or "").lower()
    return titulo.startswith("[draft]") or titulo.startswith("[incomplete]")


def _extract_domain_meta_from_snapshot(snapshot: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    raw = snapshot.get("domains") or snapshot.get("domain_order") or []
    out: Dict[int, Dict[str, Any]] = {}
    if not isinstance(raw, list):
        return out

    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        did = item.get("domain_id") or item.get("id")
        if did is None:
            continue
        did = int(did)
        out[did] = {
            "domain_id": did,
            "ordem": int(item.get("ordem", idx)),
            "weight": float(item.get("weight", 0)),
            "nome": item.get("nome") or f"Domínio {did}",
        }
    return out


def _domain_signature(domain_meta: Dict[int, Dict[str, Any]]) -> Tuple:
    return tuple(
        sorted(
            (
                int(did),
                int(meta.get("ordem", 9999)),
                float(meta.get("weight", 0)),
                str(meta.get("nome", "")),
            )
            for did, meta in domain_meta.items()
        )
    )


def _fallback_domain_meta_from_active_config(turma_id: int, disciplina_id: int) -> Dict[int, Dict[str, Any]]:
    cfg = (
        EV2SubjectConfig.query
        .filter_by(turma_id=turma_id, disciplina_id=disciplina_id, ativo=True, usar_ev2=True)
        .order_by(EV2SubjectConfig.id.desc())
        .first()
    )
    if not cfg:
        cfg = (
            EV2SubjectConfig.query
            .filter_by(turma_id=turma_id, disciplina_id=disciplina_id, ativo=True)
            .order_by(EV2SubjectConfig.id.desc())
            .first()
        )
    if not cfg:
        return {}

    accum = defaultdict(float)
    names: Dict[int, str] = {}
    order: Dict[int, int] = {}
    for idx, sr in enumerate(sorted(cfg.rubrics, key=lambda x: x.id)):
        did = int(sr.rubrica.domain_id)
        accum[did] += float(sr.weight or 0)
        names.setdefault(did, getattr(sr.rubrica.dominio, "nome", f"Domínio {did}"))
        order.setdefault(did, idx)

    out: Dict[int, Dict[str, Any]] = {}
    for did in sorted(accum.keys()):
        out[did] = {
            "domain_id": did,
            "ordem": order[did],
            "weight": accum[did],
            "nome": names[did],
        }
    return out


def _domain_order_and_weights(
    turma_id: int,
    disciplina_id: int,
    data_inicio: date,
    data_fim: date,
) -> Tuple[List[int], Dict[int, Dict[str, Any]], Dict[str, Any]]:
    """Historical domain strategy for maps.

    Strategy: use MOST RECENT snapshot metadata in range.
    - detect divergence when multiple snapshot signatures exist
    - active-config fallback only when there is no snapshot metadata AND all events
      in range are explicitly draft/incomplete
    """

    events = (
        EV2Event.query
        .filter(EV2Event.disciplina_id == disciplina_id)
        .filter(EV2Event.data >= data_inicio, EV2Event.data <= data_fim)
        .join(EV2Event.subject_config)
        .filter(EV2SubjectConfig.turma_id == turma_id)
        .order_by(EV2Event.data, EV2Event.id)
        .all()
    )

    snapshot_candidates: List[Tuple[Tuple, Dict[int, Dict[str, Any]], int]] = []
    for ev in events:
        snap = ev.config_snapshot if isinstance(ev.config_snapshot, dict) else {}
        meta = _extract_domain_meta_from_snapshot(snap)
        if not meta:
            continue
        snapshot_candidates.append((_domain_signature(meta), meta, ev.id))

    configuration_changed_in_range = False
    selected_source = "none"
    selected_event_id = None

    if snapshot_candidates:
        signatures = {sig for sig, _meta, _eid in snapshot_candidates}
        configuration_changed_in_range = len(signatures) > 1
        # most recent snapshot in range
        _sig, chosen_meta, selected_event_id = snapshot_candidates[-1]
        selected_source = "snapshot_most_recent"
        domain_meta = chosen_meta
    else:
        all_explicit_fallback = bool(events) and all(_event_allows_active_config_fallback(ev) for ev in events)
        if all_explicit_fallback:
            domain_meta = _fallback_domain_meta_from_active_config(turma_id, disciplina_id)
            selected_source = "active_config_explicit_draft_fallback"
        else:
            domain_meta = {}
            selected_source = "none_no_historical_snapshot"

    ordered_ids = [
        did for did, _ in sorted(domain_meta.items(), key=lambda kv: (kv[1].get("ordem", 9999), kv[0]))
    ]
    meta_info = {
        "domain_metadata_source": selected_source,
        "configuration_changed_in_range": configuration_changed_in_range,
        "selected_snapshot_event_id": selected_event_id,
        "snapshots_found_in_range": len(snapshot_candidates),
        "events_in_range": len(events),
    }
    return ordered_ids, domain_meta, meta_info


def _safe_avg(values: List[Optional[float]]) -> Optional[float]:
    nums = [float(v) for v in values if v is not None]
    if not nums:
        return None
    return round(sum(nums) / len(nums), 2)


def _domain_fallback_cell(domain_id: int) -> Dict[str, Any]:
    return {
        "domain_id": domain_id,
        "score": {"raw": None, "rounded_2": None, "normalized_1_5": None, "normalized_1_20": None},
        "samples": 0,
    }


def _build_map_for_range(
    *,
    map_type: str,
    turma_id: int,
    disciplina_id: int,
    data_inicio: date,
    data_fim: date,
    autoavaliacao_by_aluno: Optional[Dict[int, Any]] = None,
    notas_contexto_by_aluno: Optional[Dict[int, Any]] = None,
    include_raw: bool = False,
) -> Dict[str, Any]:
    autoavaliacao_by_aluno = autoavaliacao_by_aluno or {}
    notas_contexto_by_aluno = notas_contexto_by_aluno or {}

    students = _ordered_students(turma_id)
    domain_order, domain_meta, domain_meta_info = _domain_order_and_weights(
        turma_id, disciplina_id, data_inicio, data_fim
    )

    columns = [
        {"key": "numero", "label": "Nº"},
        {"key": "aluno", "label": "Aluno"},
        {"key": "eventos", "label": "Eventos"},
    ]
    for did in domain_order:
        d = domain_meta.get(did, {})
        columns.append(
            {
                "key": f"dominio_{did}",
                "label": d.get("nome", f"Domínio {did}"),
                "domain_id": did,
                "weight": d.get("weight", 0),
                "value": "rounded_2",
            }
        )

    columns.extend(
        [
            {"key": "final_raw", "label": "Média final (raw)"},
            {"key": "final_display_rounded_2", "label": "Média final (2 casas)"},
            {
                "key": "classificacao_display",
                "label": "Classificação (display numérico)",
                "notes": "Alias de final_display_rounded_2; não aplica regra qualitativa.",
            },
            {"key": "autoavaliacao", "label": "Autoavaliação (informativa)"},
            {"key": "notas", "label": "Notas/contexto"},
        ]
    )

    rows: List[Dict[str, Any]] = []
    for aluno in students:
        agg = aggregate_period_results(
            turma_id=turma_id,
            disciplina_id=disciplina_id,
            aluno_id=aluno.id,
            data_inicio=data_inicio,
            data_fim=data_fim,
        )

        domain_values: Dict[str, Any] = {}
        domain_details: Dict[str, Any] = {}
        for did in domain_order:
            detail = agg.get("dominios", {}).get(did, _domain_fallback_cell(did))
            domain_values[f"dominio_{did}"] = (detail.get("score") or {}).get("rounded_2")
            domain_details[f"dominio_{did}"] = detail

        final_score = agg.get("final", {}).get("score", {})
        row = {
            "aluno_id": aluno.id,
            "numero": aluno.numero,
            "aluno": aluno.nome,
            "eventos": agg.get("meta", {}).get("events_count", 0),
            **domain_values,
            "final_raw": final_score.get("raw"),
            "final_display_rounded_2": final_score.get("rounded_2"),
            "classificacao_display": final_score.get("rounded_2"),
            "autoavaliacao": autoavaliacao_by_aluno.get(aluno.id),
            "notas": notas_contexto_by_aluno.get(aluno.id),
            # optional details for future templates/export transforms
            "domain_details": domain_details,
            "rubricas": agg.get("rubricas", {}),
            "tipos": agg.get("tipos", {}),
        }
        if include_raw:
            row["_raw"] = agg

        rows.append(row)

    totals = {
        "alunos": len(rows),
        "eventos_total": sum(r.get("eventos", 0) for r in rows),
        "final_media_turma_raw": _safe_avg([r.get("final_raw") for r in rows]),
        "final_media_turma_display_rounded_2": _safe_avg([r.get("final_display_rounded_2") for r in rows]),
    }

    return {
        "meta": {
            "map_type": map_type,
            "turma_id": turma_id,
            "disciplina_id": disciplina_id,
            "data_inicio": data_inicio.isoformat(),
            "data_fim": data_fim.isoformat(),
            "domain_order": domain_order,
            "domain_meta": domain_meta,
            **domain_meta_info,
            "classificacao_display_rule": "rounded numeric display only (no qualitative grading rule)",
            "flattening_convention": {
                "domain": "dominio_<id> => rounded_2",
                "final": ["final_raw", "final_display_rounded_2"],
                "details": ["domain_details", "rubricas", "tipos", "_raw(optional)"],
            },
        },
        "columns": columns,
        "rows": rows,
        "totals": totals,
    }


def build_weekly_map(
    turma_id: int,
    disciplina_id: int,
    reference_date: date,
    autoavaliacao_by_aluno: Optional[Dict[int, Any]] = None,
    notas_contexto_by_aluno: Optional[Dict[int, Any]] = None,
    include_raw: bool = False,
) -> Dict[str, Any]:
    data_inicio, data_fim = _week_range(reference_date)
    return _build_map_for_range(
        map_type="weekly",
        turma_id=turma_id,
        disciplina_id=disciplina_id,
        data_inicio=data_inicio,
        data_fim=data_fim,
        autoavaliacao_by_aluno=autoavaliacao_by_aluno,
        notas_contexto_by_aluno=notas_contexto_by_aluno,
        include_raw=include_raw,
    )


def build_monthly_map(
    turma_id: int,
    disciplina_id: int,
    year: int,
    month: int,
    autoavaliacao_by_aluno: Optional[Dict[int, Any]] = None,
    notas_contexto_by_aluno: Optional[Dict[int, Any]] = None,
    include_raw: bool = False,
) -> Dict[str, Any]:
    data_inicio, data_fim = _month_range(year, month)
    return _build_map_for_range(
        map_type="monthly",
        turma_id=turma_id,
        disciplina_id=disciplina_id,
        data_inicio=data_inicio,
        data_fim=data_fim,
        autoavaliacao_by_aluno=autoavaliacao_by_aluno,
        notas_contexto_by_aluno=notas_contexto_by_aluno,
        include_raw=include_raw,
    )


def build_period_map(
    turma_id: int,
    disciplina_id: int,
    periodo_id: int,
    autoavaliacao_by_aluno: Optional[Dict[int, Any]] = None,
    notas_contexto_by_aluno: Optional[Dict[int, Any]] = None,
    include_raw: bool = False,
) -> Dict[str, Any]:
    data_inicio, data_fim, periodo = _period_range(periodo_id)
    out = _build_map_for_range(
        map_type="period",
        turma_id=turma_id,
        disciplina_id=disciplina_id,
        data_inicio=data_inicio,
        data_fim=data_fim,
        autoavaliacao_by_aluno=autoavaliacao_by_aluno,
        notas_contexto_by_aluno=notas_contexto_by_aluno,
        include_raw=include_raw,
    )
    out["meta"]["periodo"] = {"id": periodo.id, "nome": periodo.nome, "tipo": periodo.tipo}
    return out


def build_semester_map(
    turma_id: int,
    disciplina_id: int,
    ano_letivo_id: int,
    semestre: int,
    autoavaliacao_by_aluno: Optional[Dict[int, Any]] = None,
    notas_contexto_by_aluno: Optional[Dict[int, Any]] = None,
    include_raw: bool = False,
) -> Dict[str, Any]:
    data_inicio, data_fim, ano = _semester_range(ano_letivo_id, semestre)
    out = _build_map_for_range(
        map_type=f"semester_{semestre}",
        turma_id=turma_id,
        disciplina_id=disciplina_id,
        data_inicio=data_inicio,
        data_fim=data_fim,
        autoavaliacao_by_aluno=autoavaliacao_by_aluno,
        notas_contexto_by_aluno=notas_contexto_by_aluno,
        include_raw=include_raw,
    )
    out["meta"]["ano_letivo"] = {"id": ano.id, "nome": ano.nome}
    return out


def build_annual_map(
    turma_id: int,
    disciplina_id: int,
    ano_letivo_id: int,
    autoavaliacao_by_aluno: Optional[Dict[int, Any]] = None,
    notas_contexto_by_aluno: Optional[Dict[int, Any]] = None,
    include_raw: bool = False,
) -> Dict[str, Any]:
    data_inicio, data_fim, ano = _annual_range(ano_letivo_id)
    out = _build_map_for_range(
        map_type="annual",
        turma_id=turma_id,
        disciplina_id=disciplina_id,
        data_inicio=data_inicio,
        data_fim=data_fim,
        autoavaliacao_by_aluno=autoavaliacao_by_aluno,
        notas_contexto_by_aluno=notas_contexto_by_aluno,
        include_raw=include_raw,
    )
    out["meta"]["ano_letivo"] = {"id": ano.id, "nome": ano.nome}
    return out


def build_final_summary_map(
    turma_id: int,
    disciplina_id: int,
    data_inicio: date,
    data_fim: date,
    autoavaliacao_by_aluno: Optional[Dict[int, Any]] = None,
    notas_contexto_by_aluno: Optional[Dict[int, Any]] = None,
    include_raw: bool = False,
) -> Dict[str, Any]:
    """Final summary table in avaliacao1sem-like tabular layout.

    Rows are 1:1 aligned with columns.
    """

    base = _build_map_for_range(
        map_type="final_summary",
        turma_id=turma_id,
        disciplina_id=disciplina_id,
        data_inicio=data_inicio,
        data_fim=data_fim,
        autoavaliacao_by_aluno=autoavaliacao_by_aluno,
        notas_contexto_by_aluno=notas_contexto_by_aluno,
        include_raw=include_raw,
    )

    # Keep rows tabular; optional nested details remain as auxiliary fields.
    rows: List[Dict[str, Any]] = []
    domain_keys = [c["key"] for c in base["columns"] if c["key"].startswith("dominio_")]
    for r in base["rows"]:
        row = {
            "aluno_id": r["aluno_id"],
            "numero": r["numero"],
            "aluno": r["aluno"],
            "eventos": r.get("eventos", 0),
        }
        for dk in domain_keys:
            row[dk] = r.get(dk)
        row.update(
            {
                "final_raw": r.get("final_raw"),
                "final_display_rounded_2": r.get("final_display_rounded_2"),
                "classificacao_display": r.get("classificacao_display"),
                "autoavaliacao": r.get("autoavaliacao"),
                "notas": r.get("notas"),
                "domain_details": r.get("domain_details"),
                "rubricas": r.get("rubricas"),
                "tipos": r.get("tipos"),
            }
        )
        if include_raw and "_raw" in r:
            row["_raw"] = r["_raw"]
        rows.append(row)

    return {
        "meta": {
            **base["meta"],
            "layout": "avaliacao1sem_like",
            "domain_columns_ordered": [c for c in base["columns"] if c["key"].startswith("dominio_")],
        },
        "columns": base["columns"],
        "rows": rows,
        "totals": base["totals"],
    }
