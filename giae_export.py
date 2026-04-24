from __future__ import annotations

import html
import re
from datetime import date, datetime, time as dt_time
from typing import Any

from sqlalchemy.orm import joinedload

from models import AulaAluno, CalendarioAula


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?i)<\s*br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</\s*(p|div|tr|h[1-6])\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _format_hhmm(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%H:%M")
    if isinstance(value, dt_time):
        return value.strftime("%H:%M")
    text = str(value).strip()
    if not text:
        return ""
    try:
        parsed = dt_time.fromisoformat(text)
        return parsed.strftime("%H:%M")
    except ValueError:
        if len(text) >= 5 and text[2] == ":":
            return text[:5]
    return ""


def _resolve_disciplina(aula: CalendarioAula) -> str:
    return ""


def _calcular_blocos(carga: Any) -> int:
    if carga in (None, ""):
        return 1
    try:
        blocos = int(carga)
    except (TypeError, ValueError):
        return 1
    return blocos if blocos >= 1 else 1


def _obter_tempo_inicio(turma: Any, weekday: int | None) -> int:
    mapa = {
        0: "tempo_segunda",
        1: "tempo_terca",
        2: "tempo_quarta",
        3: "tempo_quinta",
        4: "tempo_sexta",
    }
    campo = mapa.get(weekday)
    if not campo:
        return 1
    valor = getattr(turma, campo, None) if turma is not None else None
    try:
        tempo = int(valor)
    except (TypeError, ValueError):
        return 1
    return tempo if tempo >= 1 else 1


def _obter_blocos_previstos(turma: Any, weekday: int | None) -> int:
    mapa = {
        0: "carga_segunda",
        1: "carga_terca",
        2: "carga_quarta",
        3: "carga_quinta",
        4: "carga_sexta",
    }
    campo = mapa.get(weekday)
    carga = getattr(turma, campo, None) if (campo and turma is not None) else None
    return _calcular_blocos(carga)


def _build_falta_item(registo: AulaAluno, tipo: str, tempos: int) -> dict[str, Any]:
    aluno = registo.aluno
    return {
        "aluno_id": registo.aluno_id,
        "numero": getattr(aluno, "numero", None),
        "nome": (getattr(aluno, "nome", "") or "").strip(),
        "tipo": tipo,
        "tempos": int(tempos),
        "observacoes": _clean_text(getattr(registo, "observacoes", None)),
    }


def _build_faltas_for_aula(aula: CalendarioAula) -> list[dict[str, Any]]:
    itens: list[tuple[int, int, dict[str, Any]]] = []
    for idx, registo in enumerate(aula.avaliacoes or []):
        numero_aluno = getattr(registo.aluno, "numero", None)
        sort_numero = numero_aluno if isinstance(numero_aluno, int) else 10**9

        if int(getattr(registo, "falta_disciplinar", 0) or 0) > 0:
            tempos_fdis = int(getattr(registo, "falta_disciplinar", 0) or 0)
            if tempos_fdis <= 0:
                tempos_fdis = 1
            itens.append((sort_numero, idx, _build_falta_item(registo, "fdis", tempos_fdis)))

        if bool(getattr(registo, "atraso", False)):
            itens.append((sort_numero, idx, _build_falta_item(registo, "atraso", 0)))

        faltas = int(getattr(registo, "faltas", 0) or 0)
        if faltas > 0:
            itens.append((sort_numero, idx, _build_falta_item(registo, "falta", faltas)))

    itens.sort(key=lambda x: (x[0], x[1]))
    return [item[2] for item in itens]


def build_giae_export_for_date(data_ref: date) -> dict[str, Any]:
    aulas = (
        CalendarioAula.query.options(
            joinedload(CalendarioAula.turma),
            joinedload(CalendarioAula.modulo),
            joinedload(CalendarioAula.avaliacoes).joinedload(AulaAluno.aluno),
        )
        .filter(
            CalendarioAula.data == data_ref,
            CalendarioAula.apagado.is_(False),
        )
        .all()
    )

    aulas = sorted(
        aulas,
        key=lambda aula: (
            _format_hhmm(getattr(aula, "hora_inicio", None)) or "99:99",
            getattr(aula, "id", 0),
        ),
    )

    payload_aulas: list[dict[str, Any]] = []
    for aula in aulas:
        payload_aulas.append(
            {
                "aula_id": aula.id,
                "turma": (getattr(aula.turma, "nome", "") or "").strip(),
                "disciplina": _resolve_disciplina(aula),
                "modulo": (getattr(getattr(aula, "modulo", None), "nome", "") or "").strip(),
                "tempo_inicio": _obter_tempo_inicio(getattr(aula, "turma", None), getattr(aula, "weekday", None)),
                "blocos_previstos": _obter_blocos_previstos(getattr(aula, "turma", None), getattr(aula, "weekday", None)),
                "hora_inicio": _format_hhmm(getattr(aula, "hora_inicio", None)),
                "hora_fim": _format_hhmm(getattr(aula, "hora_fim", None)),
                "sumario": _clean_text(getattr(aula, "sumario", None)),
                "faltas": _build_faltas_for_aula(aula),
            }
        )

    return {
        "schema_version": "1.3",
        "data": data_ref.isoformat(),
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "origem": "sumarios-v1",
        "aulas": payload_aulas,
    }
