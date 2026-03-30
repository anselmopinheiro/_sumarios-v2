from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import joinedload

from models import EV2Assessment, EV2Event, EV2EventStudent, EV2SubjectConfig, EV2SubjectTypeWeight


VALID_ASSESSMENT_STATES = {"avaliado", "ausente", "nao_observado"}
VALID_ASSIDUIDADE_STATES = {"presente_total", "parcial", "ausente_total"}


@dataclass
class EV2AttendanceResult:
    tempos_totais: int
    tempos_presentes: int
    assiduidade_ratio: float
    estado_assiduidade: str
    elegivel_avaliacao: bool


@dataclass
class EV2EventStudentResult:
    event_id: int
    event_student_id: int
    aluno_id: int
    event_date: date
    evaluation_type: str
    peso_evento: float
    elegivel_avaliacao: bool
    rubricas: Dict[int, Dict[str, Any]]
    dominios: Dict[int, Dict[str, Any]]
    componente_extra: Dict[str, Any]
    nota_evento: Optional[float]


def _to_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def _weighted_average(values_and_weights: Iterable[Tuple[Decimal, Decimal]]) -> Optional[float]:
    total_weight = Decimal("0")
    total_value = Decimal("0")
    for value, weight in values_and_weights:
        w = _to_decimal(weight)
        if value is None or w <= 0:
            continue
        total_weight += w
        total_value += (_to_decimal(value) * w)
    if total_weight <= 0:
        return None
    return float(total_value / total_weight)


def _round_or_none(value: Optional[float], digits: int = 2) -> Optional[float]:
    return None if value is None else round(float(value), digits)


def _scale_value(
    value: Optional[float],
    source_min: Optional[float],
    source_max: Optional[float],
    target_min: float,
    target_max: float,
) -> Optional[float]:
    if value is None or source_min is None or source_max is None:
        return None
    src_span = float(source_max) - float(source_min)
    if src_span <= 0:
        return None
    pos = (float(value) - float(source_min)) / src_span
    out = float(target_min) + pos * (float(target_max) - float(target_min))
    return out


def normalize_numeric_output(
    value: Optional[float],
    source_scale: Optional[Tuple[float, float]] = None,
) -> Dict[str, Optional[float]]:
    """Normalize numeric output for later map builders.

    Returned keys:
    - raw: unrounded float
    - rounded_2: rounded for display
    - normalized_1_5: converted value when source scale is known
    - normalized_1_20: converted value when source scale is known
    """

    source_min = source_scale[0] if source_scale else None
    source_max = source_scale[1] if source_scale else None
    n15 = _scale_value(value, source_min, source_max, 1, 5)
    n120 = _scale_value(value, source_min, source_max, 1, 20)
    return {
        "raw": None if value is None else float(value),
        "rounded_2": _round_or_none(value, 2),
        "normalized_1_5": _round_or_none(n15, 2),
        "normalized_1_20": _round_or_none(n120, 2),
    }


# ---------- Attendance helpers ----------


def compute_assiduidade_ratio(tempos_presentes: int, tempos_totais: int) -> float:
    totais = max(int(tempos_totais or 0), 1)
    presentes = max(0, min(int(tempos_presentes or 0), totais))
    return presentes / totais


def derive_estado_assiduidade(tempos_presentes: int, tempos_totais: int) -> str:
    ratio = compute_assiduidade_ratio(tempos_presentes, tempos_totais)
    if ratio <= 0:
        return "ausente_total"
    if ratio >= 1:
        return "presente_total"
    return "parcial"


def determine_elegivel_avaliacao(tempos_presentes: int, tempos_totais: int) -> bool:
    return compute_assiduidade_ratio(tempos_presentes, tempos_totais) > 0


def build_attendance_result(tempos_presentes: int, tempos_totais: int) -> EV2AttendanceResult:
    ratio = compute_assiduidade_ratio(tempos_presentes, tempos_totais)
    return EV2AttendanceResult(
        tempos_totais=max(int(tempos_totais or 0), 1),
        tempos_presentes=max(0, min(int(tempos_presentes or 0), max(int(tempos_totais or 0), 1))),
        assiduidade_ratio=ratio,
        estado_assiduidade=derive_estado_assiduidade(tempos_presentes, tempos_totais),
        elegivel_avaliacao=ratio > 0,
    )


# ---------- Assessment filtering ----------


def assessment_counts_for_average(assessment: EV2Assessment) -> bool:
    return bool(
        assessment
        and assessment.state == "avaliado"
        and assessment.score_numeric is not None
    )


def filter_countable_assessments(assessments: Iterable[EV2Assessment]) -> List[EV2Assessment]:
    return [a for a in assessments if assessment_counts_for_average(a)]


# ---------- Historical stability policy ----------


def _event_has_snapshot(event: EV2Event) -> bool:
    return isinstance(event.config_snapshot, dict) and bool(event.config_snapshot)


def _event_allows_active_config_fallback(event: EV2Event) -> bool:
    """Fallback is only allowed for explicitly draft/incomplete events.

    Implemented rule:
    1) If config_snapshot exists -> use snapshot only.
    2) Fallback to active config is allowed only when snapshot is absent/empty AND
       event is explicitly marked for fallback in snapshot metadata or by draft title tag.
    """

    snapshot = event.config_snapshot if isinstance(event.config_snapshot, dict) else {}
    if snapshot.get("allow_active_config_fallback") is True:
        return True
    titulo = (event.titulo or "").lower()
    return titulo.startswith("[draft]") or titulo.startswith("[incomplete]")


def _snapshot_subject_rubric_meta(snapshot: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    raw = snapshot.get("subject_rubrics") or snapshot.get("rubrics") or []
    out: Dict[int, Dict[str, Any]] = {}
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            rubric_id = item.get("rubric_id") or item.get("id")
            if rubric_id is None:
                continue
            out[int(rubric_id)] = {
                "weight": _to_decimal(item.get("weight"), Decimal("0")),
                "scale_min": item.get("scale_min"),
                "scale_max": item.get("scale_max"),
            }
    return out


def _snapshot_type_weights(snapshot: Dict[str, Any]) -> Dict[str, Decimal]:
    raw = snapshot.get("type_weights") or snapshot.get("subject_type_weights") or []
    out: Dict[str, Decimal] = {}
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            tipo = item.get("evaluation_type") or item.get("type")
            if tipo:
                out[str(tipo)] = _to_decimal(item.get("weight"), Decimal("0"))
    return out


def _resolve_type_weight_for_event(event: EV2Event) -> Decimal:
    if _event_has_snapshot(event):
        weights = _snapshot_type_weights(event.config_snapshot)
        return weights.get(event.evaluation_type, Decimal("0"))

    if _event_allows_active_config_fallback(event):
        active = {
            w.evaluation_type: _to_decimal(w.weight, Decimal("0"))
            for w in (event.subject_config.type_weights or [])
            if isinstance(w, EV2SubjectTypeWeight)
        }
        return active.get(event.evaluation_type, Decimal("0"))

    # Historical strictness: no snapshot + no explicit fallback = no inferred config.
    return Decimal("0")


def _resolve_rubric_meta(event: EV2Event, rubric_id: int) -> Dict[str, Any]:
    scale_min = getattr(event.subject_config, "escala_min", None) if event.subject_config else None
    scale_max = getattr(event.subject_config, "escala_max", None) if event.subject_config else None
    if _event_has_snapshot(event):
        item = _snapshot_subject_rubric_meta(event.config_snapshot).get(
            rubric_id, {"weight": Decimal("0"), "scale_min": None, "scale_max": None}
        )
        return {
            "weight": item.get("weight", Decimal("0")),
            "scale_min": scale_min if scale_min is not None else item.get("scale_min"),
            "scale_max": scale_max if scale_max is not None else item.get("scale_max"),
        }

    if _event_allows_active_config_fallback(event):
        for sr in event.subject_config.rubrics or []:
            if sr.rubric_id == rubric_id:
                return {
                    "weight": _to_decimal(sr.weight, Decimal("0")),
                    "scale_min": scale_min if scale_min is not None else sr.scale_min,
                    "scale_max": scale_max if scale_max is not None else sr.scale_max,
                }

    return {
        "weight": Decimal("0"),
        "scale_min": scale_min,
        "scale_max": scale_max,
    }


# ---------- Event-level calculations ----------


def compute_event_student_rubric_results(event_student: EV2EventStudent) -> Dict[int, Dict[str, Any]]:
    if not event_student.elegivel_avaliacao:
        return {}

    results: Dict[int, Dict[str, Any]] = {}
    for a in filter_countable_assessments(event_student.assessments):
        if a.tipo != "rubrica" or a.rubric_id is None or a.rubrica is None:
            continue
        rid = int(a.rubric_id)
        meta = _resolve_rubric_meta(event_student.event, rid)
        score = float(a.score_numeric)
        results[rid] = {
            "rubric_id": rid,
            "domain_id": int(a.rubrica.domain_id),
            "assessment_id": a.id,
            "weight": float(meta["weight"]),
            "scale_min": meta["scale_min"],
            "scale_max": meta["scale_max"],
            "score": normalize_numeric_output(score, source_scale=(meta["scale_min"], meta["scale_max"]) if meta["scale_min"] is not None and meta["scale_max"] is not None else None),
        }
    return results


def compute_event_student_domain_results(event_student: EV2EventStudent) -> Dict[int, Dict[str, Any]]:
    rubrics = compute_event_student_rubric_results(event_student)
    grouped: Dict[int, List[Tuple[Decimal, Decimal]]] = defaultdict(list)
    for r in rubrics.values():
        grouped[r["domain_id"]].append((_to_decimal(r["score"]["raw"]), _to_decimal(r["weight"])))

    out: Dict[int, Dict[str, Any]] = {}
    for domain_id, items in grouped.items():
        raw = _weighted_average(items)
        out[domain_id] = {
            "domain_id": domain_id,
            "score": normalize_numeric_output(raw),
            "rubrics_count": len(items),
        }
    return out


def compute_event_student_extra_component(event_student: EV2EventStudent) -> Dict[str, Any]:
    if not event_student.elegivel_avaliacao:
        return {"score": normalize_numeric_output(None), "assessments_count": 0}

    extras = [
        a
        for a in filter_countable_assessments(event_student.assessments)
        if a.tipo == "extra_param" and a.extra_param_id is not None
    ]
    raw = _weighted_average([(_to_decimal(a.score_numeric), _to_decimal(a.weight, Decimal("1"))) for a in extras])
    return {
        "score": normalize_numeric_output(raw),
        "assessments_count": len(extras),
    }


def compute_event_student_final_result(event_student: EV2EventStudent) -> EV2EventStudentResult:
    event = event_student.event
    rubrics = compute_event_student_rubric_results(event_student)
    domains = compute_event_student_domain_results(event_student)
    extra_component = compute_event_student_extra_component(event_student)

    rubric_raw = _weighted_average([
        (_to_decimal(v["score"]["raw"]), _to_decimal(v["weight"])) for v in rubrics.values()
    ])
    extra_raw = extra_component["score"]["raw"]

    extra_weight = _to_decimal(event.extra_component_weight, Decimal("0"))
    rubric_weight = Decimal("100") - extra_weight
    parts: List[Tuple[Decimal, Decimal]] = []
    if rubric_raw is not None and rubric_weight > 0:
        parts.append((_to_decimal(rubric_raw), rubric_weight))
    if extra_raw is not None and extra_weight > 0:
        parts.append((_to_decimal(extra_raw), extra_weight))

    nota_evento = _weighted_average(parts) if parts else rubric_raw

    return EV2EventStudentResult(
        event_id=event.id,
        event_student_id=event_student.id,
        aluno_id=event_student.aluno_id,
        event_date=event.data,
        evaluation_type=event.evaluation_type,
        peso_evento=float(_to_decimal(event.peso_evento, Decimal("100"))),
        elegivel_avaliacao=bool(event_student.elegivel_avaliacao),
        rubricas=rubrics,
        dominios=domains,
        componente_extra=extra_component,
        nota_evento=nota_evento,
    )


# ---------- Period aggregation ----------


def aggregate_period_results(
    turma_id: int,
    disciplina_id: int,
    aluno_id: int,
    data_inicio: date,
    data_fim: date,
) -> Dict[str, Any]:
    """Aggregate EV2 data for weekly/monthly/period/semester/annual/final maps.

    Historical rule enforced:
    - If `ev2_events.config_snapshot` exists, all config-dependent calculations use only
      that snapshot.
    - Active-config fallback is allowed only for explicitly draft/incomplete events.
    """

    entries = (
        EV2EventStudent.query.join(EV2Event, EV2EventStudent.event_id == EV2Event.id)
        .join(EV2Event.subject_config)
        .filter(EV2EventStudent.aluno_id == aluno_id)
        .filter(EV2Event.disciplina_id == disciplina_id)
        .filter(EV2Event.data >= data_inicio, EV2Event.data <= data_fim)
        .filter(EV2SubjectConfig.turma_id == turma_id)
        .options(
            joinedload(EV2EventStudent.event).joinedload(EV2Event.subject_config).joinedload(EV2SubjectConfig.type_weights),
            joinedload(EV2EventStudent.event).joinedload(EV2Event.subject_config).joinedload(EV2SubjectConfig.rubrics),
            joinedload(EV2EventStudent.assessments).joinedload(EV2Assessment.rubrica),
            joinedload(EV2EventStudent.assessments).joinedload(EV2Assessment.extra_param),
        )
        .all()
    )

    event_results: List[EV2EventStudentResult] = [compute_event_student_final_result(e) for e in entries]
    by_entry_id = {e.id: e for e in entries}

    rubric_agg: Dict[int, List[Tuple[Decimal, Decimal]]] = defaultdict(list)
    domain_agg: Dict[int, List[Tuple[Decimal, Decimal]]] = defaultdict(list)
    type_agg: Dict[str, List[Tuple[Decimal, Decimal]]] = defaultdict(list)
    final_agg: List[Tuple[Decimal, Decimal]] = []

    for r in event_results:
        if r.nota_evento is None:
            continue
        event_weight = _to_decimal(r.peso_evento, Decimal("0"))
        type_agg[r.evaluation_type].append((_to_decimal(r.nota_evento), event_weight))

        # final aggregation: weighted by event weight * evaluation-type weight
        ref_entry = by_entry_id.get(r.event_student_id)
        type_weight = _resolve_type_weight_for_event(ref_entry.event) if ref_entry else Decimal("0")
        final_agg.append((_to_decimal(r.nota_evento), event_weight * type_weight))

        for data in r.rubricas.values():
            rubric_agg[data["rubric_id"]].append((_to_decimal(data["score"]["raw"]), event_weight))
        for data in r.dominios.values():
            domain_agg[data["domain_id"]].append((_to_decimal(data["score"]["raw"]), event_weight))

    rubricas = {
        rid: {
            "rubric_id": rid,
            "score": normalize_numeric_output(_weighted_average(items)),
            "samples": len(items),
        }
        for rid, items in rubric_agg.items()
    }
    dominios = {
        did: {
            "domain_id": did,
            "score": normalize_numeric_output(_weighted_average(items)),
            "samples": len(items),
        }
        for did, items in domain_agg.items()
    }
    tipos = {
        t: {
            "evaluation_type": t,
            "score": normalize_numeric_output(_weighted_average(items)),
            "samples": len(items),
            "weighting": "peso_evento",
        }
        for t, items in type_agg.items()
    }

    final_raw = _weighted_average(final_agg)
    return {
        "meta": {
            "turma_id": turma_id,
            "disciplina_id": disciplina_id,
            "aluno_id": aluno_id,
            "data_inicio": data_inicio.isoformat(),
            "data_fim": data_fim.isoformat(),
            "events_count": len(event_results),
            "historical_rule": "snapshot_only_when_present; active_fallback_only_for_explicit_draft_or_incomplete",
            "normalization": {
                "raw": "stored calculation scale",
                "rounded_2": "default display",
                "normalized_1_5": "derived only when source scale is known",
                "normalized_1_20": "derived only when source scale is known",
            },
        },
        "events": [
            {
                "event_id": r.event_id,
                "event_student_id": r.event_student_id,
                "data": r.event_date.isoformat(),
                "evaluation_type": r.evaluation_type,
                "peso_evento": r.peso_evento,
                "elegivel_avaliacao": r.elegivel_avaliacao,
                "nota_evento": normalize_numeric_output(r.nota_evento),
                "rubricas": r.rubricas,
                "dominios": r.dominios,
                "componente_extra": r.componente_extra,
            }
            for r in event_results
        ],
        "rubricas": rubricas,
        "dominios": dominios,
        "tipos": tipos,
        "final": {
            "score": normalize_numeric_output(final_raw),
            "weighting": "peso_evento * type_weight",
        },
    }


def ev2_self_check_examples() -> Dict[str, Any]:
    """Deterministic helper for quick validation by future map builders.

    Example 1: weighted average with event weights 50 and 100 for scores 10 and 14
    => (10*50 + 14*100) / 150 = 12.6667

    Example 2: state filter only counts 'avaliado'.
    """

    weighted = _weighted_average(
        [
            (Decimal("10"), Decimal("50")),
            (Decimal("14"), Decimal("100")),
        ]
    )
    states_demo = {
        "avaliado_counts": assessment_counts_for_average(
            type("A", (), {"state": "avaliado", "score_numeric": 12})()
        ),
        "ausente_counts": assessment_counts_for_average(
            type("A", (), {"state": "ausente", "score_numeric": None})()
        ),
        "nao_observado_counts": assessment_counts_for_average(
            type("A", (), {"state": "nao_observado", "score_numeric": None})()
        ),
    }

    return {
        "weighted_example": {
            "raw": weighted,
            "rounded_2": _round_or_none(weighted, 2),
            "expected_raw": 12.6666666667,
        },
        "state_filter_example": states_demo,
        "attendance_example": build_attendance_result(tempos_presentes=1, tempos_totais=2).__dict__,
    }
