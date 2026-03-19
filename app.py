import calendar
import csv
import gc
import gzip
import html
import importlib
import importlib.util
import io
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid
import platform
import sys
import unicodedata
import logging
from logging.handlers import RotatingFileHandler
from urllib.parse import urlparse, parse_qsl, urlsplit
from collections import defaultdict
from functools import wraps
from datetime import datetime, date, timedelta, timezone, time as dt_time

from flask import (
    Flask,
    current_app,
    render_template,
    redirect,
    url_for,
    request,
    flash,
    Response,
    jsonify,
    send_file,
    send_from_directory,
    abort,
    has_app_context,
    g,
)

from flask_migrate import Migrate
from alembic.script import ScriptDirectory

try:
    import bleach
except Exception:
    bleach = None
from sqlalchemy import create_engine, func, inspect, or_, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import Engine
from sqlalchemy import event
from sqlalchemy.orm import joinedload, sessionmaker
from sqlalchemy.sql.sqltypes import (
    Boolean as SABoolean,
    Date as SADate,
    DateTime as SADateTime,
    Float as SAFloat,
    Integer as SAInteger,
    Numeric as SANumeric,
    Time as SATime,
)

from config import Config
from offline_blueprint import offline_bp, refresh_snapshot_from_remote, snapshot_remote_to_local
from ev2_routes import ev2_bp
from ev2_config_routes import ev2_config_bp
from offline_store import (
    count_offline_errors,
    get_offline_db_path as resolve_offline_db_path,
    get_last_offline_error,
    get_snapshot_status,
    get_state_datetime,
    init_offline_db as init_offline_store_db,
    outbox_status,
)
from sync import fix_sequences_remote, sync_outbox
from offline_queue import (
    clear_sent,
    enqueue_upsert_aulas_alunos,
    flush_pending,
    get_last_error,
    init_offline_db,
    pending_count,
)
from config_store import ConfigStore
from models import (
    db,
    Turma,
    Livro,
    Periodo,
    CalendarioAula,
    Modulo,
    AnoLetivo,
    Disciplina,
    InterrupcaoLetiva,
    Feriado,
    Horario,
    Exclusao,
    Extra,
    LivroTurma,
    TurmaDisciplina,
    Aluno,
    AulaAluno,
    Avaliacao,
    AvaliacaoItem,
    AulaSumarioHistorico,
    DTTurma,
    DTAluno,
    DTJustificacao,
    DTMotivoDia,
    DTJustificacaoTexto,
    AlunoContextoDT,
    EncarregadoEducacao,
    EEAluno,
    DTCargoAluno,
    DTCargoEE,
    TipoContacto,
    MotivoContacto,
    Contacto,
    ContactoTipo,
    ContactoAluno,
    ContactoAlunoMotivo,
    ContactoLink,
    DTDisciplina,
    DTOcorrencia,
    DTOcorrenciaAluno,
    Trabalho,
    GrupoTurma,
    GrupoTurmaMembro,
    TrabalhoGrupo,
    TrabalhoGrupoMembro,
    Entrega,
    EntregaParametro,
    ParametroDefinicao,
    EV2Domain,
    EV2Rubric,
)

from calendario_service import (
    expand_dates,
    gerar_calendario_turma,
    garantir_periodos_basicos_para_turma,
    garantir_modulos_para_turma,
    renumerar_calendario_turma,
    completar_modulos_profissionais,
    criar_aula_extra,
    DEFAULT_TIPOS_SEM_AULA,
    filtrar_periodos_para_turma,
    PERIODOS_TURMA_VALIDOS,
    exportar_sumarios_json,
    importar_sumarios_json,
    importar_calendario_escolar_json,
    exportar_backup_ano,
    importar_backup_ano,
    listar_aulas_especiais,
    calcular_mapa_avaliacao_diaria,
    listar_sumarios_pendentes,
)


BACKUP_LOCK = threading.Lock()


TIPOS_AULA = [
    ("normal", "Normal"),
    ("greve", "Greve"),
    ("faltei", "Faltei"),
    ("servico_oficial", "Serviço oficial"),
    ("outros", "Outros"),
    ("extra", "Extra"),
]

TIPOS_ESPECIAIS = ["greve", "servico_oficial", "outros", "extra", "faltei"]


# --------------------------------------------
# Funções auxiliares fora da factory
# --------------------------------------------
def _slugify_filename(texto, fallback="ficheiro"):
    if not texto:
        return fallback

    safe_nome = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    safe_nome = "_".join(
        filter(
            None,
            ["".join(c if c.isalnum() else "_" for c in safe_nome).strip("_")],
        )
    )

    return safe_nome or fallback


def _strip_html_to_text(html_text):
    if not html_text:
        return ""
    texto = str(html_text)
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    texto = re.sub(r"(?i)<\s*br\s*/?>", "\n", texto)
    texto = re.sub(r"(?i)</\s*(p|div|tr|h[1-6])\s*>", "\n", texto)
    texto = re.sub(r"(?i)<\s*li(?:\s+[^>]*)?>", "- ", texto)
    texto = re.sub(r"(?i)</\s*li\s*>", "\n", texto)
    texto = re.sub(r"<[^>]+>", "", texto)
    texto = html.unescape(texto)
    texto = texto.replace("\u00a0", " ")
    texto = re.sub(r"[ \t]+\n", "\n", texto)
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.rstrip()


def _sanitize_observacoes_html(raw_html):
    allowed_tags = ["p", "br", "b", "strong", "i", "em", "ul", "ol", "li", "a"]

    def _allow_anchor_href(tag, name, value):
        if tag != "a" or name != "href":
            return False
        href = (value or "").strip()
        if not href:
            return False
        parsed = urlparse(href)
        if parsed.scheme.lower() not in {"http", "https"}:
            return False
        return bool(parsed.netloc)

    normalized = (str(raw_html or "")).replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return None

    if bleach is not None:
        cleaned = bleach.clean(
            normalized,
            tags=allowed_tags,
            attributes=_allow_anchor_href,
            protocols=["http", "https"],
            strip=True,
            strip_comments=True,
        )
        cleaned = re.sub(r"<a>(.*?)</a>", r"\1", cleaned, flags=re.IGNORECASE | re.DOTALL)
    else:
        # Fallback sem dependências externas: mantém o conteúdo textual seguro.
        texto = _strip_html_to_text(normalized).strip()
        cleaned = f"<p>{html.escape(texto)}</p>" if texto else ""

    cleaned = cleaned.strip()
    if not cleaned:
        return None

    if not _strip_html_to_text(cleaned).strip():
        return None
    return cleaned


def csv_text(value):
    if value is None:
        return ""
    texto = str(value)
    return f'="{texto}"'


def build_csv_data(headers, rows):
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(headers)
    writer.writerows(rows)
    return "\ufeff" + output.getvalue()


def _easter_sunday(year: int) -> date:
    """Domingo de Páscoa (algoritmo de Meeus/Jones/Butcher)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _ler_modulos_form():
    nomes = request.form.getlist("modulo_nome")
    totais = request.form.getlist("modulo_total")
    ids = request.form.getlist("modulo_id")

    modulos = []
    for idx, nome in enumerate(nomes):
        nome_limpo = (nome or "").strip()
        total_txt = totais[idx] if idx < len(totais) else ""
        try:
            total = int(total_txt) if total_txt not in (None, "") else 0
        except ValueError:
            total = 0

        mod_id_txt = ids[idx] if idx < len(ids) else None
        mod_id = int(mod_id_txt) if mod_id_txt else None

        if not nome_limpo and total == 0:
            continue

        modulos.append({
            "id": mod_id,
            "nome": nome_limpo,
            "total": total,
        })

    return modulos


def _clamp_int(value, default=None, min_val=None, max_val=None):
    try:
        num = int(value)
    except (TypeError, ValueError):
        return default

    if min_val is not None:
        num = max(min_val, num)
    if max_val is not None:
        num = min(max_val, num)
    return num


def _parse_date_form(value):
    """Lê <input type='date'> em formato YYYY-MM-DD."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_time_form(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError:
        return None


AULAS_ALUNOS_FIELDS = {
    "atraso",
    "faltas",
    "responsabilidade",
    "comportamento",
    "participacao",
    "trabalho_autonomo",
    "portatil_material",
    "atividade",
    "falta_disciplinar",
    "observacoes",
}


def _as_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    value_txt = str(value).strip().lower()
    if value_txt in {"1", "true", "t", "yes", "y", "on", "sim"}:
        return True
    if value_txt in {"0", "false", "f", "no", "n", "off", "nao", "não", ""}:
        return False
    return default


def normalize_aulas_alunos_payload(payload):
    payload = payload or {}
    normalized = {}
    if "atraso" in payload:
        normalized["atraso"] = _as_bool(payload.get("atraso"), default=False)

    if "faltas" in payload:
        normalized["faltas"] = _clamp_int(payload.get("faltas"), default=0, min_val=0, max_val=6) or 0

    for campo in [
        "responsabilidade",
        "comportamento",
        "participacao",
        "trabalho_autonomo",
        "portatil_material",
        "atividade",
    ]:
        if campo in payload:
            normalized[campo] = _clamp_int(payload.get(campo), default=3, min_val=1, max_val=5) or 3

    if "falta_disciplinar" in payload:
        normalized["falta_disciplinar"] = (
            _clamp_int(payload.get("falta_disciplinar"), default=0, min_val=0, max_val=2) or 0
        )

    if "observacoes" in payload:
        observacoes = payload.get("observacoes")
        if observacoes is None:
            normalized["observacoes"] = None
        else:
            texto = str(observacoes).replace("\r\n", "\n").replace("\r", "\n").strip()
            if len(texto) > 500:
                texto = texto[:500]
            normalized["observacoes"] = texto or None

    return normalized


def apply_upsert_aulas_alunos(session, aula_id, aluno_id, payload):
    dados = normalize_aulas_alunos_payload(payload)

    avaliacao = None

    for obj in session.new:
        if isinstance(obj, AulaAluno) and obj.aula_id == aula_id and obj.aluno_id == aluno_id:
            avaliacao = obj
            break

    if not avaliacao:
        for obj in session.identity_map.values():
            if isinstance(obj, AulaAluno) and obj.aula_id == aula_id and obj.aluno_id == aluno_id:
                avaliacao = obj
                break

    if not avaliacao:
        with session.no_autoflush:
            avaliacao = session.query(AulaAluno).filter_by(aula_id=aula_id, aluno_id=aluno_id).first()

    if not avaliacao:
        avaliacao = AulaAluno(aula_id=aula_id, aluno_id=aluno_id)
        session.add(avaliacao)

    for campo, valor in dados.items():
        if campo in AULAS_ALUNOS_FIELDS:
            setattr(avaliacao, campo, valor)

    return avaliacao


def parse_aulas_alunos_tsv(raw_text, aula_id_default=None):
    rows = []
    if not raw_text:
        return rows

    lines = [line for line in str(raw_text).splitlines() if line.strip()]
    if not lines:
        return rows

    headers = [h.strip() for h in lines[0].split("\t")]
    has_header = "aluno_id" in headers
    data_lines = lines[1:] if has_header else lines

    expected = [
        "aula_id",
        "aluno_id",
        "atraso",
        "faltas",
        "responsabilidade",
        "comportamento",
        "participacao",
        "trabalho_autonomo",
        "portatil_material",
        "atividade",
        "falta_disciplinar",
    ]
    allowed = set(expected + ["observacoes"])

    for idx, line in enumerate(data_lines, start=1):
        raw_parts = line.split("\t")
        if has_header:
            record = {}
            for col_idx, raw_header in enumerate(headers):
                header = (raw_header or "").strip()
                if header not in allowed:
                    continue
                value = raw_parts[col_idx] if col_idx < len(raw_parts) else ""
                record[header] = value.strip()
        else:
            parts = [p.strip() for p in raw_parts]
            if len(parts) < len(expected):
                raise ValueError(f"Linha TSV invalida (campos insuficientes) na linha {idx}.")
            record = dict(zip(expected, parts[: len(expected)]))
            if len(raw_parts) > len(expected):
                record["observacoes"] = "\t".join(raw_parts[len(expected) :]).strip()

        aula_id_raw = record.get("aula_id") or aula_id_default
        if aula_id_raw in (None, ""):
            raise ValueError(f"Linha TSV invalida (aula_id em falta) na linha {idx}.")
        aluno_id_raw = record.get("aluno_id")
        if aluno_id_raw in (None, ""):
            raise ValueError(f"Linha TSV invalida (aluno_id em falta) na linha {idx}.")

        aula_id = int(aula_id_raw)
        aluno_id = int(aluno_id_raw)
        payload = normalize_aulas_alunos_payload(record)
        payload["client_ts"] = datetime.utcnow().isoformat(timespec="seconds")

        rows.append({"aula_id": aula_id, "aluno_id": aluno_id, "payload": payload})

    return rows


def _dt_periodo_range(dt_turma, periodo):
    ano = dt_turma.ano_letivo if dt_turma else None
    if not ano:
        return None, None
    if periodo == "semestre1":
        return ano.data_inicio_ano, ano.data_fim_semestre1
    if periodo == "semestre2":
        return ano.data_inicio_semestre2, ano.data_fim_ano
    if periodo == "anual":
        return ano.data_inicio_ano, ano.data_fim_ano
    return None, None


def _default_nome_curto(nome):
    partes = [p for p in (nome or "").strip().split() if p]
    if not partes:
        return ""
    if len(partes) == 1:
        return partes[0][:10]
    iniciais = "".join(p[0].upper() for p in partes[:4] if p)
    return iniciais or partes[0][:10]


def _clean_query_params(data):
    clean = {}
    for k, v in (data or {}).items():
        if v is None:
            continue
        s = str(v).strip()
        if not s:
            continue
        clean[str(k)] = s
    return clean


def _safe_next_url(next_url, fallback):
    if not next_url:
        return fallback
    parsed = urlparse(next_url)
    if parsed.scheme or parsed.netloc:
        return fallback
    if not next_url.startswith("/") or next_url.startswith("//"):
        return fallback
    return next_url


def redirect_com_filtros(endpoint, **kwargs):
    params = request.args.to_dict(flat=True)
    if not params:
        raw_qs = request.form.get("_qs")
        if raw_qs:
            params = dict(parse_qsl(raw_qs, keep_blank_values=False))
    params = _clean_query_params(params)
    params.update(_clean_query_params(kwargs))
    return redirect(url_for(endpoint, **params))


def _dt_filtros_to_qs(filtros):
    qs = {
        "periodo": filtros.get("periodo") or "",
        "data_inicio": filtros["data_inicio"].isoformat() if filtros.get("data_inicio") else "",
        "data_fim": filtros["data_fim"].isoformat() if filtros.get("data_fim") else "",
        "disciplina_id": str(filtros.get("disciplina_id") or ""),
        "aluno_id": str(filtros.get("aluno_id") or ""),
    }
    return _clean_query_params(qs)


def _total_previsto_ui(sumarios_txt, tempos_sem_aula):
    sumarios_limpos = [s.strip() for s in (sumarios_txt or "").split(",") if s.strip()]
    base = len(sumarios_limpos) if sumarios_limpos else 1
    if tempos_sem_aula:
        try:
            base = max(base, int(tempos_sem_aula))
        except (TypeError, ValueError):
            pass
    return max(base, 1)


def _primeiro_nome(nome):
    partes = [p for p in (nome or "").strip().split() if p]
    return partes[0] if partes else None


def _normalizar_nome_curto(nome, nome_curto_raw):
    nome_curto = (nome_curto_raw or "").strip()
    if nome_curto.lower() in {"none", "null"}:
        nome_curto = ""
    if not nome_curto:
        nome_curto = _primeiro_nome(nome) or ""
    return nome_curto or None


def _normalizar_texto_opcional(valor):
    if valor is None:
        return None
    texto = str(valor).strip()
    if texto.lower() in {"none", "null"}:
        return ""
    return texto


def _parse_backup_date_arg(valor, campo):
    txt = (valor or "").strip()
    if not txt:
        return None
    try:
        return date.fromisoformat(txt)
    except ValueError as exc:
        raise ValueError(f"Data invalida para '{campo}'. Usa AAAA-MM-DD.") from exc


BACKUP_INTERVALOS_VALIDOS = {"ano", "s1", "s2", "custom"}


def _resolver_intervalo_export(ano_letivo, intervalo, desde_str, ate_str):
    intervalo_norm = (intervalo or "custom").strip().lower()
    if intervalo_norm not in BACKUP_INTERVALOS_VALIDOS:
        raise ValueError("Intervalo invalido. Usa: ano, s1, s2 ou custom.")

    if intervalo_norm == "ano":
        if not ano_letivo:
            raise ValueError("Seleciona um ano letivo para usar o intervalo escolhido.")
        if not ano_letivo.data_inicio_ano or not ano_letivo.data_fim_ano:
            raise ValueError("O ano letivo selecionado nao tem datas de inicio/fim do ano configuradas.")
        return ano_letivo.data_inicio_ano, ano_letivo.data_fim_ano

    if intervalo_norm == "s1":
        if not ano_letivo:
            raise ValueError("Seleciona um ano letivo para usar o intervalo escolhido.")
        if not ano_letivo.data_inicio_ano or not ano_letivo.data_fim_semestre1:
            raise ValueError("O ano letivo selecionado nao tem as datas necessarias para o 1. semestre.")
        return ano_letivo.data_inicio_ano, ano_letivo.data_fim_semestre1

    if intervalo_norm == "s2":
        if not ano_letivo:
            raise ValueError("Seleciona um ano letivo para usar o intervalo escolhido.")
        if not ano_letivo.data_inicio_semestre2:
            raise ValueError("O ano letivo selecionado nao tem data de inicio do 2. semestre.")
        if not ano_letivo.data_fim_ano:
            raise ValueError("O ano letivo selecionado nao tem data de fim do ano configurada.")
        return ano_letivo.data_inicio_semestre2, ano_letivo.data_fim_ano

    desde = _parse_backup_date_arg(desde_str, "desde")
    ate = _parse_backup_date_arg(ate_str, "ate")

    if ano_letivo:
        if desde is None:
            if not ano_letivo.data_inicio_ano:
                raise ValueError("O ano letivo selecionado nao tem data de inicio do ano configurada.")
            desde = ano_letivo.data_inicio_ano
        if ate is None:
            if not ano_letivo.data_fim_ano:
                raise ValueError("O ano letivo selecionado nao tem data de fim do ano configurada.")
            ate = ano_letivo.data_fim_ano

    return desde, ate


def _validar_intervalo_dentro_ano_letivo(ano_letivo, desde, ate):
    if not ano_letivo:
        return

    inicio = ano_letivo.data_inicio_ano
    fim = ano_letivo.data_fim_ano

    if inicio and desde and desde < inicio:
        raise ValueError(
            f"Intervalo invalido: 'desde' ({desde.isoformat()}) fora do ano letivo "
            f"({inicio.isoformat()} a {fim.isoformat() if fim else '...'})."
        )
    if fim and ate and ate > fim:
        raise ValueError(
            f"Intervalo invalido: 'ate' ({ate.isoformat()}) fora do ano letivo "
            f"({inicio.isoformat() if inicio else '...'} a {fim.isoformat()})."
        )


def _serialize_backup_value(valor):
    if isinstance(valor, datetime):
        return valor.isoformat()
    if isinstance(valor, (date, dt_time)):
        return valor.isoformat()
    if isinstance(valor, uuid.UUID):
        return str(valor)
    return valor


def _model_row_to_dict(row):
    return {
        col.name: _serialize_backup_value(getattr(row, col.name))
        for col in row.__table__.columns
    }


def _apply_date_range(query, column, desde=None, ate=None):
    if desde is not None:
        query = query.filter(column >= desde)
    if ate is not None:
        query = query.filter(column <= ate)
    return query


def _iter_query_in_batches(query, model, batch_size=1000):
    base_query = query.order_by(None)
    pk_col = getattr(model, "id", None)

    if pk_col is None:
        for row in base_query.yield_per(batch_size):
            yield row
        return

    last_id = None
    while True:
        paged_query = base_query
        if last_id is not None:
            paged_query = paged_query.filter(pk_col > last_id)
        rows = paged_query.order_by(pk_col.asc()).limit(batch_size).all()
        if not rows:
            break
        for row in rows:
            yield row
        last_id = rows[-1].id
        if len(rows) < batch_size:
            break


def _build_backup_ndjson_specs(turma=None, desde=None, ate=None):
    if turma is not None:
        ano_id = turma.ano_letivo_id

        q_anos = AnoLetivo.query.filter(AnoLetivo.id == ano_id)
        q_disciplinas = (
            Disciplina.query.join(TurmaDisciplina, TurmaDisciplina.disciplina_id == Disciplina.id)
            .filter(TurmaDisciplina.turma_id == turma.id)
            .distinct()
        )
        q_livros = (
            Livro.query.join(LivroTurma, LivroTurma.livro_id == Livro.id)
            .filter(LivroTurma.turma_id == turma.id)
            .distinct()
        )
        q_turmas = Turma.query.filter(Turma.id == turma.id)
        q_livros_turmas = LivroTurma.query.filter(LivroTurma.turma_id == turma.id)
        q_turmas_disciplinas = TurmaDisciplina.query.filter(TurmaDisciplina.turma_id == turma.id)
        q_alunos = Aluno.query.filter(Aluno.turma_id == turma.id)
        q_horarios = Horario.query.filter(Horario.turma_id == turma.id)
        q_modulos = Modulo.query.filter(Modulo.turma_id == turma.id)
        q_periodos = Periodo.query.filter(Periodo.turma_id == turma.id)

        q_calendario = CalendarioAula.query.filter(CalendarioAula.turma_id == turma.id)
        q_calendario = _apply_date_range(q_calendario, CalendarioAula.data, desde, ate)

        q_avaliacoes = (
            AulaAluno.query.join(CalendarioAula, AulaAluno.aula_id == CalendarioAula.id)
            .filter(CalendarioAula.turma_id == turma.id)
        )
        q_avaliacoes = _apply_date_range(q_avaliacoes, CalendarioAula.data, desde, ate)

        q_historico = (
            AulaSumarioHistorico.query.join(
                CalendarioAula,
                AulaSumarioHistorico.calendario_aula_id == CalendarioAula.id,
            )
            .filter(CalendarioAula.turma_id == turma.id)
        )
        q_historico = _apply_date_range(q_historico, CalendarioAula.data, desde, ate)

        q_dt_turmas = DTTurma.query.filter(DTTurma.turma_id == turma.id)
        q_dt_alunos = (
            DTAluno.query.join(DTTurma, DTAluno.dt_turma_id == DTTurma.id)
            .filter(DTTurma.turma_id == turma.id)
        )
        q_dt_justificacoes = (
            DTJustificacao.query.join(DTAluno, DTJustificacao.dt_aluno_id == DTAluno.id)
            .join(DTTurma, DTAluno.dt_turma_id == DTTurma.id)
            .filter(DTTurma.turma_id == turma.id)
        )
        q_dt_justificacoes = _apply_date_range(
            q_dt_justificacoes, DTJustificacao.data, desde, ate
        )
        q_dt_motivos = (
            DTMotivoDia.query.join(DTTurma, DTMotivoDia.dt_turma_id == DTTurma.id)
            .filter(DTTurma.turma_id == turma.id)
        )
        q_dt_motivos = _apply_date_range(q_dt_motivos, DTMotivoDia.data, desde, ate)

        q_dt_ocorrencias = (
            DTOcorrencia.query.join(DTTurma, DTOcorrencia.dt_turma_id == DTTurma.id)
            .filter(DTTurma.turma_id == turma.id)
        )
        q_dt_ocorrencias = _apply_date_range(q_dt_ocorrencias, DTOcorrencia.data, desde, ate)

        q_dt_ocorrencia_alunos = (
            DTOcorrenciaAluno.query.join(
                DTOcorrencia,
                DTOcorrenciaAluno.dt_ocorrencia_id == DTOcorrencia.id,
            )
            .join(DTTurma, DTOcorrencia.dt_turma_id == DTTurma.id)
            .filter(DTTurma.turma_id == turma.id)
        )
        q_dt_ocorrencia_alunos = _apply_date_range(
            q_dt_ocorrencia_alunos, DTOcorrencia.data, desde, ate
        )

        q_dt_disciplinas = (
            DTDisciplina.query.join(DTOcorrencia, DTOcorrencia.dt_disciplina_id == DTDisciplina.id)
            .join(DTTurma, DTOcorrencia.dt_turma_id == DTTurma.id)
            .filter(DTTurma.turma_id == turma.id)
            .distinct()
        )
        q_dt_disciplinas = _apply_date_range(q_dt_disciplinas, DTOcorrencia.data, desde, ate)

        q_trabalhos = Trabalho.query.filter(Trabalho.turma_id == turma.id)
        q_trabalhos = _apply_date_range(q_trabalhos, Trabalho.data_limite, desde, ate)

        q_grupos_turma = GrupoTurma.query.filter(GrupoTurma.turma_id == turma.id)
        q_grupo_turma_membros = (
            GrupoTurmaMembro.query.join(
                GrupoTurma, GrupoTurmaMembro.grupo_turma_id == GrupoTurma.id
            )
            .filter(GrupoTurma.turma_id == turma.id)
        )

        q_trabalho_grupos = (
            TrabalhoGrupo.query.join(Trabalho, TrabalhoGrupo.trabalho_id == Trabalho.id)
            .filter(Trabalho.turma_id == turma.id)
        )
        q_trabalho_grupos = _apply_date_range(q_trabalho_grupos, Trabalho.data_limite, desde, ate)

        q_trabalho_grupo_membros = (
            TrabalhoGrupoMembro.query.join(
                TrabalhoGrupo,
                TrabalhoGrupoMembro.trabalho_grupo_id == TrabalhoGrupo.id,
            )
            .join(Trabalho, TrabalhoGrupo.trabalho_id == Trabalho.id)
            .filter(Trabalho.turma_id == turma.id)
        )
        q_trabalho_grupo_membros = _apply_date_range(
            q_trabalho_grupo_membros, Trabalho.data_limite, desde, ate
        )

        q_entregas = (
            Entrega.query.join(Trabalho, Entrega.trabalho_id == Trabalho.id)
            .filter(Trabalho.turma_id == turma.id)
        )
        q_entregas = _apply_date_range(q_entregas, Entrega.data_entrega, desde, ate)

        q_parametros = (
            ParametroDefinicao.query.join(
                Trabalho, ParametroDefinicao.trabalho_id == Trabalho.id
            )
            .filter(Trabalho.turma_id == turma.id)
        )
        q_parametros = _apply_date_range(q_parametros, Trabalho.data_limite, desde, ate)

        q_entrega_parametros = (
            EntregaParametro.query.join(Entrega, EntregaParametro.entrega_id == Entrega.id)
            .join(Trabalho, Entrega.trabalho_id == Trabalho.id)
            .filter(Trabalho.turma_id == turma.id)
        )
        q_entrega_parametros = _apply_date_range(
            q_entrega_parametros, Trabalho.data_limite, desde, ate
        )

        q_feriados = Feriado.query.filter(Feriado.ano_letivo_id == ano_id)
        q_feriados = _apply_date_range(q_feriados, Feriado.data, desde, ate)

        q_interrupcoes = InterrupcaoLetiva.query.filter(
            InterrupcaoLetiva.ano_letivo_id == ano_id
        )
        if desde is not None:
            q_interrupcoes = q_interrupcoes.filter(
                or_(
                    InterrupcaoLetiva.data_fim.is_(None),
                    InterrupcaoLetiva.data_fim >= desde,
                )
            )
        if ate is not None:
            q_interrupcoes = q_interrupcoes.filter(
                or_(
                    InterrupcaoLetiva.data_inicio.is_(None),
                    InterrupcaoLetiva.data_inicio <= ate,
                )
            )

    else:
        q_anos = AnoLetivo.query
        q_disciplinas = Disciplina.query
        q_livros = Livro.query
        q_turmas = Turma.query
        q_livros_turmas = LivroTurma.query
        q_turmas_disciplinas = TurmaDisciplina.query
        q_alunos = Aluno.query
        q_horarios = Horario.query
        q_modulos = Modulo.query
        q_periodos = Periodo.query

        q_calendario = _apply_date_range(CalendarioAula.query, CalendarioAula.data, desde, ate)

        q_avaliacoes = AulaAluno.query
        if desde is not None or ate is not None:
            q_avaliacoes = q_avaliacoes.join(
                CalendarioAula, AulaAluno.aula_id == CalendarioAula.id
            )
            q_avaliacoes = _apply_date_range(q_avaliacoes, CalendarioAula.data, desde, ate)

        q_historico = AulaSumarioHistorico.query
        if desde is not None or ate is not None:
            q_historico = q_historico.join(
                CalendarioAula,
                AulaSumarioHistorico.calendario_aula_id == CalendarioAula.id,
            )
            q_historico = _apply_date_range(q_historico, CalendarioAula.data, desde, ate)

        q_dt_turmas = DTTurma.query
        q_dt_alunos = DTAluno.query
        q_dt_justificacoes = _apply_date_range(
            DTJustificacao.query, DTJustificacao.data, desde, ate
        )
        q_dt_motivos = _apply_date_range(DTMotivoDia.query, DTMotivoDia.data, desde, ate)
        q_dt_disciplinas = DTDisciplina.query
        q_dt_ocorrencias = _apply_date_range(DTOcorrencia.query, DTOcorrencia.data, desde, ate)

        q_dt_ocorrencia_alunos = DTOcorrenciaAluno.query
        if desde is not None or ate is not None:
            q_dt_ocorrencia_alunos = q_dt_ocorrencia_alunos.join(
                DTOcorrencia,
                DTOcorrenciaAluno.dt_ocorrencia_id == DTOcorrencia.id,
            )
            q_dt_ocorrencia_alunos = _apply_date_range(
                q_dt_ocorrencia_alunos, DTOcorrencia.data, desde, ate
            )

        q_trabalhos = _apply_date_range(Trabalho.query, Trabalho.data_limite, desde, ate)
        q_grupos_turma = GrupoTurma.query
        q_grupo_turma_membros = GrupoTurmaMembro.query

        q_trabalho_grupos = TrabalhoGrupo.query
        if desde is not None or ate is not None:
            q_trabalho_grupos = q_trabalho_grupos.join(
                Trabalho, TrabalhoGrupo.trabalho_id == Trabalho.id
            )
            q_trabalho_grupos = _apply_date_range(
                q_trabalho_grupos, Trabalho.data_limite, desde, ate
            )

        q_trabalho_grupo_membros = TrabalhoGrupoMembro.query
        if desde is not None or ate is not None:
            q_trabalho_grupo_membros = q_trabalho_grupo_membros.join(
                TrabalhoGrupo,
                TrabalhoGrupoMembro.trabalho_grupo_id == TrabalhoGrupo.id,
            ).join(Trabalho, TrabalhoGrupo.trabalho_id == Trabalho.id)
            q_trabalho_grupo_membros = _apply_date_range(
                q_trabalho_grupo_membros, Trabalho.data_limite, desde, ate
            )

        q_entregas = _apply_date_range(Entrega.query, Entrega.data_entrega, desde, ate)
        q_parametros = ParametroDefinicao.query
        q_entrega_parametros = EntregaParametro.query
        q_feriados = _apply_date_range(Feriado.query, Feriado.data, desde, ate)

        q_interrupcoes = InterrupcaoLetiva.query
        if desde is not None:
            q_interrupcoes = q_interrupcoes.filter(
                or_(
                    InterrupcaoLetiva.data_fim.is_(None),
                    InterrupcaoLetiva.data_fim >= desde,
                )
            )
        if ate is not None:
            q_interrupcoes = q_interrupcoes.filter(
                or_(
                    InterrupcaoLetiva.data_inicio.is_(None),
                    InterrupcaoLetiva.data_inicio <= ate,
                )
            )

    return [
        ("anos_letivos", AnoLetivo, q_anos),
        ("disciplinas", Disciplina, q_disciplinas),
        ("livros", Livro, q_livros),
        ("turmas", Turma, q_turmas),
        ("livros_turmas", LivroTurma, q_livros_turmas),
        ("turmas_disciplinas", TurmaDisciplina, q_turmas_disciplinas),
        ("alunos", Aluno, q_alunos),
        ("horarios", Horario, q_horarios),
        ("modulos", Modulo, q_modulos),
        ("periodos", Periodo, q_periodos),
        ("calendario_aulas", CalendarioAula, q_calendario),
        ("aulas_alunos", AulaAluno, q_avaliacoes),
        ("sumario_historico", AulaSumarioHistorico, q_historico),
        ("dt_turmas", DTTurma, q_dt_turmas),
        ("dt_alunos", DTAluno, q_dt_alunos),
        ("dt_justificacoes", DTJustificacao, q_dt_justificacoes),
        ("dt_motivos_dia", DTMotivoDia, q_dt_motivos),
        ("dt_disciplinas", DTDisciplina, q_dt_disciplinas),
        ("dt_ocorrencias", DTOcorrencia, q_dt_ocorrencias),
        ("dt_ocorrencia_alunos", DTOcorrenciaAluno, q_dt_ocorrencia_alunos),
        ("trabalhos", Trabalho, q_trabalhos),
        ("grupos_turma", GrupoTurma, q_grupos_turma),
        ("grupo_turma_membros", GrupoTurmaMembro, q_grupo_turma_membros),
        ("trabalho_grupos", TrabalhoGrupo, q_trabalho_grupos),
        ("trabalho_grupo_membros", TrabalhoGrupoMembro, q_trabalho_grupo_membros),
        ("entregas", Entrega, q_entregas),
        ("parametro_definicoes", ParametroDefinicao, q_parametros),
        ("entrega_parametros", EntregaParametro, q_entrega_parametros),
        ("feriados", Feriado, q_feriados),
        ("interrupcoes_letivas", InterrupcaoLetiva, q_interrupcoes),
    ]


BACKUP_NDJSON_TYPE_MODEL = {
    "anos_letivos": AnoLetivo,
    "disciplinas": Disciplina,
    "livros": Livro,
    "turmas": Turma,
    "livros_turmas": LivroTurma,
    "turmas_disciplinas": TurmaDisciplina,
    "alunos": Aluno,
    "horarios": Horario,
    "modulos": Modulo,
    "periodos": Periodo,
    "calendario_aulas": CalendarioAula,
    "aulas_alunos": AulaAluno,
    "sumario_historico": AulaSumarioHistorico,
    "dt_turmas": DTTurma,
    "dt_alunos": DTAluno,
    "dt_justificacoes": DTJustificacao,
    "dt_motivos_dia": DTMotivoDia,
    "dt_disciplinas": DTDisciplina,
    "dt_ocorrencias": DTOcorrencia,
    "dt_ocorrencia_alunos": DTOcorrenciaAluno,
    "trabalhos": Trabalho,
    "grupos_turma": GrupoTurma,
    "grupo_turma_membros": GrupoTurmaMembro,
    "trabalho_grupos": TrabalhoGrupo,
    "trabalho_grupo_membros": TrabalhoGrupoMembro,
    "entregas": Entrega,
    "parametro_definicoes": ParametroDefinicao,
    "entrega_parametros": EntregaParametro,
    "feriados": Feriado,
    "interrupcoes_letivas": InterrupcaoLetiva,
}


def _parse_iso_datetime_value(raw, field_name):
    txt = (raw or "").strip()
    if not txt:
        return None
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(txt)
    except ValueError as exc:
        raise ValueError(f"Valor invalido para '{field_name}': {raw}") from exc


def _parse_iso_date_value(raw, field_name):
    txt = (raw or "").strip()
    if not txt:
        return None
    try:
        return date.fromisoformat(txt)
    except ValueError as exc:
        raise ValueError(f"Valor invalido para '{field_name}': {raw}") from exc


def _parse_iso_time_value(raw, field_name):
    txt = (raw or "").strip()
    if not txt:
        return None
    try:
        return dt_time.fromisoformat(txt)
    except ValueError as exc:
        raise ValueError(f"Valor invalido para '{field_name}': {raw}") from exc


def _coerce_backup_column_value(column, value):
    if value is None:
        return None

    if isinstance(column.type, SADateTime):
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return _parse_iso_datetime_value(value, column.name)
        raise ValueError(f"Valor invalido para '{column.name}': {value!r}")

    if isinstance(column.type, SADate):
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            return _parse_iso_date_value(value, column.name)
        raise ValueError(f"Valor invalido para '{column.name}': {value!r}")

    if isinstance(column.type, SATime):
        if isinstance(value, dt_time):
            return value
        if isinstance(value, str):
            return _parse_iso_time_value(value, column.name)
        raise ValueError(f"Valor invalido para '{column.name}': {value!r}")

    if isinstance(column.type, SABoolean):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            txt = value.strip().lower()
            if txt in {"1", "true", "t", "yes", "sim"}:
                return True
            if txt in {"0", "false", "f", "no", "nao", "não"}:
                return False
        if isinstance(value, (int, float)):
            return bool(value)
        raise ValueError(f"Valor invalido para '{column.name}': {value!r}")

    if isinstance(column.type, SAInteger):
        if value == "":
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            return int(value)
        return int(value)

    if isinstance(column.type, (SAFloat, SANumeric)):
        if value == "":
            return None
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            return float(value)
        return float(value)

    return value


def _coerce_backup_row(model, payload):
    if not isinstance(payload, dict):
        raise ValueError(f"Payload invalido para '{model.__tablename__}'.")

    values = {}
    for column in model.__table__.columns:
        if column.name not in payload:
            continue
        try:
            values[column.name] = _coerce_backup_column_value(column, payload[column.name])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Campo invalido '{column.name}' em '{model.__tablename__}': {exc}"
            ) from exc

    if model is CalendarioAula and "previsao" in values:
        previsao = values.get("previsao")
        if isinstance(previsao, str) and previsao.strip().lower() in {"none", "null"}:
            values["previsao"] = ""

    if not values:
        raise ValueError(f"Sem campos validos para '{model.__tablename__}'.")
    return values


def _insert_backup_row(model, values):
    table = model.__table__
    bind = db.session.get_bind()
    dialect_name = bind.dialect.name if bind is not None else ""

    if dialect_name == "postgresql":
        stmt = pg_insert(table).values(**values).on_conflict_do_nothing()
    elif dialect_name == "sqlite":
        stmt = sqlite_insert(table).values(**values).on_conflict_do_nothing()
    else:
        stmt = table.insert().values(**values)

    result = db.session.execute(stmt)
    return max(result.rowcount or 0, 0)


def importar_backup_ndjson_gz(file_storage):
    if file_storage is None:
        raise ValueError("Ficheiro em falta.")

    filename = (file_storage.filename or "").lower()
    if filename and not filename.endswith(".ndjson.gz"):
        raise ValueError("Formato invalido. Usa um ficheiro .ndjson.gz.")

    try:
        file_storage.stream.seek(0)
    except (AttributeError, OSError):
        pass

    started_perf = time.perf_counter()
    parsed_lines = 0
    imported_lines = 0
    imported_by_type = defaultdict(int)
    inserted_by_type = defaultdict(int)

    try:
        with gzip.GzipFile(fileobj=file_storage.stream, mode="rb") as gz_handle:
            for line_number, raw_line in enumerate(gz_handle, start=1):
                parsed_lines = line_number

                try:
                    line = raw_line.decode("utf-8").strip()
                except UnicodeDecodeError as exc:
                    raise ValueError(f"Linha {line_number}: conteudo nao e UTF-8 valido.") from exc

                if not line:
                    continue

                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Linha {line_number}: JSON invalido.") from exc

                if not isinstance(obj, dict):
                    raise ValueError(f"Linha {line_number}: objeto NDJSON invalido.")

                row_type = obj.get("type")
                if row_type == "meta":
                    continue

                model = BACKUP_NDJSON_TYPE_MODEL.get(row_type)
                if model is None:
                    raise ValueError(f"Linha {line_number}: tipo desconhecido '{row_type}'.")

                values = _coerce_backup_row(model, obj.get("data"))
                inserted = _insert_backup_row(model, values)

                imported_lines += 1
                imported_by_type[row_type] += 1
                inserted_by_type[row_type] += inserted
    except OSError as exc:
        raise ValueError(f"Ficheiro gzip invalido ou corrompido: {exc}") from exc

    elapsed = time.perf_counter() - started_perf
    current_app.logger.info(
        "Importacao NDJSON concluida | linhas=%s | importadas=%s | inseridas=%s | duracao_s=%.3f",
        parsed_lines,
        imported_lines,
        sum(inserted_by_type.values()),
        elapsed,
    )

    return {
        "linhas_lidas": parsed_lines,
        "linhas_importadas": imported_lines,
        "linhas_inseridas": int(sum(inserted_by_type.values())),
        "por_tipo_importadas": dict(imported_by_type),
        "por_tipo_inseridas": dict(inserted_by_type),
    }


def _build_backup_ndjson_response(
    scope,
    specs,
    desde=None,
    ate=None,
    turma=None,
    intervalo="custom",
    ano_letivo=None,
):
    started_at = datetime.now(timezone.utc).isoformat()
    started_perf = time.perf_counter()
    scope_label = "turma" if scope == "turma" else "completo"

    timestamp = datetime.now().strftime("%Y%m%d-%H%M")
    if turma:
        filename = f"backup-turma-{_slugify_filename(turma.nome, str(turma.id))}-{timestamp}.ndjson.gz"
    else:
        filename = f"backup-completo-{timestamp}.ndjson.gz"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".ndjson.gz")
    tmp_path = tmp.name
    tmp.close()

    counts = defaultdict(int)
    raw_bytes = 0
    total_records = 0

    def _to_line(payload):
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"

    meta_payload = {
        "type": "meta",
        "data": {
            "format": "ndjson",
            "compression": "gzip",
            "version": 1,
            "generated_at": started_at,
            "scope": scope_label,
            "turma_id": turma.id if turma else None,
            "turma_nome": turma.nome if turma else None,
            "ano_letivo_id": ano_letivo.id if ano_letivo else None,
            "ano_letivo_nome": ano_letivo.nome if ano_letivo else None,
            "intervalo": (intervalo or "custom"),
            "desde": desde.isoformat() if desde else None,
            "ate": ate.isoformat() if ate else None,
        },
    }

    try:
        with gzip.open(tmp_path, "wb", compresslevel=6) as gz_handle:
            line = _to_line(meta_payload)
            line_bytes = line.encode("utf-8")
            gz_handle.write(line_bytes)
            raw_bytes += len(line_bytes)
            total_records += 1

            for type_name, model, query in specs:
                for row in _iter_query_in_batches(query, model, batch_size=1000):
                    payload = {"type": type_name, "data": _model_row_to_dict(row)}
                    line = _to_line(payload)
                    line_bytes = line.encode("utf-8")
                    gz_handle.write(line_bytes)
                    counts[type_name] += 1
                    raw_bytes += len(line_bytes)
                    total_records += 1

        with open(tmp_path, "rb") as tmp_check:
            magic = tmp_check.read(2)
        if magic != b"\x1f\x8b":
            raise ValueError("Backup gerado sem cabecalho gzip valido.")
    except Exception:
        current_app.logger.exception(
            "Falha durante exportacao de backup NDJSON | scope=%s | turma_id=%s",
            scope_label,
            turma.id if turma else None,
        )
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise

    gz_bytes = 0
    try:
        gz_bytes = os.path.getsize(tmp_path)
    except OSError:
        gz_bytes = 0

    elapsed = time.perf_counter() - started_perf
    current_app.logger.info(
        (
            "Backup NDJSON concluido | scope=%s | turma_id=%s | desde=%s | ate=%s | "
            "duracao_s=%.3f | registos=%s | turmas=%s | aulas=%s | alunos=%s | "
            "ocorrencias=%s | trabalhos=%s | bytes_raw=%s | bytes_gzip=%s"
        ),
        scope_label,
        turma.id if turma else None,
        desde.isoformat() if desde else None,
        ate.isoformat() if ate else None,
        elapsed,
        total_records,
        counts.get("turmas", 0),
        counts.get("calendario_aulas", 0),
        counts.get("alunos", 0),
        counts.get("dt_ocorrencias", 0),
        counts.get("trabalhos", 0),
        raw_bytes,
        gz_bytes,
    )

    response = send_file(
        tmp_path,
        as_attachment=True,
        download_name=filename,
        mimetype="application/gzip",
        max_age=0,
    )
    response.headers.pop("Content-Encoding", None)
    response.headers["Cache-Control"] = "no-store, no-transform"
    response.headers["X-Accel-Buffering"] = "no"

    @response.call_on_close
    def _cleanup_tmp_backup():
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    return response


def _mapear_alunos_em_falta(aulas):
    ids = [a.id for a in aulas if getattr(a, "id", None)]
    if not ids:
        return {}

    resultados = defaultdict(list)
    faltas = (
        AulaAluno.query.options(joinedload(AulaAluno.aluno))
        .join(Aluno)
        .filter(AulaAluno.aula_id.in_(ids), AulaAluno.faltas > 0)
        .order_by(Aluno.numero.is_(None), Aluno.numero, Aluno.nome)
        .all()
    )

    for avaliacao in faltas:
        aluno = avaliacao.aluno
        numero = aluno.numero if aluno else None
        etiqueta_num = (
            f"{numero:02d}"
            if numero is not None
            else (
                str(aluno.processo).zfill(2)
                if aluno and aluno.processo is not None
                else "--"
            )
        )
        nome = aluno.nome if aluno else ""
        faltas_dia = avaliacao.faltas or 0
        resultados[avaliacao.aula_id].append(
            f"{etiqueta_num} {nome} ({faltas_dia})".strip()
        )

    return resultados


def _mapear_aulas_com_avaliacao(aulas):
    ids = [a.id for a in aulas if getattr(a, "id", None)]
    if not ids:
        return set()

    return {
        aula_id
        for (aula_id,) in (
            db.session.query(AulaAluno.aula_id)
            .filter(AulaAluno.aula_id.in_(ids))
            .distinct()
            .all()
        )
    }


def _formatar_data_hora(valor):
    if not valor:
        return None
    if isinstance(valor, str):
        try:
            valor = datetime.fromisoformat(valor)
        except ValueError:
            return None
    if isinstance(valor, (int, float)):
        valor = datetime.fromtimestamp(valor)
    if isinstance(valor, datetime):
        return valor.strftime("%d/%m/%Y %H:%M")
    return None


def _formatar_tamanho_bytes(valor):
    if valor is None:
        return None
    try:
        tamanho = float(valor)
    except (TypeError, ValueError):
        return None
    unidades = ["B", "KB", "MB", "GB", "TB"]
    for unidade in unidades:
        if tamanho < 1024 or unidade == unidades[-1]:
            if unidade == "B":
                return f"{int(tamanho)} {unidade}"
            return f"{tamanho:.1f} {unidade}"
        tamanho /= 1024
    return None


def _mapear_sumarios_anteriores(aulas):
    if not aulas:
        return {}

    turma_ids = {
        aula.turma_id for aula in aulas if getattr(aula, "turma_id", None) is not None
    }
    if turma_ids:
        universo = (
            CalendarioAula.query.filter(
                CalendarioAula.apagado == False,  # noqa: E712
                CalendarioAula.turma_id.in_(turma_ids),
            )
            .order_by(CalendarioAula.data.asc(), CalendarioAula.id.asc())
            .all()
        )
    else:
        universo = list(aulas)

    grupos = defaultdict(list)
    for aula in universo:
        chave = (aula.turma_id, aula.modulo_id)
        grupos[chave].append(aula)

    anteriores: dict[int, str | None] = {}

    for lista in grupos.values():
        lista.sort(
            key=lambda a: (
                a.data or date.min,
                a.total_geral or 0,
                a.numero_modulo or 0,
                a.id or 0,
            )
        )

        ultimo_sumario: str | None = None
        for aula in lista:
            anteriores[aula.id] = ultimo_sumario
            if aula.sumario and aula.sumario.strip():
                ultimo_sumario = aula.sumario.strip()

    return anteriores


def _extrair_filtros_outras_datas(origem):
    tipo_bruto = origem.get("tipo") or origem.get("tipo_filtro")
    tipo_filtro = tipo_bruto if tipo_bruto in TIPOS_ESPECIAIS else None

    turma_raw = origem.get("turma_id") or origem.get("turma_filtro")
    try:
        turma_filtro = int(turma_raw) if turma_raw else None
    except (TypeError, ValueError):
        turma_filtro = None

    data_inicio = _parse_date_form(origem.get("data_inicio"))
    data_fim = _parse_date_form(origem.get("data_fim"))

    return tipo_filtro, turma_filtro, data_inicio, data_fim


def _filtros_outras_datas_redirect(tipo, turma_id, data_inicio, data_fim):
    filtros = {}
    if tipo:
        filtros["tipo"] = tipo
    if turma_id:
        filtros["turma_id"] = turma_id
    if data_inicio:
        filtros["data_inicio"] = data_inicio.isoformat()
    if data_fim:
        filtros["data_fim"] = data_fim.isoformat()
    return filtros


def criar_periodo_modular_para_modulo(modulo: Modulo) -> Periodo:
    """
    Cria (ou devolve) um período do tipo 'modular' associado a um módulo
    de turma profissional.
    """
    turma = modulo.turma
    ano = turma.ano_letivo

    p_existente = (
        Periodo.query
        .filter_by(turma_id=turma.id, tipo="modular", modulo_id=modulo.id)
        .first()
    )
    if p_existente:
        return p_existente

    # Datas podem ser:
    # - estimadas com base no ano letivo
    # - ou deixadas iguais ao ano e depois afinadas manualmente via interface.
    data_inicio = ano.data_inicio_ano
    data_fim = ano.data_fim_ano

    p = Periodo(
        turma_id=turma.id,
        nome=f"Módulo: {modulo.nome}",
        tipo="modular",
        data_inicio=data_inicio,
        data_fim=data_fim,
        modulo_id=modulo.id,
    )
    db.session.add(p)
    db.session.commit()
    return p



def _safe_db_target_from_uri(uri):
    try:
        parsed = urlsplit(uri or "")
        host = parsed.hostname or "-"
        port = parsed.port or "-"
        db_name = (parsed.path or "/").lstrip("/") or "-"
        return {"host": host, "port": port, "db": db_name}
    except Exception:
        return {"host": "-", "port": "-", "db": "-"}


def _configure_logging(app):
    os.makedirs(os.path.join(app.root_path, "logs"), exist_ok=True)
    log_file = os.path.join(app.root_path, "logs", "app.log")

    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")

    file_handler_exists = any(
        isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", None) == log_file
        for h in app.logger.handlers
    )
    if not file_handler_exists:
        file_handler = RotatingFileHandler(log_file, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)

    if app.debug:
        console_exists = any(isinstance(h, logging.StreamHandler) for h in app.logger.handlers)
        if not console_exists:
            console = logging.StreamHandler()
            console.setFormatter(formatter)
            console.setLevel(logging.DEBUG)
            app.logger.addHandler(console)

    app.logger.setLevel(logging.DEBUG if app.debug else logging.INFO)



def _bind_label(connection):
    try:
        backend = connection.engine.url.get_backend_name()
    except Exception:
        backend = "unknown"
    if backend == "postgresql":
        return "postgres"
    if backend == "sqlite":
        return "sqlite"
    return backend


def _setup_tx_logging(app):
    if getattr(_setup_tx_logging, "_registered", False):
        return

    @event.listens_for(Engine, "begin")
    def _tx_begin(conn):
        app.logger.info("TX BEGIN | bind=%s", _bind_label(conn))

    @event.listens_for(Engine, "commit")
    def _tx_commit(conn):
        app.logger.info("TX COMMIT | bind=%s", _bind_label(conn))

    @event.listens_for(Engine, "rollback")
    def _tx_rollback(conn):
        app.logger.info("TX ROLLBACK | bind=%s", _bind_label(conn))

    _setup_tx_logging._registered = True

def _setup_dual_db_engines(app):
    offline_db_path = resolve_offline_db_path(app.instance_path)
    local_uri = f"sqlite:///{offline_db_path}"
    remote_uri = app.config.get("SQLALCHEMY_DATABASE_URI")

    app.extensions["engine_local"] = create_engine(local_uri, future=True)
    app.extensions["session_local_factory"] = sessionmaker(bind=app.extensions["engine_local"], future=True)
    app.extensions["offline_db_path"] = offline_db_path

    app.extensions["engine_remote"] = None
    app.extensions["session_remote_factory"] = None
    app.extensions["remote_available"] = False
    app.extensions["startup_offline"] = False

    if (app.config.get("APP_DB_MODE") or "sqlite").lower() == "postgres" and remote_uri:
        try:
            app.extensions["engine_remote"] = create_engine(
                remote_uri,
                future=True,
                pool_pre_ping=True,
                pool_recycle=1800,
                connect_args={
                    "connect_timeout": int(app.config.get("SUPABASE_CONNECT_TIMEOUT", 5) or 5),
                    "options": f"-c statement_timeout={int(app.config.get('SUPABASE_STATEMENT_TIMEOUT_MS', 15000) or 15000)}",
                },
            )
            app.extensions["session_remote_factory"] = sessionmaker(bind=app.extensions["engine_remote"], future=True)
            with app.extensions["engine_remote"].connect() as conn:
                conn.execute(text("SELECT 1"))
            app.extensions["remote_available"] = True
        except Exception as exc:
            app.extensions["remote_available"] = False
            app.extensions["startup_offline"] = True
            target = _safe_db_target_from_uri(remote_uri)
            app.logger.warning(
                "Remote DB unavailable at startup; entering offline mode "
                "(host=%s port=%s db=%s): %s",
                target["host"],
                target["port"],
                target["db"],
                exc,
            )



def _remote_healthcheck(app, use_cache=True):
    now = time.time()
    cache = app.extensions.setdefault("remote_health_cache", {"ts": 0.0, "ok": False, "error": "", "latency_ms": None})
    ttl = float(app.config.get("REMOTE_HEALTHCHECK_TTL_SECONDS", 5) or 5)

    if use_cache and (now - cache.get("ts", 0.0)) < ttl:
        return dict(cache)

    started = time.perf_counter()
    if (app.config.get("APP_DB_MODE") or "sqlite").lower() != "postgres":
        cache.update(
            {
                "ts": now,
                "ok": True,
                "error": "",
                "latency_ms": None,
                "local_mode": True,
            }
        )
        return dict(cache)

    if not _has_remote_backend(app):
        cache.update(
            {
                "ts": now,
                "ok": False,
                "error": "Remote engine not configured",
                "latency_ms": None,
            }
        )
        return dict(cache)

    try:
        db.session.execute(text("SELECT 1"))
        latency = int((time.perf_counter() - started) * 1000)
        cache.update({"ts": now, "ok": True, "error": "", "latency_ms": latency})
    except Exception as exc:
        db.session.rollback()
        latency = int((time.perf_counter() - started) * 1000)
        cache.update({"ts": now, "ok": False, "error": str(exc), "latency_ms": latency})
        app.extensions["remote_available"] = False
        target = _safe_db_target_from_uri(app.config.get("SQLALCHEMY_DATABASE_URI") or "")
        app.logger.exception(
            "Healthcheck remoto falhou (host=%s port=%s db=%s): %s",
            target["host"],
            target["port"],
            target["db"],
            exc,
        )
    return dict(cache)


def _is_remote_online(app, use_cache=True):
    return bool(_remote_healthcheck(app, use_cache=use_cache).get("ok"))


def _has_remote_backend(app):
    return (
        (app.config.get("APP_DB_MODE") or "sqlite").lower() == "postgres"
        and ("engine_remote" in app.extensions)
        and (app.extensions.get("engine_remote") is not None)
    )

def create_app():
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)

    os.makedirs(app.instance_path, exist_ok=True)
    _configure_logging(app)
    _setup_tx_logging(app)
    _setup_dual_db_engines(app)
    app.extensions["is_remote_online"] = lambda use_cache=True: _is_remote_online(app, use_cache=use_cache)
    backup_override = os.environ.get("DB_BACKUP_DIR")
    if backup_override and os.path.isabs(backup_override):
        app.config["BACKUP_DIR"] = backup_override
    else:
        app.config["BACKUP_DIR"] = os.path.join(app.instance_path, "backups")

    db.init_app(app)
    Migrate(app, db)
    app.register_blueprint(offline_bp)
    app.register_blueprint(ev2_bp)
    app.register_blueprint(ev2_config_bp)

    @app.get("/health")
    def healthcheck():
        return jsonify(
            {
                "status": "ok",
                "supabase_url": app.config.get("SUPABASE_URL") or os.environ.get("SUPABASE_URL"),
            }
        )

    @app.before_request
    def _set_connectivity_state():
        g.db_mode = (app.config.get("APP_DB_MODE") or "sqlite").lower()

        if g.db_mode == "sqlite":
            app.extensions["remote_available"] = False
            app.extensions["startup_offline"] = False
            g.has_remote = False
            g.is_online = True
            g.is_offline = False
            g.connection_status_label = "SQLite (local)"
            return

        g.has_remote = _has_remote_backend(app)
        if not g.has_remote:
            app.extensions["remote_available"] = False
            app.extensions["startup_offline"] = True
            g.is_online = False
            g.is_offline = True
            g.connection_status_label = "Offline (sem Supabase)"
        else:
            g.is_online = _is_remote_online(app, use_cache=True)
            app.extensions["remote_available"] = bool(g.is_online)
            app.extensions["startup_offline"] = not g.is_online
            g.is_offline = not g.is_online
            g.connection_status_label = "Online (Supabase)" if g.is_online else "Offline (sem Supabase)"

        if g.is_offline and not (
            request.path.startswith("/offline")
            or request.path.startswith("/static/")
            or request.path == "/health"
        ):
            return redirect(url_for("offline.dashboard"))

    @app.cli.group("offline")
    def offline_cli():
        """Comandos de preparação/sincronização offline."""

    @offline_cli.command("snapshot")
    def offline_snapshot_command():
        result = refresh_snapshot_from_remote()
        if result.get("ok"):
            print(
                f"Snapshot offline atualizado: {result['turmas']} turma(s), "
                f"{result['alunos']} aluno(s), {result['aulas']} aula(s)."
            )
        else:
            raise SystemExit(result.get("error") or "Falha ao atualizar snapshot offline.")

    @offline_cli.command("healthcheck")
    def offline_healthcheck_command():
        target = _safe_db_target_from_uri(app.config.get("SQLALCHEMY_DATABASE_URI") or "")
        if (app.config.get("APP_DB_MODE") or "sqlite").lower() != "postgres":
            raise SystemExit("APP_DB_MODE não está em postgres.")
        try:
            db.session.execute(text("SELECT 1"))
            print(json.dumps({"ok": True, **target}, ensure_ascii=False))
        except Exception as exc:
            app.logger.exception(
                "Healthcheck CLI falhou (host=%s port=%s db=%s): %s",
                target["host"],
                target["port"],
                target["db"],
                exc,
            )
            raise SystemExit(json.dumps({"ok": False, "error": str(exc), **target}, ensure_ascii=False))

    @app.cli.command("supabase-fix-sequences")
    def supabase_fix_sequences_command():
        """Alinha sequences das tabelas do schema public com coluna id."""
        if (app.config.get("APP_DB_MODE") or "sqlite").lower() != "postgres":
            raise SystemExit("APP_DB_MODE não está em postgres.")

        sql_path = os.path.join(app.root_path, "db", "supabase_fix_sequences.sql")
        if not os.path.exists(sql_path):
            raise SystemExit(f"Ficheiro SQL não encontrado: {sql_path}")

        try:
            sql_script = open(sql_path, "r", encoding="utf-8").read()
            db.session.execute(text(sql_script))
            db.session.commit()

            result = fix_sequences_remote(app, schema_name="public")
            for table_name in result.get("tables", []):
                app.logger.info("FIX SEQ OK | table=%s", table_name)
            print(json.dumps({"ok": True, "tables": result.get("tables", [])}, ensure_ascii=False))
        except Exception as exc:
            db.session.rollback()
            app.logger.exception("Falha no comando supabase-fix-sequences: %s", exc)
            raise SystemExit(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))

    @app.get("/health/db")
    @app.get("/api/health/db")
    def api_health_db():
        target = _safe_db_target_from_uri(app.config.get("SQLALCHEMY_DATABASE_URI") or "")
        info = _remote_healthcheck(app, use_cache=False)
        if (app.config.get("APP_DB_MODE") or "sqlite").lower() != "postgres":
            return jsonify({"ok": False, "error": "APP_DB_MODE não está em postgres.", **target}), 400
        if info.get("ok"):
            return jsonify({"ok": True, "latency_ms": info.get("latency_ms"), **target})
        return jsonify({"ok": False, "error": info.get("error"), "latency_ms": info.get("latency_ms"), **target}), 503

    @app.get("/health/db-write")
    def api_health_db_write():
        target = _safe_db_target_from_uri(app.config.get("SQLALCHEMY_DATABASE_URI") or "")
        if (app.config.get("APP_DB_MODE") or "sqlite").lower() != "postgres":
            return jsonify({"ok": False, "error": "APP_DB_MODE não está em postgres.", **target}), 400

        try:
            db.session.execute(text("SELECT 1"))
            db.session.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS __write_probe (
                      id BIGSERIAL PRIMARY KEY,
                      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
            )
            db.session.execute(text("INSERT INTO __write_probe DEFAULT VALUES"))
            rows = db.session.execute(text("SELECT COUNT(*) FROM __write_probe")).scalar() or 0
            db.session.commit()
            return jsonify({"ok": True, "rows": int(rows), **target})
        except Exception as exc:
            db.session.rollback()
            app.logger.exception("Healthcheck DB-WRITE falhou (host=%s port=%s db=%s): %s", target["host"], target["port"], target["db"], exc)
            return jsonify({"ok": False, "error": str(exc), **target}), 500

    config_store = ConfigStore(app.instance_path, logger=app.logger)

    def get_db_sessions(mode="auto"):
        remote_session = db.session
        local_factory = app.extensions.get("session_local_factory")

        resolved_mode = mode
        if mode == "auto":
            resolved_mode = "remote" if _is_remote_online(app, use_cache=True) else "local"

        if resolved_mode == "remote" and (app.config.get("APP_DB_MODE") or "sqlite").lower() != "postgres":
            app.logger.warning("Pedido de sessão remota em APP_DB_MODE=%s", app.config.get("APP_DB_MODE"))

        return {
            "mode": resolved_mode,
            "remote": remote_session,
            "local_factory": local_factory,
        }

    def _default_csv_dir():
        return app.config.get("CSV_EXPORT_DIR") or os.path.join(app.root_path, "exports")

    def _default_backup_json_dir():
        return app.config.get("BACKUP_JSON_DIR") or os.path.join(
            app.root_path, "exports", "backups"
        )

    def _load_export_options():
        options = {
            "csv_dest_dir": _default_csv_dir(),
            "backup_json_dir": _default_backup_json_dir(),
        }

        stored = config_store.read_json("export_config.json", default={}) or {}
        if stored.get("csv_dest_dir"):
            options["csv_dest_dir"] = stored["csv_dest_dir"]
        if stored.get("backup_json_dir"):
            options["backup_json_dir"] = stored["backup_json_dir"]

        app.config["CSV_EXPORT_DIR"] = options["csv_dest_dir"] or _default_csv_dir()
        app.config["BACKUP_JSON_DIR"] = options.get("backup_json_dir") or _default_backup_json_dir()
        return options

    def _save_export_options(csv_dest_dir=None, backup_json_dir=None):
        options = _load_export_options()
        if csv_dest_dir is not None:
            options["csv_dest_dir"] = csv_dest_dir
        if backup_json_dir is not None:
            options["backup_json_dir"] = backup_json_dir

        if not config_store.write_json("export_config.json", options):
            app.logger.warning("Não foi possível gravar opções de exportação.")

        app.config["CSV_EXPORT_DIR"] = options["csv_dest_dir"] or _default_csv_dir()
        app.config["BACKUP_JSON_DIR"] = options.get("backup_json_dir") or _default_backup_json_dir()

    _load_export_options()

    def _load_last_save():
        payload = config_store.read_json("app_state.json", default={}) or {}
        return payload.get("last_save")

    def _save_last_save(timestamp):
        if not config_store.write_json("app_state.json", {"last_save": timestamp}):
            app.logger.warning("Não foi possível gravar a data do último registo.")

    def _ler_timestamp_git():
        try:
            result = subprocess.run(
                ["git", "log", "-1", "--format=%ct"],
                cwd=app.root_path,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                ts = (result.stdout or "").strip()
                if ts.isdigit():
                    return int(ts)
        except OSError:
            return None
        return None

    app.config["APP_VERSION_TIMESTAMP"] = _formatar_data_hora(_ler_timestamp_git())

    @event.listens_for(db.session, "before_commit")
    def _before_commit(session):
        session.info["has_changes"] = bool(
            session.new or session.dirty or session.deleted
        )

    @event.listens_for(db.session, "after_commit")
    def _after_commit(session):
        if not session.info.pop("has_changes", False):
            return
        _save_last_save(datetime.now().isoformat(timespec="seconds"))
        if app.config.get("BACKUP_ON_COMMIT", True) and not _running_flask_cli():
            _agendar_backup_change()

    @app.context_processor
    def inject_footer_info():
        has_remote = _has_remote_backend(app)
        if has_remote:
            health = _remote_healthcheck(app, use_cache=True)
            is_offline = not bool(health.get("ok"))
            connection_status_label = "Online (Supabase)" if not is_offline else "Offline (sem Supabase)"
        else:
            health = {"ok": True, "error": "", "latency_ms": None, "local_mode": True}
            is_offline = False
            connection_status_label = "SQLite (local)"

        return {
            "app_version_timestamp": app.config.get("APP_VERSION_TIMESTAMP"),
            "last_save_timestamp": _formatar_data_hora(_load_last_save()),
            "is_offline": is_offline,
            "db_mode": (app.config.get("APP_DB_MODE") or "sqlite").lower(),
            "has_remote": has_remote,
            "connection_status_label": connection_status_label,
            "remote_health": health,
        }

    # Garantir que colunas recentes existem em instalações que ainda não
    # aplicaram as migrações correspondentes (evita erros em bases de dados
    # antigas carregadas a partir de ficheiro).
    def _ensure_trabalhos_tables():
        required = {
            "trabalhos",
            "trabalho_grupos",
            "trabalho_grupo_membros",
            "entregas",
            "parametro_definicoes",
            "entrega_parametros",
            "grupos_turma",
            "grupo_turma_membros",
        }
        insp = inspect(db.engine)
        existing = set(insp.get_table_names())
        missing = sorted(required - existing)
        if not missing:
            return

        app.logger.warning("Tabelas de trabalhos em falta (%s). A criar automaticamente.", ", ".join(missing))
        db.metadata.create_all(
            bind=db.engine,
            tables=[
                Trabalho.__table__,
                TrabalhoGrupo.__table__,
                TrabalhoGrupoMembro.__table__,
                Entrega.__table__,
                ParametroDefinicao.__table__,
                EntregaParametro.__table__,
                GrupoTurma.__table__,
                GrupoTurmaMembro.__table__,
            ],
            checkfirst=True,
        )
        db.session.commit()
        app.logger.info("Schema de trabalhos garantido com sucesso.")

        insp = inspect(db.engine)
        trabalho_cols = {c["name"] for c in insp.get_columns("trabalhos")} if "trabalhos" in insp.get_table_names() else set()
        if "data_limite" not in trabalho_cols:
            db.session.execute(text("ALTER TABLE trabalhos ADD COLUMN data_limite DATE"))
            db.session.commit()

        entrega_cols = {c["name"] for c in insp.get_columns("entregas")} if "entregas" in insp.get_table_names() else set()
        if "data_entrega" not in entrega_cols:
            db.session.execute(text("ALTER TABLE entregas ADD COLUMN data_entrega DATE"))
        if "observacoes" not in entrega_cols:
            db.session.execute(text("ALTER TABLE entregas ADD COLUMN observacoes TEXT"))
        db.session.commit()

    def _ensure_columns():
        insp = inspect(db.engine)
        tabelas = set(insp.get_table_names())
        if "calendario_aulas" in tabelas:
            colunas_calendario = {col["name"] for col in insp.get_columns("calendario_aulas")}
            if "observacoes_html" not in colunas_calendario:
                db.session.execute(
                    text("ALTER TABLE calendario_aulas ADD COLUMN observacoes_html TEXT")
                )
                db.session.commit()

        if "dt_justificacao_textos" not in tabelas:
            db.metadata.create_all(bind=db.engine, tables=[DTJustificacaoTexto.__table__], checkfirst=True)
            db.session.commit()
            insp = inspect(db.engine)
            tabelas = set(insp.get_table_names())

        if db.engine.dialect.name != "sqlite":
            return

        # Instalações limpas: criar todas as tabelas definidas nos modelos para
        # que a aplicação arranque mesmo sem ter corrido as migrações.
        if not tabelas:
            db.create_all()
            db.session.commit()
            insp = inspect(db.engine)
            tabelas = set(insp.get_table_names())

        if "alunos" not in tabelas:
            db.session.execute(
                text(
                    """
                    CREATE TABLE alunos (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        turma_id INTEGER NOT NULL,
                        processo VARCHAR(50),
                        numero INTEGER,
                        nome VARCHAR(255) NOT NULL,
                        nome_curto VARCHAR(100),
                        nee TEXT,
                        observacoes TEXT,
                        FOREIGN KEY(turma_id) REFERENCES turmas(id)
                    )
                    """
                )
            )
            db.session.commit()

        if "aulas_alunos" not in tabelas:
            db.session.execute(
                text(
                    """
                    CREATE TABLE aulas_alunos (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        aula_id INTEGER NOT NULL,
                        aluno_id INTEGER NOT NULL,
                        atraso BOOLEAN NOT NULL DEFAULT 0,
                        faltas INTEGER NOT NULL DEFAULT 0,
                        responsabilidade INTEGER DEFAULT 3,
                        comportamento INTEGER DEFAULT 3,
                        participacao INTEGER DEFAULT 3,
                        trabalho_autonomo INTEGER DEFAULT 3,
                        portatil_material INTEGER DEFAULT 3,
                        atividade INTEGER DEFAULT 3,
                        falta_disciplinar INTEGER NOT NULL DEFAULT 0,
                        observacoes TEXT,
                        CONSTRAINT fk_aula FOREIGN KEY(aula_id) REFERENCES calendario_aulas(id),
                        CONSTRAINT fk_aluno FOREIGN KEY(aluno_id) REFERENCES alunos(id),
                        CONSTRAINT uq_aula_aluno UNIQUE(aula_id, aluno_id)
                    )
                    """
                )
            )
            db.session.commit()

        if "dt_turmas" not in tabelas:
            db.session.execute(
                text(
                    """
                    CREATE TABLE dt_turmas (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        turma_id INTEGER NOT NULL,
                        ano_letivo_id INTEGER NOT NULL,
                        observacoes TEXT,
                        CONSTRAINT fk_dt_turma FOREIGN KEY(turma_id) REFERENCES turmas(id),
                        CONSTRAINT fk_dt_ano FOREIGN KEY(ano_letivo_id) REFERENCES anos_letivos(id),
                        CONSTRAINT uq_dt_turma_ano UNIQUE(turma_id, ano_letivo_id)
                    )
                    """
                )
            )
            db.session.commit()

        if "dt_alunos" not in tabelas:
            db.session.execute(
                text(
                    """
                    CREATE TABLE dt_alunos (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        dt_turma_id INTEGER NOT NULL,
                        aluno_id INTEGER NOT NULL,
                        CONSTRAINT fk_dt_turma FOREIGN KEY(dt_turma_id) REFERENCES dt_turmas(id),
                        CONSTRAINT fk_dt_aluno FOREIGN KEY(aluno_id) REFERENCES alunos(id)
                    )
                    """
                )
            )
            db.session.commit()

        if "dt_justificacoes" not in tabelas:
            db.session.execute(
                text(
                    """
                    CREATE TABLE dt_justificacoes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        dt_aluno_id INTEGER NOT NULL,
                        data DATE NOT NULL,
                        tipo VARCHAR(20) NOT NULL DEFAULT 'falta',
                        motivo TEXT,
                        CONSTRAINT fk_dt_aluno FOREIGN KEY(dt_aluno_id) REFERENCES dt_alunos(id)
                    )
                    """
                )
            )
            db.session.commit()

        dt_alunos_cols = {col["name"] for col in insp.get_columns("dt_alunos")}
        if "aluno_id" not in dt_alunos_cols:
            db.session.execute(
                text("ALTER TABLE dt_alunos ADD COLUMN aluno_id INTEGER")
            )
            db.session.commit()

        if "dt_motivos_dia" not in tabelas:
            db.session.execute(
                text(
                    """
                    CREATE TABLE dt_motivos_dia (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        dt_turma_id INTEGER NOT NULL,
                        data DATE NOT NULL,
                        motivo TEXT,
                        CONSTRAINT fk_dt_motivo_turma FOREIGN KEY(dt_turma_id) REFERENCES dt_turmas(id),
                        CONSTRAINT uq_dt_motivo_dia UNIQUE(dt_turma_id, data)
                    )
                    """
                )
            )
            db.session.commit()

        if "dt_disciplinas" not in tabelas:
            db.session.execute(
                text(
                    """
                    CREATE TABLE dt_disciplinas (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        nome VARCHAR(120) NOT NULL,
                        nome_curto VARCHAR(40),
                        professor_nome VARCHAR(120),
                        ativa BOOLEAN NOT NULL DEFAULT 1,
                        CONSTRAINT uq_dt_disciplinas_nome UNIQUE(nome)
                    )
                    """
                )
            )
            db.session.commit()
        else:
            dt_disciplinas_cols = {col["name"] for col in insp.get_columns("dt_disciplinas")}
            if "nome_curto" not in dt_disciplinas_cols:
                db.session.execute(text("ALTER TABLE dt_disciplinas ADD COLUMN nome_curto VARCHAR(40)"))
                db.session.commit()
            if "professor_nome" not in dt_disciplinas_cols:
                db.session.execute(text("ALTER TABLE dt_disciplinas ADD COLUMN professor_nome VARCHAR(120)"))
                db.session.commit()

        if "dt_ocorrencias" not in tabelas:
            db.session.execute(
                text(
                    """
                    CREATE TABLE dt_ocorrencias (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        dt_turma_id INTEGER NOT NULL,
                        data DATE NOT NULL,
                        hora_inicio TIME,
                        hora_fim TIME,
                        num_tempos INTEGER,
                        dt_disciplina_id INTEGER NOT NULL,
                        observacoes TEXT,
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL,
                        CONSTRAINT fk_dt_ocorrencia_turma FOREIGN KEY(dt_turma_id) REFERENCES dt_turmas(id),
                        CONSTRAINT fk_dt_ocorrencia_disciplina FOREIGN KEY(dt_disciplina_id) REFERENCES dt_disciplinas(id)
                    )
                    """
                )
            )
            db.session.execute(text("CREATE INDEX ix_dt_ocorrencias_dt_turma_id ON dt_ocorrencias (dt_turma_id)"))
            db.session.execute(text("CREATE INDEX ix_dt_ocorrencias_data ON dt_ocorrencias (data)"))
            db.session.execute(text("CREATE INDEX ix_dt_ocorrencias_dt_disciplina_id ON dt_ocorrencias (dt_disciplina_id)"))
            db.session.commit()

        if "dt_ocorrencia_alunos" not in tabelas:
            db.session.execute(
                text(
                    """
                    CREATE TABLE dt_ocorrencia_alunos (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        dt_ocorrencia_id INTEGER NOT NULL,
                        dt_aluno_id INTEGER NOT NULL,
                        CONSTRAINT fk_dt_ocorr_aluno_ocorr FOREIGN KEY(dt_ocorrencia_id) REFERENCES dt_ocorrencias(id),
                        CONSTRAINT fk_dt_ocorr_aluno_aluno FOREIGN KEY(dt_aluno_id) REFERENCES dt_alunos(id),
                        CONSTRAINT uq_dt_ocorrencia_aluno UNIQUE(dt_ocorrencia_id, dt_aluno_id)
                    )
                    """
                )
            )
            db.session.execute(text("CREATE INDEX ix_dt_ocorrencia_alunos_ocorrencia ON dt_ocorrencia_alunos (dt_ocorrencia_id)"))
            db.session.execute(text("CREATE INDEX ix_dt_ocorrencia_alunos_aluno ON dt_ocorrencia_alunos (dt_aluno_id)"))
            db.session.commit()

        if "sumario_historico" not in tabelas:
            db.session.execute(
                text(
                    """
                    CREATE TABLE sumario_historico (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        calendario_aula_id INTEGER NOT NULL,
                        created_at DATETIME NOT NULL,
                        acao VARCHAR(50) NOT NULL,
                        sumario_anterior TEXT,
                        sumario_novo TEXT,
                        autor VARCHAR(100) NOT NULL DEFAULT 'local',
                        FOREIGN KEY(calendario_aula_id) REFERENCES calendario_aulas(id)
                    )
                    """
                )
            )
            db.session.execute(
                text(
                    """
                    CREATE INDEX ix_sumario_hist_aula_data
                    ON sumario_historico (calendario_aula_id, created_at)
                    """
                )
            )
            db.session.commit()

        colunas = {col["name"] for col in insp.get_columns("calendario_aulas")}

        if "tempos_sem_aula" not in colunas:
            db.session.execute(
                text(
                    "ALTER TABLE calendario_aulas ADD COLUMN tempos_sem_aula INTEGER DEFAULT 0"
                )
            )
            db.session.commit()

        if "previsao" not in colunas:
            db.session.execute(
                text("ALTER TABLE calendario_aulas ADD COLUMN previsao TEXT")
            )
            db.session.commit()

        if "atividade" not in colunas:
            db.session.execute(
                text(
                    "ALTER TABLE calendario_aulas ADD COLUMN atividade BOOLEAN NOT NULL DEFAULT 0"
                )
            )
            db.session.commit()

        colunas = {col["name"] for col in insp.get_columns("calendario_aulas")}
        if "atividade_nome" not in colunas:
            db.session.execute(
                text("ALTER TABLE calendario_aulas ADD COLUMN atividade_nome TEXT")
            )
            db.session.commit()
        colunas_alunos = {col["name"] for col in insp.get_columns("aulas_alunos")}
        if "falta_disciplinar" not in colunas_alunos:
            db.session.execute(
                text(
                    "ALTER TABLE aulas_alunos ADD COLUMN falta_disciplinar INTEGER NOT NULL DEFAULT 0"
                )
            )
            db.session.commit()
        if "observacoes" not in colunas_alunos:
            db.session.execute(
                text("ALTER TABLE aulas_alunos ADD COLUMN observacoes TEXT")
            )
            db.session.commit()

        turmas_cols = {col["name"] for col in insp.get_columns("turmas")}
        if "periodo_tipo" not in turmas_cols:
            db.session.execute(
                text(
                    "ALTER TABLE turmas ADD COLUMN periodo_tipo VARCHAR(20) NOT NULL DEFAULT 'anual'"
                )
            )
            db.session.commit()

        turmas_cols = {col["name"] for col in insp.get_columns("turmas")}
        for nome_coluna in [
            "tempo_segunda",
            "tempo_terca",
            "tempo_quarta",
            "tempo_quinta",
            "tempo_sexta",
        ]:
            if nome_coluna not in turmas_cols:
                db.session.execute(
                    text(f"ALTER TABLE turmas ADD COLUMN {nome_coluna} INTEGER")
                )
                db.session.commit()

        turmas_cols = {col["name"] for col in insp.get_columns("turmas")}
        if "letiva" not in turmas_cols:
            db.session.execute(
                text("ALTER TABLE turmas ADD COLUMN letiva BOOLEAN NOT NULL DEFAULT 1")
            )
            db.session.commit()

        try:
            script = ScriptDirectory("migrations")
            head_revision = script.get_current_head()
        except Exception:
            head_revision = None

        if head_revision:
            tabelas = set(insp.get_table_names())
            if "alembic_version" not in tabelas:
                db.session.execute(
                    text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
                )
                db.session.execute(
                    text("INSERT INTO alembic_version (version_num) VALUES (:vnum)"),
                    {"vnum": head_revision},
                )
                db.session.commit()
            else:
                versao_atual = db.session.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar()
                if versao_atual != head_revision:
                    db.session.execute(text("DELETE FROM alembic_version"))
                    db.session.execute(
                        text("INSERT INTO alembic_version (version_num) VALUES (:vnum)"),
                        {"vnum": head_revision},
                    )
                    db.session.commit()

    def _get_db_path():
        db_path = app.config.get("DB_PATH")
        if db_path:
            return os.path.abspath(db_path)
        if has_app_context():
            try:
                engine_path = db.engine.url.database
                if engine_path:
                    return os.path.abspath(engine_path)
            except Exception:
                pass
        uri = app.config.get("SQLALCHEMY_DATABASE_URI")
        if not uri or not uri.startswith("sqlite:///"):
            return None
        return os.path.abspath(uri.replace("sqlite:///", "", 1))

    def _parse_backup_filename(filename):
        pattern = re.compile(
            r"^(?P<ts>\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})__(?P<host>[^/\\\\]+?)(?P<manual>_manual)?\\.db$"
        )
        match = pattern.match(filename)
        if not match:
            return None
        try:
            timestamp = datetime.strptime(match.group("ts"), "%Y-%m-%d_%H-%M-%S")
        except ValueError:
            return None
        return {
            "filename": filename,
            "timestamp": timestamp,
            "hostname": match.group("host"),
            "is_manual": bool(match.group("manual")),
        }

    def _rotate_backups(backup_dir, keep):
        if keep is None:
            return
        try:
            keep = int(keep)
        except (TypeError, ValueError):
            return
        if keep <= 0:
            return
        entries = []
        try:
            for filename in os.listdir(backup_dir):
                parsed = _parse_backup_filename(filename)
                if not parsed:
                    continue
                parsed["path"] = os.path.join(backup_dir, filename)
                entries.append(parsed)
        except FileNotFoundError:
            return
        entries.sort(key=lambda item: item["timestamp"], reverse=True)
        for entry in entries[keep:]:
            try:
                os.remove(entry["path"])
            except OSError:
                app.logger.warning(
                    "Não foi possível remover backup antigo: %s", entry["path"]
                )

    def _validar_backup_sqlite(path):
        try:
            with sqlite3.connect(path) as conn:
                cursor = conn.execute("PRAGMA integrity_check;")
                resultado = cursor.fetchone()
                if not resultado or resultado[0] != "ok":
                    return False, "Falha no integrity_check."
        except sqlite3.Error as exc:
            return False, f"Erro SQLite ao validar: {exc}"
        return True, None

    def _safe_remove(path, tentativas=6, atraso=0.2):
        ultimo_erro = None
        for tentativa in range(tentativas):
            try:
                if os.path.exists(path):
                    os.remove(path)
                return True, None
            except OSError as exc:
                app.logger.warning("Falha ao remover %s (tentativa %s): %s", path, tentativa + 1, exc)
                gc.collect()
                time.sleep(atraso * (2 ** tentativa))
                ultimo_erro = exc
        return False, ultimo_erro

    def _safe_replace(src, dst, tentativas=6, atraso=0.2):
        ultimo_erro = None
        for tentativa in range(tentativas):
            try:
                os.replace(src, dst)
                return True, None
            except OSError as exc:
                app.logger.warning(
                    "Falha ao substituir %s -> %s (tentativa %s): %s",
                    src,
                    dst,
                    tentativa + 1,
                    exc,
                )
                gc.collect()
                time.sleep(atraso * (2 ** tentativa))
                ultimo_erro = exc
        return False, ultimo_erro

    def _running_flask_cli():
        """Deteta comandos utilitários de CLI (não inclui `flask run`)."""
        args = " ".join(sys.argv).lower()
        return any(
            token in args
            for token in ["flask db", "flask shell", "flask routes", "migrate", "upgrade", "current"]
        )

    def _should_run_startup_jobs():
        if _running_flask_cli():
            return False
        if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
            return True
        if os.environ.get("FLASK_DEBUG") in {"1", "true", "True"}:
            return False
        return True

    def get_db_mode():
        mode = (app.config.get("APP_DB_MODE") or "sqlite").strip().lower()
        return "postgres" if mode == "postgres" else "sqlite"

    def _sqlite_backups_enabled():
        return get_db_mode() == "sqlite"

    def _get_machine_name():
        return os.environ.get("COMPUTERNAME") or platform.node() or socket.gethostname()

    def _obter_lock_backup(backup_dir):
        lock_path = os.path.join(backup_dir, ".backup.lock")
        try:
            handle = open(lock_path, "x", encoding="utf-8")
            handle.write(f"{os.getpid()}\n{socket.gethostname()}\n{datetime.now().isoformat()}\n")
            handle.flush()
            return lock_path, handle, None
        except FileExistsError as exc:
            return lock_path, None, "Backup já em execução."
        except OSError as exc:
            return lock_path, None, f"Não foi possível criar lock: {exc}"

    def _libertar_lock_backup(lock_path, handle):
        try:
            if handle:
                handle.close()
            if lock_path and os.path.exists(lock_path):
                _safe_remove(lock_path)
        except OSError:
            app.logger.warning("Não foi possível remover lock de backup: %s", lock_path)

    def _registar_backup_status(payload):
        if not config_store.write_json("backup_status.json", payload):
            app.logger.warning("Não foi possível gravar estado do backup.")

    def _carregar_backup_status():
        return config_store.read_json("backup_status.json", default=None)

    def _carregar_backup_state():
        estado = config_store.read_json(
            "backup_state.json",
            default={
                "last_backup_at": None,
                "pending_changes_count": 0,
                "last_change_at": None,
            },
        )
        if not isinstance(estado, dict):
            return {
            "last_backup_at": None,
            "pending_changes_count": 0,
            "last_change_at": None,
            }
        return estado

    def _guardar_backup_state(payload):
        if not config_store.write_json("backup_state.json", payload):
            app.logger.warning("Não foi possível gravar estado do backup.")

    def _backup_database(reason="manual"):
        if not _sqlite_backups_enabled():
            app.logger.info("Backups SQLite desativados (modo postgres)")
            return {"ok": False, "error": "Backups SQLite desativados (modo postgres)."}

        inicio = time.monotonic()
        backup_dir = app.config.get("BACKUP_DIR")
        db_path = _get_db_path()
        status_payload = {
            "last_backup_at": datetime.now().isoformat(timespec="seconds"),
            "last_backup_ok": False,
            "last_backup_filename": None,
            "last_backup_error": None,
            "hostname": socket.gethostname(),
            "db_path": db_path,
            "backup_dir": backup_dir,
            "tmp_path": None,
            "method": None,
            "duration_s": None,
        }

        if not backup_dir or not db_path:
            status_payload["last_backup_error"] = "Configuração de backup em falta."
            status_payload["duration_s"] = round(time.monotonic() - inicio, 3)
            _registar_backup_status(status_payload)
            return {"ok": False, "error": status_payload["last_backup_error"]}

        if not os.path.isfile(db_path):
            status_payload["last_backup_error"] = "Base de dados não encontrada."
            status_payload["duration_s"] = round(time.monotonic() - inicio, 3)
            _registar_backup_status(status_payload)
            return {"ok": False, "error": status_payload["last_backup_error"]}

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        hostname = _get_machine_name() or "HOST"
        manual_suffix = "_manual" if reason == "manual" else ""
        backup_name = f"{timestamp}__{hostname}{manual_suffix}.db"
        destination = os.path.join(backup_dir, backup_name)
        tmp_path = None
        status_payload["tmp_path"] = None
        delays = [0.2, 0.5, 1.0, 2.0, 3.0]

        try:
            os.makedirs(backup_dir, exist_ok=True)
            app.logger.info(
                "Início backup (%s): db=%s | backup_dir=%s | dest=%s | tmp=%s | pid=%s",
                reason,
                db_path,
                backup_dir,
                destination,
                tmp_path,
                os.getpid(),
            )
            lock_path, lock_handle, lock_error = _obter_lock_backup(backup_dir)
            if lock_error:
                status_payload["last_backup_error"] = lock_error
                status_payload["duration_s"] = round(time.monotonic() - inicio, 3)
                _registar_backup_status(status_payload)
                return {"ok": False, "error": lock_error}
            try:
                if not BACKUP_LOCK.acquire(blocking=False):
                    status_payload["last_backup_error"] = "Backup já em execução."
                    status_payload["duration_s"] = round(time.monotonic() - inicio, 3)
                    _registar_backup_status(status_payload)
                    return {"ok": False, "error": status_payload["last_backup_error"]}
                if has_app_context():
                    db.session.remove()
                    if db.session.is_active:
                        db.session.rollback()
                status_payload["method"] = "copy2"
                copia_ok = False
                ultimo_erro = None
                for atraso in delays:
                    try:
                        shutil.copy2(db_path, destination)
                        copia_ok = True
                        break
                    except OSError as exc:
                        ultimo_erro = exc
                        app.logger.warning("Falha ao copiar backup, retry em %.2fs: %s", atraso, exc)
                        time.sleep(atraso)
                if not copia_ok:
                    fallback_dir = os.path.join(tempfile.gettempdir(), "sumarios_backups")
                    os.makedirs(fallback_dir, exist_ok=True)
                    fallback_path = os.path.join(fallback_dir, backup_name)
                    try:
                        shutil.copy2(db_path, fallback_path)
                        destination = fallback_path
                        status_payload["last_backup_filename"] = os.path.basename(fallback_path)
                        app.logger.warning(
                            "Backup gravado em fallback (TEMP): %s", fallback_path
                        )
                        copia_ok = True
                    except OSError as exc:
                        status_payload["last_backup_error"] = f"Não foi possível gravar backup: {exc}"
                        status_payload["duration_s"] = round(time.monotonic() - inicio, 3)
                        _registar_backup_status(status_payload)
                        return {"ok": False, "error": status_payload["last_backup_error"]}
                if not os.path.exists(destination):
                    status_payload["last_backup_error"] = "O ficheiro de backup não foi criado."
                    status_payload["duration_s"] = round(time.monotonic() - inicio, 3)
                    _registar_backup_status(status_payload)
                    return {"ok": False, "error": status_payload["last_backup_error"]}
                if os.path.getsize(destination) <= 0:
                    status_payload["last_backup_error"] = "O ficheiro de backup está vazio."
                    status_payload["duration_s"] = round(time.monotonic() - inicio, 3)
                    _registar_backup_status(status_payload)
                    return {"ok": False, "error": status_payload["last_backup_error"]}
                valido, erro_sqlite = _validar_backup_sqlite(destination)
                if not valido:
                    status_payload["last_backup_error"] = erro_sqlite or "Backup inválido."
                    status_payload["duration_s"] = round(time.monotonic() - inicio, 3)
                    _registar_backup_status(status_payload)
                    return {"ok": False, "error": status_payload["last_backup_error"]}
                _rotate_backups(backup_dir, app.config.get("BACKUP_KEEP", 30))
            finally:
                if BACKUP_LOCK.locked():
                    BACKUP_LOCK.release()
                _libertar_lock_backup(lock_path, lock_handle)
            status_payload["last_backup_ok"] = True
            status_payload["last_backup_filename"] = status_payload["last_backup_filename"] or backup_name
            status_payload["last_backup_error"] = None
            status_payload["duration_s"] = round(time.monotonic() - inicio, 3)
            _registar_backup_status(status_payload)
            app.logger.info(
                "Backup criado (%s): %s | método=%s | db=%s | dest=%s | %.3fs",
                reason,
                status_payload["last_backup_filename"],
                status_payload["method"],
                db_path,
                destination,
                status_payload["duration_s"],
            )
            return {"ok": True, "filename": status_payload["last_backup_filename"]}
        except (OSError, sqlite3.Error) as exc:
            status_payload["last_backup_error"] = str(exc)
            status_payload["duration_s"] = round(time.monotonic() - inicio, 3)
            _registar_backup_status(status_payload)
            app.logger.exception(
                "Não foi possível criar backup da base de dados em %s: %s",
                backup_dir,
                exc,
            )
        except Exception as exc:
            status_payload["last_backup_error"] = str(exc)
            status_payload["duration_s"] = round(time.monotonic() - inicio, 3)
            _registar_backup_status(status_payload)
            app.logger.exception(
                "Falha inesperada ao criar backup em %s: %s",
                backup_dir,
                exc,
            )
        finally:
            pass
        return {"ok": False, "error": "Não foi possível criar backup."}

    def _list_backups():
        backup_dir = app.config.get("BACKUP_DIR")
        entries = []
        if not backup_dir:
            return entries
        try:
            for filename in os.listdir(backup_dir):
                parsed = _parse_backup_filename(filename)
                if not parsed:
                    continue
                path = os.path.join(backup_dir, filename)
                try:
                    size = os.path.getsize(path)
                except OSError:
                    size = None
                entries.append(
                    {
                        **parsed,
                        "size": size,
                        "size_label": _formatar_tamanho_bytes(size),
                    }
                )
        except FileNotFoundError:
            return entries
        entries.sort(key=lambda item: item["timestamp"], reverse=True)
        return entries[:20]

    def _registar_sumario_historico(aula, acao, anterior, novo, autor="local", session=None, ignore_errors=False):
        sess = session or db.session
        try:
            registo = AulaSumarioHistorico(
                calendario_aula_id=aula.id,
                acao=acao,
                sumario_anterior=anterior,
                sumario_novo=novo,
                autor=autor,
            )
            sess.add(registo)
            excessos = (
                sess.query(AulaSumarioHistorico)
                .filter_by(calendario_aula_id=aula.id)
                .order_by(AulaSumarioHistorico.created_at.desc(), AulaSumarioHistorico.id.desc())
                .offset(10)
                .all()
            )
            if excessos:
                for item in excessos:
                    sess.delete(item)
            return registo
        except IntegrityError as exc:
            sess.rollback()
            app.logger.exception(
                "HIST FAIL (ignored) | aula_id=%s | acao=%s | erro=%s",
                getattr(aula, "id", None),
                acao,
                exc,
            )
            if ignore_errors:
                return None
            raise

    def _registar_sumario_historico_isolado(aula_id, acao, anterior, novo, autor="local"):
        session_factory = app.extensions.get("session_remote_factory")
        if session_factory is None:
            bind = db.session.get_bind()
            session_factory = sessionmaker(bind=bind, future=True)

        hist_session = session_factory()
        try:
            aula_hist = hist_session.get(CalendarioAula, int(aula_id))
            if not aula_hist:
                app.logger.warning("HIST FAIL (ignored) | aula_id=%s | motivo=aula_inexistente", aula_id)
                hist_session.rollback()
                return False

            registo = _registar_sumario_historico(
                aula_hist,
                acao,
                anterior,
                novo,
                autor=autor,
                session=hist_session,
                ignore_errors=True,
            )
            if registo is None:
                hist_session.rollback()
                return False

            hist_session.commit()
            app.logger.info("HIST OK | aula_id=%s | acao=%s", aula_id, acao)
            return True
        except Exception as exc:
            hist_session.rollback()
            app.logger.exception("HIST FAIL (ignored) | aula_id=%s | acao=%s | erro=%s", aula_id, acao, exc)
            return False
        finally:
            hist_session.close()

    def _build_payloads_from_form(aula, alunos):
        payloads = []
        for aluno in alunos:
            payload = normalize_aulas_alunos_payload(
                {
                    "atraso": bool(request.form.get(f"atraso_{aluno.id}")),
                    "faltas": request.form.get(f"faltas_{aluno.id}"),
                    "responsabilidade": request.form.get(f"responsabilidade_{aluno.id}"),
                    "comportamento": request.form.get(f"comportamento_{aluno.id}"),
                    "participacao": request.form.get(f"participacao_{aluno.id}"),
                    "trabalho_autonomo": request.form.get(f"trabalho_autonomo_{aluno.id}"),
                    "portatil_material": request.form.get(f"portatil_material_{aluno.id}"),
                    "atividade": request.form.get(f"atividade_{aluno.id}"),
                    "falta_disciplinar": request.form.get(f"falta_disciplinar_{aluno.id}"),
                    "observacoes": request.form.get(f"observacoes_{aluno.id}"),
                }
            )
            payload["client_ts"] = datetime.utcnow().isoformat(timespec="seconds")
            payloads.append({"aula_id": aula.id, "aluno_id": aluno.id, "payload": payload})
        return payloads

    def _enqueue_payloads(payloads):
        for item in payloads:
            enqueue_upsert_aulas_alunos(
                item["aula_id"],
                item["aluno_id"],
                item["payload"],
                instance_path=app.instance_path,
            )

    def _apply_payloads(payloads):
        dedup = {}
        for item in payloads:
            key = (int(item["aula_id"]), int(item["aluno_id"]))
            dedup[key] = {
                "aula_id": key[0],
                "aluno_id": key[1],
                "payload": item["payload"],
            }

        for item in dedup.values():
            apply_upsert_aulas_alunos(
                db.session,
                item["aula_id"],
                item["aluno_id"],
                item["payload"],
            )

    def _log_db_mode():
        db_mode = app.config.get("APP_DB_MODE", "sqlite")
        uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        if db_mode == "postgres":
            parsed = urlsplit(uri)
            host = parsed.hostname or "-"
            port = parsed.port or "-"
            db_name = (parsed.path or "/").lstrip("/") or "-"
            supabase_mode = app.config.get("SUPABASE_DB_MODE", "direct")
            app.logger.info(
                "DB mode: postgres | host: %s | port: %s | db: %s | supabase_mode: %s",
                host,
                port,
                db_name,
                supabase_mode,
            )
        else:
            app.logger.info("DB mode: sqlite | uri: %s", uri)

    def try_flush_outbox(limit=200):
        try:
            db.session.execute(text("SELECT 1"))
        except Exception as exc:
            db.session.rollback()
            app.logger.warning("Sem ligação à BD principal; flush adiado: %s", exc)
            return {"ok": False, "applied": 0, "errors": 0, "remaining": pending_count(app.instance_path)}

        def _apply_from_outbox(payload):
            with db.session.begin():
                apply_upsert_aulas_alunos(
                    db.session,
                    int(payload["aula_id"]),
                    int(payload["aluno_id"]),
                    payload.get("payload") or {},
                )

        result = flush_pending(_apply_from_outbox, limit=limit, instance_path=app.instance_path)
        clear_sent(instance_path=app.instance_path)
        result["ok"] = True
        return result

    def should_skip_db_bootstrap():
        return (os.environ.get("SKIP_DB_BOOTSTRAP", "0").strip().lower() in {"1", "true", "yes", "on"})

    def _start_dev_snapshot_scheduler():
        if os.environ.get("DEV_LOCAL_SCHEDULER", "0") != "1":
            return
        if not _should_run_startup_jobs():
            app.logger.info("Scheduler snapshot ignorado neste processo (reloader/CLI).")
            return
        if app.extensions.get("offline_scheduler"):
            app.logger.info("Scheduler snapshot já ativo; sem duplicação de job.")
            return

        try:
            from apscheduler.schedulers.background import BackgroundScheduler
        except Exception:
            app.logger.warning("DEV_LOCAL_SCHEDULER=1 mas APScheduler não está disponível.")
            return

        try:
            interval = int(os.environ.get("SNAPSHOT_INTERVAL_SECONDS", "60") or "60")
        except Exception:
            interval = 60
        interval = max(5, interval)
        scheduler = BackgroundScheduler(daemon=True)

        def _scheduled_job():
            with app.app_context():
                from offline_store import get_setting

                enabled = get_setting(app.instance_path, "snapshot_enabled", "1")
                if enabled != "1":
                    app.logger.info("Snapshot automático ignorado: snapshot_enabled=0")
                    return

                app.logger.info("Snapshot automático iniciado (interval=%ss)", interval)
                result = snapshot_remote_to_local(mode="auto")
                if result.get("ok"):
                    app.logger.info(
                        "Snapshot automático concluído: turmas=%s alunos=%s aulas=%s periodos=%s modulos=%s",
                        result.get("turmas", 0),
                        result.get("alunos", 0),
                        result.get("aulas", 0),
                        result.get("periodos", 0),
                        result.get("modulos", 0),
                    )
                else:
                    app.logger.warning("Snapshot automático falhou: %s", result.get("error"))

        scheduler.add_job(
            _scheduled_job,
            "interval",
            seconds=interval,
            id="offline_snapshot_job",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        scheduler.start()
        app.extensions["offline_scheduler"] = scheduler
        app.logger.info("Scheduler local de snapshot ativo: %ss", interval)

    if should_skip_db_bootstrap():
        app.logger.info("SKIP_DB_BOOTSTRAP=1 ativo: bootstrap de BD ignorado para este processo.")
    else:
        with app.app_context():
            init_offline_db(app.instance_path)
            init_offline_store_db(app.instance_path)
            app.logger.info("Offline DB path ativo: %s", resolve_offline_db_path(app.instance_path))
            is_pg_mode = (app.config.get("APP_DB_MODE") or "sqlite").lower() == "postgres"
            startup_offline = bool(app.extensions.get("startup_offline"))
            if is_pg_mode and startup_offline:
                app.logger.warning("Bootstrap remoto ignorado: startup em modo offline degradado.")
            else:
                _ensure_columns()
                _ensure_trabalhos_tables()
            try:
                _log_db_mode()
            except Exception:
                app.logger.warning("Não foi possível emitir informação do backend de BD.")
            if _sqlite_backups_enabled():
                if app.config.get("BACKUP_ON_STARTUP", True) and _should_run_startup_jobs():
                    app.logger.info("Backups SQLite ativos")
                    _backup_database(reason="startup")
                elif not _should_run_startup_jobs():
                    app.logger.info("Arranque secundário/CLI detetado: tarefas de startup desativadas.")
            else:
                app.logger.info("Backups SQLite desativados (modo postgres)")

            flush_result = try_flush_outbox(limit=200)
            if flush_result.get("applied"):
                app.logger.info("Outbox sincronizada no arranque: %s item(ns).", flush_result["applied"])

        _start_dev_snapshot_scheduler()

    def _agendar_backup_change():
        if not _sqlite_backups_enabled():
            return
        estado = _carregar_backup_state()
        agora = datetime.now().isoformat(timespec="seconds")
        estado["pending_changes_count"] = int(estado.get("pending_changes_count") or 0) + 1
        estado["last_change_at"] = agora
        _guardar_backup_state(estado)

    def _resetar_backup_state(timestamp=None):
        estado = _carregar_backup_state()
        estado["pending_changes_count"] = 0
        estado["last_change_at"] = None
        if timestamp:
            estado["last_backup_at"] = timestamp
        _guardar_backup_state(estado)

    def _backup_scheduler():
        if _running_flask_cli():
            return
        if not _sqlite_backups_enabled():
            app.logger.info("Backups SQLite desativados (modo postgres)")
            return
        intervalo = max(5, app.config.get("BACKUP_CHECK_INTERVAL_SECONDS", 30))
        debounce = max(0, app.config.get("BACKUP_DEBOUNCE_SECONDS", 300))
        threshold = max(1, app.config.get("BACKUP_CHANGE_THRESHOLD", 15))
        while True:
            time.sleep(intervalo)
            if not app.config.get("BACKUP_ON_COMMIT", True):
                continue
            estado = _carregar_backup_state()
            pendentes = int(estado.get("pending_changes_count") or 0)
            last_change_at = estado.get("last_change_at")
            if pendentes == 0 or not last_change_at:
                continue
            try:
                last_dt = datetime.fromisoformat(last_change_at)
            except ValueError:
                continue
            agora = datetime.now()
            pronto_por_threshold = pendentes >= threshold
            pronto_por_tempo = debounce and (agora - last_dt).total_seconds() >= debounce
            if pronto_por_threshold or pronto_por_tempo:
                with app.app_context():
                    resultado = _backup_database(reason="auto")
                if resultado.get("ok"):
                    _resetar_backup_state(agora.isoformat(timespec="seconds"))
                else:
                    app.logger.warning("Backup automático falhou: %s", resultado.get("error"))

    if not _running_flask_cli() and _sqlite_backups_enabled():
        threading.Thread(target=_backup_scheduler, daemon=True).start()

    # ----------------------------------------
    # Helpers internos à app
    # ----------------------------------------
    def get_ano_letivo_atual():
        """
        Ano letivo a usar no calendário escolar:

        - se vier ?ano_id=... na querystring, usa esse;
        - senão, tenta o que está marcado como ativo;
        - senão, o mais recente (maior data_inicio_ano).
        """
        ano_id = request.args.get("ano_id", type=int)
        if ano_id:
            return AnoLetivo.query.get_or_404(ano_id)

        ano_ativo = AnoLetivo.query.filter_by(ativo=True).first()
        if ano_ativo:
            return ano_ativo

        return (
            AnoLetivo.query
            .order_by(AnoLetivo.data_inicio_ano.desc())
            .first()
        )

    def turmas_abertas_ativas():
        return (
            Turma.query.join(AnoLetivo)
            .filter(AnoLetivo.ativo == True)  # noqa: E712
            .filter(AnoLetivo.fechado == False)  # noqa: E712
            .order_by(Turma.nome)
            .all()
        )

    def _tempo_da_turma_no_dia(turma: Turma | None, data_ref: date | None):
        if not turma or not data_ref:
            return None

        tempos = {
            0: turma.tempo_segunda,
            1: turma.tempo_terca,
            2: turma.tempo_quarta,
            3: turma.tempo_quinta,
            4: turma.tempo_sexta,
        }

        return tempos.get(data_ref.weekday())

    def _chave_ordenacao_aula(aula: CalendarioAula):
        tempo = _tempo_da_turma_no_dia(aula.turma, aula.data)
        tempo_ord = tempo if tempo is not None else 999
        turma_nome = aula.turma.nome if aula.turma else ""

        return (
            aula.data or date.min,
            tempo_ord,
            turma_nome,
            aula.numero_modulo or 0,
            aula.total_geral or 0,
            aula.id,
        )

    def admin_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not app.config.get("ADMIN_ENABLED", True):
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    def _admin_nav_items():
        return [
            ("admin_anos_letivos", "Anos letivos"),
            ("admin_calendario_semanal", "Calendário semanal"),
            ("/calendario/dia", "Calendário diário"),
            ("calendario_outras_datas", "Outras datas"),
            ("admin_turmas", "Turmas"),
            ("admin_direcao_turma", "Direção de Turma"),
            ("admin_disciplinas_dt", "Disciplinas (DT)"),
            ("admin_offline", "Offline"),
        ]

    # ----------------------------------------
    # ADMIN
    # ----------------------------------------
    @app.route("/admin")
    @admin_required
    def admin_home():
        return redirect(url_for("admin_anos_letivos"))

    @app.route("/admin/anos-letivos")
    @admin_required
    def admin_anos_letivos():
        anos = AnoLetivo.query.order_by(AnoLetivo.id.desc()).all()
        return render_template("admin/anos_letivos.html", anos=anos, admin_nav_items=_admin_nav_items())

    @app.route("/admin/calendario-semanal")
    @admin_required
    def admin_calendario_semanal():
        turmas = Turma.query.order_by(Turma.nome.asc()).all()
        return render_template("admin/calendario_semanal.html", turmas=turmas, admin_nav_items=_admin_nav_items())

    @app.route("/admin/calendario-diario")
    @admin_required
    def admin_calendario_diario():
        data_ref = request.args.get("data", type=str)
        data_ref = _parse_date_local(data_ref) if data_ref else date.today()

        aulas = (
            CalendarioAula.query
            .filter(CalendarioAula.data == data_ref)
            .filter(CalendarioAula.apagado == False)  # noqa: E712
            .order_by(CalendarioAula.id.asc())
            .all()
        )
        exclusoes = Exclusao.query.filter(Exclusao.data == data_ref).all()
        extras = Extra.query.filter(Extra.data == data_ref).all()
        feriados = Feriado.query.filter(Feriado.data == data_ref).all()
        interrupcoes = (
            InterrupcaoLetiva.query
            .filter(InterrupcaoLetiva.data_inicio <= data_ref)
            .filter(InterrupcaoLetiva.data_fim >= data_ref)
            .all()
        )

        return render_template(
            "admin/calendario_diario.html",
            data_ref=data_ref,
            aulas=aulas,
            exclusoes=exclusoes,
            extras=extras,
            feriados=feriados,
            interrupcoes=interrupcoes,
            admin_nav_items=_admin_nav_items(),
        )

    @app.route("/admin/turmas")
    @admin_required
    def admin_turmas():
        turmas = Turma.query.order_by(Turma.nome.asc()).all()
        return render_template("admin/turmas.html", turmas=turmas, admin_nav_items=_admin_nav_items())

    @app.route("/admin/direcao-turma")
    @admin_required
    def admin_direcao_turma():
        dts = DTTurma.query.order_by(DTTurma.id.desc()).all()
        return render_template("admin/direcao_turma.html", dts=dts, admin_nav_items=_admin_nav_items())

    @app.route("/admin/disciplinas-dt")
    @admin_required
    def admin_disciplinas_dt():
        disciplinas = DTDisciplina.query.order_by(DTDisciplina.id.desc()).all()
        return render_template("admin/disciplinas_dt.html", disciplinas=disciplinas, admin_nav_items=_admin_nav_items())

    @app.route("/admin/offline")
    @admin_required
    def admin_offline():
        snapshot_status = _carregar_backup_status()
        return render_template(
            "admin/offline.html",
            pending_offline=pending_count(app.instance_path),
            last_error=get_last_error(app.instance_path),
            snapshot_interval_seconds=app.config.get("SNAPSHOT_INTERVAL_SECONDS", 60),
            snapshot_status=snapshot_status,
            admin_nav_items=_admin_nav_items(),
        )

    @app.route("/admin/tipos-aula")
    @admin_required
    def admin_tipos_aula():
        return redirect(url_for("calendario_outras_datas"), code=301)

    @app.route("/definicoes/tipos-aula")
    def definicoes_tipos_aula():
        return redirect(url_for("calendario_outras_datas"), code=301)

    @app.route("/admin/offline/snapshot", methods=["POST"])
    @admin_required
    def admin_offline_snapshot():
        result = snapshot_remote_to_local(mode="manual")
        if result.get("ok"):
            flash("Snapshot offline atualizado com sucesso.", "success")
        else:
            flash(result.get("error") or "Falha ao atualizar snapshot offline.", "error")
        return redirect(url_for("admin_offline"))

    # ----------------------------------------
    # DASHBOARD
    # ----------------------------------------
    def calcular_media_por_dominio(avaliacao):
        """
        Calcula a média de cada domínio por aluno.
        - Ignora rubricas não avaliadas (None)
        - Ignora alunos ausentes
        Retorna dict {letra_dominio: média}
        """
        dominios = {}
        for item in (avaliacao.itens or []):
            # Ignora alunos faltosos
            if getattr(getattr(getattr(item, "avaliacao", None), "aluno", None), "faltou", False):
                continue
            # Ignora rubricas sem pontuação
            if item.pontuacao is None:
                continue
            rubrica = getattr(item, "rubrica", None)
            dominio = getattr(rubrica, "dominio", None)
            if not dominio:
                continue
            letra = (getattr(dominio, "letra", None) or "").strip()
            if not letra:
                continue
            dominios.setdefault(letra, []).append(float(item.pontuacao))

        medias = {}
        for letra, vals in dominios.items():
            if vals:
                medias[letra] = round(sum(vals) / len(vals), 1)
            else:
                medias[letra] = None
        return medias

    def _detetar_ciclo_aula(aula):
        ciclo = (getattr(aula, "ciclo", None) or "").strip().lower()
        if ciclo in {"basico", "secundario"}:
            return ciclo

        turma_tipo = (getattr(getattr(aula, "turma", None), "tipo", None) or "").strip().lower()
        if "secund" in turma_tipo:
            return "secundario"
        return "basico"

    def _resolver_total_tempos_aula(aula):
        total_tempos = 0
        total_tempos_raw = getattr(aula, "total_tempos", None)
        if total_tempos_raw not in (None, ""):
            try:
                total_tempos = max(int(total_tempos_raw), 0)
            except (TypeError, ValueError):
                total_tempos = 0

        if total_tempos <= 0:
            horarios = Horario.query.filter_by(turma_id=aula.turma_id, weekday=aula.weekday).all()
            total_horarios = 0
            for horario in horarios:
                try:
                    total_horarios += max(int(getattr(horario, "horas", 0) or 0), 0)
                except (TypeError, ValueError):
                    continue
            total_tempos = total_horarios

        if total_tempos <= 0:
            tempo_dia = _tempo_da_turma_no_dia(aula.turma, aula.data)
            try:
                total_tempos = max(int(tempo_dia or 0), 0)
            except (TypeError, ValueError):
                total_tempos = 0

        return max(total_tempos, 1)

    def _carregar_registros_faltas(aula, alunos, total_tempos):
        registos_db = {r.aluno_id: r for r in AulaAluno.query.filter_by(aula_id=aula.id).all()}
        registros = {}
        for aluno in alunos:
            r = registos_db.get(aluno.id)
            atraso = False
            faltas_tempos = []
            fdis = False
            obs = ""
            if r:
                meta = {}
                raw_obs = (r.observacoes or "").strip()
                if raw_obs:
                    try:
                        parsed = json.loads(raw_obs)
                        if isinstance(parsed, dict):
                            meta = parsed
                    except (TypeError, ValueError, json.JSONDecodeError):
                        meta = {}
                atraso = bool(meta.get("atraso", r.atraso))
                faltas_default = list(range(1, min(max(int(r.faltas or 0), 0), total_tempos) + 1))
                faltas_tempos = [
                    int(t) for t in (meta.get("faltas", faltas_default) or [])
                    if str(t).isdigit()
                ]
                fdis = bool(meta.get("fdis", bool(getattr(r, "falta_disciplinar", 0))))
                obs = str(meta.get("obs", raw_obs if not meta else ""))

            registros[aluno.id] = {
                "atraso": atraso,
                "faltas": sorted({t for t in faltas_tempos if 1 <= t <= total_tempos}),
                "fdis": fdis,
                "obs": obs,
            }
        return registros, registos_db

    @app.route('/aula/<int:aula_id>/avaliar', methods=['GET', 'POST'])
    def aula_avaliar(aula_id):
        aula = CalendarioAula.query.get_or_404(aula_id)
        alunos = Aluno.query.filter_by(turma_id=aula.turma_id).order_by(Aluno.numero.asc(), Aluno.nome.asc()).all()
        total_tempos = _resolver_total_tempos_aula(aula)
        registros_faltas, _registos_aula = _carregar_registros_faltas(aula, alunos, total_tempos)
        avaliavel_por_aluno = {}
        for aluno in alunos:
            faltas_aluno = registros_faltas.get(aluno.id, {}).get("faltas", [])
            fdis_aluno = bool(registros_faltas.get(aluno.id, {}).get("fdis"))
            avaliavel_por_aluno[aluno.id] = (
                (not getattr(aluno, "faltou", False))
                and (len(faltas_aluno) < total_tempos)
                and (not fdis_aluno)
            )
        alunos_faltosos_ids = {aluno_id for aluno_id, avaliavel in avaliavel_por_aluno.items() if not avaliavel}
        aluno_ids_avaliaveis = {aluno_id for aluno_id, avaliavel in avaliavel_por_aluno.items() if avaliavel}
        dominios = (
            EV2Domain.query.options(joinedload(EV2Domain.rubricas))
            .filter_by(ativo=True)
            .order_by(EV2Domain.letra.asc(), EV2Domain.nome.asc())
            .all()
        )
        dominios_view = []
        for idx, dominio in enumerate(dominios):
            letra = getattr(dominio, "letra", None)
            if not letra:
                letra = chr(ord("A") + idx)
            rubricas_dominio = sorted(
                [r for r in (dominio.rubricas or []) if getattr(r, "ativo", True)],
                key=lambda r: ((r.codigo or ""), (r.nome or "")),
            )
            dominios_view.append(
                {
                    "id": dominio.id,
                    "nome": dominio.nome,
                    "letra": letra,
                    "codigo": getattr(dominio, "codigo", None),
                    "rubricas": rubricas_dominio,
                }
            )

        rubricas = [rubrica for dominio in dominios_view for rubrica in dominio["rubricas"]]
        rubricas_por_dominio = {dominio["id"]: dominio["rubricas"] for dominio in dominios_view}

        if request.method == 'POST':
            rubrica_id = request.form.get("rubrica_id", type=int)
            if rubrica_id:
                valor_raw = request.form.get("valor")
                valor = None
                if valor_raw not in (None, ""):
                    try:
                        valor = float(valor_raw)
                    except (TypeError, ValueError):
                        valor = None

                aluno_ids = request.form.getlist("aluno_ids[]")
                if not aluno_ids:
                    aluno_unico = request.form.get("aluno_id")
                    if aluno_unico:
                        aluno_ids = [aluno_unico]
                aluno_ids = [int(aluno_id) for aluno_id in aluno_ids if str(aluno_id).isdigit()]
                aluno_ids = [aluno_id for aluno_id in aluno_ids if aluno_id in aluno_ids_avaliaveis]
                if not aluno_ids:
                    return jsonify({"status": "error", "message": "Sem alunos elegíveis para atualizar"}), 400

                for aluno_id in aluno_ids:
                    avaliacao = Avaliacao.query.filter_by(aula_id=aula.id, aluno_id=aluno_id).first()
                    if not avaliacao:
                        avaliacao = Avaliacao(aula_id=aula.id, aluno_id=aluno_id)
                        db.session.add(avaliacao)
                        db.session.flush()

                    item = AvaliacaoItem.query.filter_by(avaliacao_id=avaliacao.id, rubrica_id=rubrica_id).first()
                    if not item:
                        item = AvaliacaoItem(avaliacao_id=avaliacao.id, rubrica_id=rubrica_id)
                        db.session.add(item)
                    item.pontuacao = valor

                    medias = calcular_media_por_dominio(avaliacao)
                    avaliacao.resultado = round(sum(medias.values()) / len(medias), 1) if medias else 0.0

                db.session.commit()

                medias_atualizadas = {}
                for aluno_id in aluno_ids:
                    av = (
                        Avaliacao.query.filter_by(aula_id=aula.id, aluno_id=aluno_id)
                        .options(
                            joinedload(Avaliacao.itens)
                            .joinedload(AvaliacaoItem.rubrica)
                            .joinedload(EV2Rubric.dominio)
                        )
                        .first()
                    )
                    medias_atualizadas[str(aluno_id)] = calcular_media_por_dominio(av) if av else {}

                return jsonify(
                    {
                        "status": "ok",
                        "rubrica_id": rubrica_id,
                        "valor": valor,
                        "medias_por_aluno": medias_atualizadas,
                    }
                ), 200
            return jsonify({"status": "error", "message": "rubrica_id é obrigatório"}), 400

        avaliacao_map = {
            av.aluno_id: av
            for av in (
                Avaliacao.query.filter_by(aula_id=aula.id)
                .options(
                    joinedload(Avaliacao.itens)
                    .joinedload(AvaliacaoItem.rubrica)
                    .joinedload(EV2Rubric.dominio)
                )
                .all()
            )
        }

        avaliacoes = {}
        medias_por_aluno = {}
        for aluno in alunos:
            if aluno.id in alunos_faltosos_ids:
                avaliacoes[aluno.id] = {}
                medias_por_aluno[aluno.id] = {}
                continue
            av = avaliacao_map.get(aluno.id)
            avaliacoes[aluno.id] = {}
            if not av:
                medias_por_aluno[aluno.id] = {}
                continue
            for item in av.itens or []:
                if item.pontuacao is not None:
                    avaliacoes[aluno.id][item.rubrica_id] = item.pontuacao
            medias_por_aluno[aluno.id] = calcular_media_por_dominio(av)

        return render_template(
            'aula_avaliar.html',
            aula=aula,
            alunos=alunos,
            dominios=dominios_view,
            rubricas_por_dominio=rubricas_por_dominio,
            avaliacoes=avaliacoes,
            medias_por_aluno=medias_por_aluno,
            avaliavel_por_aluno=avaliavel_por_aluno,
            total_tempos=total_tempos,
            alunos_faltosos_ids=alunos_faltosos_ids,
            ciclo_aula=_detetar_ciclo_aula(aula),
        )

    @app.route('/aula/<int:aula_id>/pontualidade', methods=['GET', 'POST'])
    def aula_pontualidade(aula_id):
        aula = CalendarioAula.query.get_or_404(aula_id)
        alunos = Aluno.query.filter_by(turma_id=aula.turma_id).order_by(Aluno.numero.asc(), Aluno.nome.asc()).all()
        registos = {r.aluno_id: r for r in AulaAluno.query.filter_by(aula_id=aula.id).all()}

        pontualidade = {aluno.id: 1 for aluno in alunos}
        for aluno in alunos:
            registo = registos.get(aluno.id)
            if not registo:
                continue
            pontualidade[aluno.id] = 0 if (bool(registo.atraso) or (registo.faltas or 0) > 0) else 1

        if request.method == "POST":
            for aluno in alunos:
                valor_bruto = request.form.get(f"pontualidade-{aluno.id}", "1")
                try:
                    valor = int(valor_bruto)
                except (TypeError, ValueError):
                    valor = 1
                valor = 1 if valor == 1 else 0

                registo = registos.get(aluno.id)
                if not registo:
                    registo = AulaAluno(aula_id=aula.id, aluno_id=aluno.id)
                    db.session.add(registo)
                    registos[aluno.id] = registo
                registo.atraso = (valor == 0)
            db.session.commit()
            flash("Pontualidade e faltas atualizadas.", "success")
            return redirect(url_for("aula_avaliar", aula_id=aula.id))

        return render_template(
            "aula_pontualidade.html",
            aula=aula,
            alunos=alunos,
            pontualidade=pontualidade,
        )

    @app.route('/aula/<int:aula_id>/faltas', methods=['GET', 'POST'])
    def aula_faltas(aula_id):
        aula = CalendarioAula.query.get_or_404(aula_id)
        alunos = Aluno.query.filter_by(turma_id=aula.turma_id).order_by(Aluno.numero.asc(), Aluno.nome.asc()).all()
        total_tempos = _resolver_total_tempos_aula(aula)
        registros, registos_db = _carregar_registros_faltas(aula, alunos, total_tempos)

        if request.method == "POST":
            for aluno in alunos:
                atraso = request.form.get(f"atraso-{aluno.id}") == "1"

                faltas_raw = request.form.getlist(f"faltas-{aluno.id}[]")
                faltas_tempos = sorted({
                    int(t)
                    for t in faltas_raw
                    if str(t).isdigit() and 1 <= int(t) <= total_tempos
                })
                fdis = request.form.get(f"fdis-{aluno.id}") == "1"
                obs = (request.form.get(f"obs-{aluno.id}", "") or "").strip()

                registo = registos_db.get(aluno.id)
                if not registo:
                    registo = AulaAluno(aula_id=aula.id, aluno_id=aluno.id)
                    db.session.add(registo)
                    registos_db[aluno.id] = registo

                registo.atraso = atraso
                registo.faltas = len(faltas_tempos)
                registo.falta_disciplinar = 1 if fdis else 0
                registo.observacoes = json.dumps(
                    {
                        "atraso": atraso,
                        "faltas": faltas_tempos,
                        "fdis": fdis,
                        "obs": obs if fdis else "",
                    },
                    ensure_ascii=False,
                )

            db.session.commit()
            flash("Registos de faltas e atrasos atualizados.", "success")
            return redirect(url_for("aula_faltas", aula_id=aula.id))

        return render_template(
            "aula_faltas.html",
            aula=aula,
            alunos=alunos,
            registros=registros,
            total_tempos=total_tempos,
        )

    @app.route("/")
    def dashboard():
        turmas = turmas_abertas_ativas()
        ano_atual = get_ano_letivo_atual()
        turma_id = request.args.get("turma_id", type=int)
        search_min_len = 2
        q = (request.args.get("q") or "").strip()
        search_results = []
        turma_atual = next((t for t in turmas if t.id == turma_id), None)
        if not turma_atual and turmas:
            turma_atual = turmas[0]

        hoje = date.today()
        aula_hoje = None
        proxima_aula = None
        checklist = {
            "sumario": False,
            "faltas": False,
            "avaliacao": False,
        }
        trabalhos_ativos = []
        indicadores = {
            "por_entregar": 0,
            "atrasadas": 0,
            "media_global": None,
            "nota_zero": 0,
        }
        disciplina_atual = None
        offline_pending = 0
        offline_error_count = 0
        dashboard_last_snapshot_ok_display = "-"
        dashboard_last_sync_ok_display = "-"
        dashboard_last_error_display = "Sem erros"
        dashboard_snapshot_last_run_display = "-"
        dashboard_snapshot_last_run_status = "-"

        try:
            offline_outbox = outbox_status(app.instance_path)
            offline_pending = int(offline_outbox.get("pending", 0))
            offline_error_count = int(count_offline_errors(app.instance_path))

            last_sync_ok_at = get_state_datetime(app.instance_path, "last_sync_ok_at")
            last_snapshot_ok_at = get_state_datetime(app.instance_path, "last_snapshot_ok_at")
            dashboard_last_sync_ok_display = _formatar_data_hora(last_sync_ok_at) or "-"
            dashboard_last_snapshot_ok_display = _formatar_data_hora(last_snapshot_ok_at) or "-"

            last_error_row = get_last_offline_error(app.instance_path)
            if last_error_row and offline_error_count > 0:
                dashboard_last_error_display = _formatar_data_hora(last_error_row.get("created_at")) or "Com erros"

            snapshot_status = get_snapshot_status(app.instance_path)
            last_run = (snapshot_status or {}).get("last_run") or {}
            snapshot_last_run_at = last_run.get("finished_at") or last_run.get("started_at")
            dashboard_snapshot_last_run_display = _formatar_data_hora(snapshot_last_run_at) or "-"
            if last_run:
                dashboard_snapshot_last_run_status = "OK" if int(last_run.get("ok") or 0) == 1 else "ERRO"
        except Exception as exc:
            app.logger.exception("Falha ao carregar resumo offline da dashboard: %s", exc)

        if len(q) >= search_min_len:
            bind = db.session.get_bind()
            dialect_name = bind.dialect.name if bind is not None else ""
            like_pattern = f"%{q}%"

            def _sumario_match(column):
                if dialect_name == "sqlite":
                    return column.like(like_pattern)
                return column.ilike(like_pattern)

            search_predicates = [_sumario_match(CalendarioAula.sumario)]
            if hasattr(CalendarioAula, "sumarios"):
                search_predicates.append(_sumario_match(CalendarioAula.sumarios))
            if hasattr(CalendarioAula, "previsao"):
                search_predicates.append(_sumario_match(CalendarioAula.previsao))

            search_results = (
                db.session.query(CalendarioAula)
                .options(joinedload(CalendarioAula.turma))
                .join(Turma, Turma.id == CalendarioAula.turma_id)
                .filter(CalendarioAula.apagado == False)  # noqa: E712
                .filter(CalendarioAula.sumario.isnot(None))
                .filter(CalendarioAula.sumario != "")
                .filter(or_(*search_predicates))
                .order_by(CalendarioAula.data.desc(), Turma.nome.asc())
                .limit(200)
                .all()
            )

        if turma_atual:
            disciplina_atual = turma_atual.disciplinas[0] if getattr(turma_atual, "disciplinas", None) else None

            aula_hoje = (
                CalendarioAula.query
                .filter_by(turma_id=turma_atual.id, data=hoje, apagado=False)
                .order_by(CalendarioAula.numero_modulo.asc(), CalendarioAula.id.asc())
                .first()
            )
            if not aula_hoje:
                proxima_aula = (
                    CalendarioAula.query
                    .filter(CalendarioAula.turma_id == turma_atual.id)
                    .filter(CalendarioAula.apagado == False)  # noqa: E712
                    .filter(CalendarioAula.data >= hoje)
                    .order_by(CalendarioAula.data.asc(), CalendarioAula.numero_modulo.asc(), CalendarioAula.id.asc())
                    .first()
                )

            aula_ref = aula_hoje or proxima_aula
            if aula_ref:
                checklist["sumario"] = bool((aula_ref.sumario or "").strip())
                checklist["faltas"] = (
                    db.session.query(AulaAluno.id)
                    .filter(AulaAluno.aula_id == aula_ref.id)
                    .first()
                    is not None
                )
                checklist["avaliacao"] = (
                    db.session.query(AulaAluno.id)
                    .filter(AulaAluno.aula_id == aula_ref.id)
                    .filter(
                        or_(
                            AulaAluno.responsabilidade.isnot(None),
                            AulaAluno.comportamento.isnot(None),
                            AulaAluno.participacao.isnot(None),
                            AulaAluno.trabalho_autonomo.isnot(None),
                            AulaAluno.portatil_material.isnot(None),
                            AulaAluno.atividade.isnot(None),
                        )
                    )
                    .first()
                    is not None
                )

            trabalhos_ativos = (
                Trabalho.query
                .filter(Trabalho.turma_id == turma_atual.id)
                .order_by(
                    Trabalho.data_limite.is_(None),
                    Trabalho.data_limite.asc(),
                    Trabalho.created_at.desc(),
                )
                .limit(5)
                .all()
            )

            notas = []
            for trabalho in trabalhos_ativos:
                total_grupos = len(trabalho.grupos)
                entregues = 0
                atrasadas = 0
                for entrega in trabalho.entregas:
                    if not entrega.entregue:
                        continue
                    entregues += 1
                    if trabalho.data_limite and entrega.data_entrega and entrega.data_entrega > trabalho.data_limite:
                        atrasadas += 1
                trabalho.total_grupos_dashboard = total_grupos
                trabalho.entregues_dashboard = entregues
                trabalho.atrasadas_dashboard = atrasadas
                trabalho.percent_entregues_dashboard = round((entregues / total_grupos) * 100) if total_grupos else 0

                por_entregar = max(total_grupos - entregues, 0)
                indicadores["por_entregar"] += por_entregar
                indicadores["atrasadas"] += atrasadas

                for entrega in trabalho.entregas:
                    if not entrega.entregue:
                        notas.append(0.0)
                        indicadores["nota_zero"] += 1
                        continue
                    valores = []
                    if entrega.consecucao is not None:
                        valores.append(float(entrega.consecucao))
                    if entrega.qualidade is not None:
                        valores.append(float(entrega.qualidade))
                    for ep in entrega.parametros:
                        if ep.valor_numerico is not None:
                            valores.append(float(ep.valor_numerico))
                    media_base = (sum(valores) / len(valores)) if valores else 0.0
                    fator = 1.0
                    if trabalho.data_limite and entrega.data_entrega and entrega.data_entrega > trabalho.data_limite:
                        fator = 0.5
                    nota_final = media_base * fator
                    notas.append(nota_final)
                    if nota_final == 0:
                        indicadores["nota_zero"] += 1

            if notas:
                indicadores["media_global"] = round(sum(notas) / len(notas), 2)

        return render_template(
            "dashboard.html",
            turmas=turmas,
            ano_atual=ano_atual,
            turma_atual=turma_atual,
            disciplina_atual=disciplina_atual,
            aula_hoje=aula_hoje,
            proxima_aula=proxima_aula,
            checklist=checklist,
            trabalhos_ativos=trabalhos_ativos,
            indicadores=indicadores,
            offline_pending=offline_pending,
            offline_error_count=offline_error_count,
            dashboard_last_snapshot_ok_display=dashboard_last_snapshot_ok_display,
            dashboard_last_sync_ok_display=dashboard_last_sync_ok_display,
            dashboard_last_error_display=dashboard_last_error_display,
            dashboard_snapshot_last_run_display=dashboard_snapshot_last_run_display,
            dashboard_snapshot_last_run_status=dashboard_snapshot_last_run_status,
            q=q,
            search_q=q,
            search_min_len=search_min_len,
            search_results=search_results,
        )

    @app.route("/backups")
    def backups_list():
        backups = _list_backups()
        db_path = _get_db_path()
        db_exists = bool(db_path and os.path.isfile(db_path))
        backup_status = _carregar_backup_status()
        return render_template(
            "backups/list.html",
            title="Backups",
            backups=backups,
            last_backup=backups[0] if backups else None,
            hostname=socket.gethostname(),
            db_exists=db_exists,
            backup_status=backup_status,
        )

    @app.route("/backups/<filename>")
    def backups_download(filename):
        backup_dir = app.config.get("BACKUP_DIR")
        if not backup_dir:
            abort(404)
        if filename != os.path.basename(filename):
            abort(404)
        if os.path.sep in filename or (os.path.altsep and os.path.altsep in filename):
            abort(404)
        if not _parse_backup_filename(filename):
            abort(404)
        path = os.path.join(backup_dir, filename)
        if not os.path.isfile(path):
            abort(404)
        return send_from_directory(backup_dir, filename, as_attachment=True)

    @app.route("/aulas/<int:aula_id>/sumario/copiar-previsao", methods=["POST"])
    def sumario_copiar_previsao(aula_id):
        aula = CalendarioAula.query.get_or_404(aula_id)
        payload = request.get_json(silent=True) or {}
        previsao_origem = payload.get("sumario", None)
        if previsao_origem is None:
            previsao_origem = aula.previsao or ""
        anterior = aula.sumario or ""
        novo = _strip_html_to_text(previsao_origem)
        if anterior == novo:
            return jsonify({"status": "noop", "sumario": _strip_html_to_text(aula.sumario or "")})
        _registar_sumario_historico(
            aula,
            "copiar_previsao_para_sumario",
            anterior,
            novo,
        )
        aula.sumario = novo
        db.session.commit()
        return jsonify(
            {
                "status": "ok",
                "sumario": novo,
                "previous": anterior,
                "last_save": _formatar_data_hora(_load_last_save()),
            }
        )

    @app.route("/aulas/<int:aula_id>/sumario/reverter", methods=["POST"])
    def sumario_reverter(aula_id):
        aula = CalendarioAula.query.get_or_404(aula_id)
        ultimo = (
            AulaSumarioHistorico.query
            .filter_by(calendario_aula_id=aula.id)
            .order_by(AulaSumarioHistorico.created_at.desc(), AulaSumarioHistorico.id.desc())
            .first()
        )
        if not ultimo:
            return jsonify({"status": "error", "message": "Sem histórico para reverter."}), 400
        anterior = ultimo.sumario_anterior or ""
        novo = aula.sumario or ""
        _registar_sumario_historico(aula, "reverter", novo, anterior)
        aula.sumario = anterior
        db.session.commit()
        return jsonify(
            {
                "status": "ok",
                "sumario": aula.sumario or "",
                "last_save": _formatar_data_hora(_load_last_save()),
            }
        )

    @app.route("/backups/trigger", methods=["POST"])
    def backups_trigger():
        resultado = _backup_database(reason="manual")
        if resultado.get("ok"):
            flash(f"Backup criado: {resultado.get('filename')}", "success")
            _resetar_backup_state(datetime.now().isoformat(timespec="seconds"))
        else:
            flash(resultado.get("error") or "Não foi possível criar backup.", "error")
        return redirect(request.referrer or url_for("dashboard"))

    def _obter_aula_turma(turma_id, aula_id):
        aula = CalendarioAula.query.get_or_404(aula_id)
        if aula.turma_id != turma_id:
            abort(404)
        return aula

    def _filtrar_por_periodo(query):
        periodo_id = request.form.get("periodo_id", type=int)
        if periodo_id:
            return query.filter(CalendarioAula.periodo_id == periodo_id)
        return query

    @app.route(
        "/turmas/<int:turma_id>/aulas/<int:aula_id>/previsao/limpar",
        methods=["POST"],
    )
    def previsao_limpar(turma_id, aula_id):
        aula = _obter_aula_turma(turma_id, aula_id)
        aula.previsao = ""
        db.session.commit()
        flash("Previsão limpa.", "success")
        return redirect(request.referrer or url_for("dashboard"))

    @app.route(
        "/turmas/<int:turma_id>/aulas/<int:aula_id>/previsao/copiar-anterior",
        methods=["POST"],
    )
    def previsao_copiar_anterior(turma_id, aula_id):
        aula = _obter_aula_turma(turma_id, aula_id)
        query = CalendarioAula.query.filter_by(turma_id=turma_id).filter(
            CalendarioAula.apagado == False,  # noqa: E712
            CalendarioAula.data < aula.data,
        )
        query = _filtrar_por_periodo(query)
        anterior = (
            query.order_by(CalendarioAula.data.desc(), CalendarioAula.id.desc()).first()
        )
        if not anterior:
            flash("Não existe aula anterior para copiar.", "error")
            return redirect(request.referrer or url_for("dashboard"))
        aula.previsao = _normalizar_texto_opcional(anterior.previsao) or ""
        db.session.commit()
        flash("Previsão copiada da aula anterior.", "success")
        return redirect(request.referrer or url_for("dashboard"))

    @app.route(
        "/turmas/<int:turma_id>/aulas/<int:aula_id>/previsao/enviar-seguinte",
        methods=["POST"],
    )
    def previsao_enviar_seguinte(turma_id, aula_id):
        aula = _obter_aula_turma(turma_id, aula_id)
        previsao_origem = _normalizar_texto_opcional(aula.previsao) or ""
        if not previsao_origem.strip():
            flash("A previsão está vazia.", "error")
            return redirect(request.referrer or url_for("dashboard"))
        query = CalendarioAula.query.filter_by(turma_id=turma_id).filter(
            CalendarioAula.apagado == False,  # noqa: E712
            CalendarioAula.data > aula.data,
        )
        query = _filtrar_por_periodo(query)
        seguinte = query.order_by(CalendarioAula.data.asc(), CalendarioAula.id.asc()).first()
        if not seguinte:
            flash("Não existe aula seguinte para enviar.", "error")
            return redirect(request.referrer or url_for("dashboard"))
        seguinte.previsao = previsao_origem
        db.session.commit()
        flash("Previsão enviada para a aula seguinte.", "success")
        return redirect(request.referrer or url_for("dashboard"))

    # ----------------------------------------
    # LIVROS
    # ----------------------------------------
    @app.route("/livros")
    def livros_list():
        livros = Livro.query.order_by(Livro.nome).all()
        return render_template("livros/list.html", livros=livros)

    @app.route("/livros/novo", methods=["GET", "POST"])
    def livros_new():
        if request.method == "POST":
            nome = (request.form.get("nome") or "").strip()

            if not nome:
                flash("O nome do livro é obrigatório.", "error")
                return render_template("livros/form.html", titulo="Novo Livro")

            existente = Livro.query.filter(func.lower(Livro.nome) == nome.lower()).first()
            if existente:
                flash("Já existe um livro com esse nome.", "error")
                return render_template("livros/form.html", titulo="Novo Livro")

            livro = Livro(nome=nome)
            db.session.add(livro)
            db.session.commit()
            flash("Livro criado com sucesso.", "success")
            return redirect(url_for("livros_detail", livro_id=livro.id))

        return render_template("livros/form.html", titulo="Novo Livro")

    @app.route("/livros/<int:livro_id>")
    def livros_detail(livro_id):
        livro = Livro.query.get_or_404(livro_id)
        return render_template("livros/detail.html", livro=livro)

    @app.route("/livros/<int:livro_id>/editar", methods=["GET", "POST"])
    def livros_edit(livro_id):
        livro = Livro.query.get_or_404(livro_id)

        if request.method == "POST":
            nome = (request.form.get("nome") or "").strip()

            if not nome:
                flash("O nome do livro é obrigatório.", "error")
                return render_template(
                    "livros/form.html",
                    titulo="Editar Livro",
                    livro=livro,
                )

            existente = (
                Livro.query
                .filter(func.lower(Livro.nome) == nome.lower(), Livro.id != livro.id)
                .first()
            )
            if existente:
                flash("Já existe outro livro com esse nome.", "error")
                return render_template(
                    "livros/form.html",
                    titulo="Editar Livro",
                    livro=livro,
                )

            livro.nome = nome
            db.session.commit()
            flash("Livro atualizado com sucesso.", "success")
            return redirect(url_for("livros_detail", livro_id=livro.id))

        return render_template("livros/form.html", titulo="Editar Livro", livro=livro)

    @app.route("/livros/<int:livro_id>/gerar", methods=["POST"])
    def livros_gerar(livro_id):
        livro = Livro.query.get_or_404(livro_id)
        modo = request.form.get("modo", "recalcular")
        recalcular_tudo = (modo == "recalcular")

        # opcional: impedir geração se a turma estiver num ano letivo fechado
        for turma in livro.turmas:
            if turma.ano_letivo and turma.ano_letivo.fechado:
                flash(
                    f"Não é possível gerar calendários: a turma {turma.nome} "
                    f"pertence a um ano letivo fechado ({turma.ano_letivo.nome}).",
                    "error",
                )
                return redirect(url_for("livros_detail", livro_id=livro.id))

        turmas_para_gerar = []
        turmas_com_calendario = []

        for turma in livro.turmas:
            existente = (
                db.session.query(CalendarioAula.id)
                .filter_by(turma_id=turma.id, apagado=False)
                .first()
            )
            if existente:
                turmas_com_calendario.append(turma.nome)
                continue
            turmas_para_gerar.append(turma)

        if not turmas_para_gerar:
            mensagem = "Todas as turmas já têm calendário gerado."
            if turmas_com_calendario:
                lista = ", ".join(sorted(turmas_com_calendario))
                mensagem += f" (Turmas: {lista})"
            flash(mensagem, "warning")
            return redirect(url_for("livros_detail", livro_id=livro.id))

        for turma in turmas_para_gerar:
            garantir_periodos_basicos_para_turma(turma)
            gerar_calendario_turma(turma.id, recalcular_tudo=recalcular_tudo)

        aviso_gerados = "Calendários gerados/atualizados com sucesso."
        if turmas_com_calendario:
            lista = ", ".join(sorted(turmas_com_calendario))
            aviso_gerados += f" As seguintes turmas foram ignoradas por já terem calendário: {lista}."
        flash(aviso_gerados, "success")
        return redirect(url_for("livros_detail", livro_id=livro.id))

    @app.route("/livros/<int:livro_id>/delete", methods=["POST"])
    def livros_delete(livro_id):
        livro = Livro.query.get_or_404(livro_id)

        # Remover vínculos antes de apagar
        LivroTurma.query.filter_by(livro_id=livro.id).delete()

        db.session.delete(livro)
        db.session.commit()

        flash("Livro removido com sucesso.", "success")
        return redirect(url_for("livros_list"))

    # ----------------------------------------
    # TURMAS
    # ----------------------------------------
    def _gerar_nome_turma_copia(nome_base: str) -> str:
        base = nome_base.strip() or "Turma"
        candidato = f"{base} (Cópia)"
        contador = 2
        while Turma.query.filter_by(nome=candidato).first():
            candidato = f"{base} (Cópia {contador})"
            contador += 1
        return candidato

    @app.route("/turmas")
    def turmas_list():
        turmas = (
            Turma.query.options(joinedload(Turma.ano_letivo))
            .outerjoin(AnoLetivo)
            .order_by(AnoLetivo.ativo.desc(), AnoLetivo.fechado.asc(), AnoLetivo.data_inicio_ano.desc(), Turma.nome)
            .all()
        )

        turmas_abertas = [t for t in turmas if not (t.ano_letivo and t.ano_letivo.fechado)]
        turmas_fechadas = [t for t in turmas if t.ano_letivo and t.ano_letivo.fechado]
        anos_letivos = (
            AnoLetivo.query.order_by(AnoLetivo.data_inicio_ano.desc()).all()
        )

        return render_template(
            "turmas/list.html",
            turmas_abertas=turmas_abertas,
            turmas_fechadas=turmas_fechadas,
            csv_dest_dir=app.config.get("CSV_EXPORT_DIR"),
            backup_json_dir=app.config.get("BACKUP_JSON_DIR"),
            anos_letivos=anos_letivos,
        )

    @app.route("/turmas/<int:turma_id>/clone", methods=["POST"])
    def turmas_clone(turma_id):
        turma = Turma.query.get_or_404(turma_id)
        ano = turma.ano_letivo
        if ano and ano.fechado:
            flash("Ano letivo fechado: não é possível clonar esta turma.", "error")
            return redirect(url_for("turmas_list"))

        nome_copia = _gerar_nome_turma_copia(turma.nome)
        nova = Turma(
            nome=nome_copia,
            tipo=turma.tipo,
            periodo_tipo=turma.periodo_tipo,
            ano_letivo_id=turma.ano_letivo_id,
            letiva=turma.letiva,
            carga_segunda=turma.carga_segunda,
            carga_terca=turma.carga_terca,
            carga_quarta=turma.carga_quarta,
            carga_quinta=turma.carga_quinta,
            carga_sexta=turma.carga_sexta,
            tempo_segunda=turma.tempo_segunda,
            tempo_terca=turma.tempo_terca,
            tempo_quarta=turma.tempo_quarta,
            tempo_quinta=turma.tempo_quinta,
            tempo_sexta=turma.tempo_sexta,
        )
        db.session.add(nova)
        db.session.flush()

        for livro in turma.livros:
            nova.livros.append(livro)

        for rel in TurmaDisciplina.query.filter_by(turma_id=turma.id).all():
            db.session.add(
                TurmaDisciplina(
                    turma_id=nova.id,
                    disciplina_id=rel.disciplina_id,
                    horas_semanais=rel.horas_semanais,
                )
            )

        for mod in Modulo.query.filter_by(turma_id=turma.id).all():
            db.session.add(
                Modulo(
                    turma_id=nova.id,
                    nome=mod.nome,
                    total_aulas=mod.total_aulas,
                    tolerancia=mod.tolerancia,
                )
            )

        for horario in Horario.query.filter_by(turma_id=turma.id).all():
            db.session.add(
                Horario(
                    turma_id=nova.id,
                    weekday=horario.weekday,
                    horas=horario.horas,
                )
            )

        for aluno in Aluno.query.filter_by(turma_id=turma.id).all():
            db.session.add(
                Aluno(
                    turma_id=nova.id,
                    processo=aluno.processo,
                    numero=aluno.numero,
                    nome=aluno.nome,
                    nome_curto=aluno.nome_curto,
                    nee=aluno.nee,
                    observacoes=aluno.observacoes,
                )
            )

        db.session.commit()
        flash(f"Turma clonada como '{nova.nome}'.", "success")
        return redirect(url_for("turmas_list"))

    @app.route("/turmas/export/csv", methods=["POST"])
    def turmas_export_csv():
        acao = (request.form.get("acao") or "exportar").lower()
        csv_dest_dir = (request.form.get("csv_dest_dir") or "").strip()

        if not csv_dest_dir:
            flash("Indica uma pasta de destino para os CSV.", "error")
            return redirect(url_for("turmas_list"))

        try:
            os.makedirs(csv_dest_dir, exist_ok=True)
        except OSError as exc:
            flash(f"Não foi possível usar a pasta indicada: {exc}", "error")
            return redirect(url_for("turmas_list"))

        _save_export_options(csv_dest_dir=csv_dest_dir)
        app.config["CSV_EXPORT_DIR"] = csv_dest_dir

        if acao == "guardar":
            flash("Pasta de destino atualizada.", "success")
            return redirect(url_for("turmas_list"))

        hoje = date.today()
        data_export = hoje.strftime("%Y%m%d")
        total_ficheiros = 0
        falhas = []
        turmas = (
            Turma.query.options(joinedload(Turma.ano_letivo))
            .outerjoin(AnoLetivo)
            .order_by(
                AnoLetivo.ativo.desc(),
                AnoLetivo.fechado.asc(),
                AnoLetivo.data_inicio_ano.desc(),
                Turma.nome,
            )
            .all()
        )

        for turma in turmas:
            dados = exportar_sumarios_json(turma.id)
            linhas_validas = []

            for linha in dados:
                tipo = (linha.get("tipo") or "").lower()
                if tipo not in {"normal", "extra"}:
                    continue

                data_txt = linha.get("data")
                try:
                    data_aula = datetime.fromisoformat(data_txt).date() if data_txt else None
                except ValueError:
                    data_aula = None

                if data_aula and data_aula > hoje:
                    continue

                data_legivel = ""
                if data_aula:
                    data_legivel = data_aula.strftime("%d/%m/%Y")
                elif data_txt:
                    data_legivel = data_txt

                linhas_validas.append(
                    [
                        data_legivel,
                        linha.get("modulo_nome") or "",
                        csv_text(linha.get("sumarios") or ""),
                        _strip_html_to_text(linha.get("sumario") or ""),
                    ]
                )

            if not linhas_validas:
                continue

            filename = f"sumarios_{_slugify_filename(turma.nome, 'turma')}_{data_export}.csv"
            destino = os.path.join(csv_dest_dir, filename)

            try:
                with open(destino, "w", newline="", encoding="utf-8-sig") as handle:
                    writer = csv.writer(handle, delimiter=";")
                    writer.writerow(["DATA", "MÓDULO", "N.º Sumário", "Sumário"])
                    writer.writerows(linhas_validas)
                total_ficheiros += 1
            except OSError as exc:
                falhas.append(f"{turma.nome}: {exc}")

        if total_ficheiros:
            flash(
                f"Exportação concluída: {total_ficheiros} ficheiro(s) criado(s) em {csv_dest_dir}.",
                "success",
            )
        else:
            flash(
                "Nenhum sumário elegível encontrado para exportar até à data de hoje.",
                "warning",
            )

        if falhas:
            flash("Falhas ao exportar: " + "; ".join(falhas), "error")

        return redirect(url_for("turmas_list"))

    @app.route("/turmas/<int:turma_id>/sumarios/export/csv", methods=["POST"])
    def turma_sumarios_export_csv(turma_id):
        turma = Turma.query.get_or_404(turma_id)
        periodos = (
            Periodo.query.filter_by(turma_id=turma.id)
            .order_by(Periodo.data_inicio)
            .all()
        )
        periodo_id = request.form.get("periodo_id", type=int)
        periodo = next((p for p in periodos if p.id == periodo_id), None)

        data_inicio = _parse_date_form(request.form.get("data_inicio"))
        data_fim = _parse_date_form(request.form.get("data_fim"))
        if periodo:
            data_inicio = data_inicio or periodo.data_inicio
            data_fim = data_fim or periodo.data_fim

        dados = exportar_sumarios_json(turma.id)
        linhas_validas = []

        for linha in dados:
            tipo = (linha.get("tipo") or "").lower()
            if tipo not in {"normal", "extra"}:
                continue

            data_txt = linha.get("data")
            try:
                data_aula = datetime.fromisoformat(data_txt).date() if data_txt else None
            except ValueError:
                data_aula = None

            if not data_aula:
                continue

            if data_inicio and data_aula < data_inicio:
                continue
            if data_fim and data_aula > data_fim:
                continue

            linhas_validas.append(
                [
                    data_aula.strftime("%d/%m/%Y"),
                    linha.get("modulo_nome") or "",
                    csv_text(linha.get("sumarios") or ""),
                    _strip_html_to_text(linha.get("sumario") or ""),
                ]
            )

        if not linhas_validas:
            flash("Nenhum sumário encontrado para o intervalo selecionado.", "warning")
            return redirect(url_for("turma_calendario", turma_id=turma.id))

        range_label = "todas"
        if data_inicio or data_fim:
            inicio_txt = data_inicio.strftime("%Y%m%d") if data_inicio else "inicio"
            fim_txt = data_fim.strftime("%Y%m%d") if data_fim else "fim"
            range_label = f"{inicio_txt}_{fim_txt}"
        filename = f"sumarios_{_slugify_filename(turma.nome, 'turma')}_{range_label}.csv"
        data = build_csv_data(
            ["DATA", "MÓDULO", "N.º Sumário", "Sumário"],
            linhas_validas,
        )
        return Response(
            data,
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    # ----------------------------------------
    # DIREÇÃO DE TURMA
    # ----------------------------------------
    def _validar_dt_turma(turma_id, ano_letivo_id):
        if not turma_id:
            flash("Seleciona uma turma válida.", "error")
            return None, None

        turma = Turma.query.options(joinedload(Turma.ano_letivo)).get(turma_id)
        if not turma:
            flash("Turma inválida.", "error")
            return None, None

        if turma.ano_letivo_id:
            if ano_letivo_id and turma.ano_letivo_id != ano_letivo_id:
                flash(
                    "A turma selecionada não pertence ao ano letivo escolhido.",
                    "error",
                )
                return None, None
            ano_letivo_id = turma.ano_letivo_id

        if not ano_letivo_id:
            flash("Seleciona um ano letivo válido.", "error")
            return None, None

        ano = AnoLetivo.query.get(ano_letivo_id)
        if not ano:
            flash("Ano letivo inválido.", "error")
            return None, None

        if ano.fechado:
            flash("Ano letivo fechado: apenas consulta.", "error")
            return None, None

        return turma, ano

    def _dt_locked(dt_turma):
        return bool(dt_turma and dt_turma.ano_letivo and dt_turma.ano_letivo.fechado)

    def _dt_ocorrencias_filters(dt_turma):
        args = request.args
        periodo = (args.get("periodo") or "").strip()
        data_inicio = _parse_date_form(args.get("data_inicio"))
        data_fim = _parse_date_form(args.get("data_fim"))
        if periodo in {"semestre1", "semestre2", "anual"}:
            data_inicio, data_fim = _dt_periodo_range(dt_turma, periodo)
        return {
            "periodo": periodo,
            "data_inicio": data_inicio,
            "data_fim": data_fim,
            "disciplina_id": args.get("disciplina_id", type=int),
            "aluno_id": args.get("aluno_id", type=int),
        }

    def _dt_ocorrencias_query(dt_turma, filtros):
        query = DTOcorrencia.query.options(
            joinedload(DTOcorrencia.disciplina),
            joinedload(DTOcorrencia.alunos).joinedload(DTAluno.aluno),
        ).filter(DTOcorrencia.dt_turma_id == dt_turma.id)

        if filtros.get("data_inicio"):
            query = query.filter(DTOcorrencia.data >= filtros["data_inicio"])
        if filtros.get("data_fim"):
            query = query.filter(DTOcorrencia.data <= filtros["data_fim"])
        if filtros.get("disciplina_id"):
            query = query.filter(DTOcorrencia.dt_disciplina_id == filtros["disciplina_id"])
        if filtros.get("aluno_id"):
            query = query.filter(DTOcorrencia.alunos.any(DTAluno.id == filtros["aluno_id"]))
        return query.order_by(DTOcorrencia.data.desc(), DTOcorrencia.hora_inicio.desc(), DTOcorrencia.id.desc())

    def _dt_ordem_dt_aluno(dt_aluno):
        aluno = dt_aluno.aluno
        if not aluno:
            return (1, 1, 9999, "", dt_aluno.id or 0)
        nome_ref = ((aluno.nome_curto_exibicao or aluno.nome or "")).strip().casefold()
        numero = aluno.numero
        return (
            0,
            numero is None,
            numero if numero is not None else 9999,
            nome_ref,
            aluno.id or 0,
        )

    def _dt_ocorrencias_agregado(dt_turma, filtros):
        query = (
            db.session.query(
                DTOcorrenciaAluno.dt_aluno_id.label("dt_aluno_id"),
                DTOcorrencia.dt_disciplina_id.label("dt_disciplina_id"),
                func.count(DTOcorrenciaAluno.id).label("total"),
            )
            .join(DTOcorrencia, DTOcorrencia.id == DTOcorrenciaAluno.dt_ocorrencia_id)
            .filter(DTOcorrencia.dt_turma_id == dt_turma.id)
        )

        if filtros.get("data_inicio"):
            query = query.filter(DTOcorrencia.data >= filtros["data_inicio"])
        if filtros.get("data_fim"):
            query = query.filter(DTOcorrencia.data <= filtros["data_fim"])
        if filtros.get("disciplina_id"):
            query = query.filter(DTOcorrencia.dt_disciplina_id == filtros["disciplina_id"])
        if filtros.get("aluno_id"):
            query = query.filter(DTOcorrenciaAluno.dt_aluno_id == filtros["aluno_id"])

        linhas = (
            query.group_by(
                DTOcorrenciaAluno.dt_aluno_id,
                DTOcorrencia.dt_disciplina_id,
            )
            .all()
        )

        disciplina_ids = sorted(
            {
                linha.dt_disciplina_id
                for linha in linhas
                if linha.dt_disciplina_id is not None
            }
        )
        disciplinas = []
        if disciplina_ids:
            disciplinas = (
                DTDisciplina.query.filter(DTDisciplina.id.in_(disciplina_ids))
                .order_by(DTDisciplina.nome.asc())
                .all()
            )

        dt_aluno_ids = sorted(
            {
                linha.dt_aluno_id
                for linha in linhas
                if linha.dt_aluno_id is not None
            }
        )
        alunos = []
        if dt_aluno_ids:
            alunos = (
                DTAluno.query.options(joinedload(DTAluno.aluno))
                .join(Aluno, DTAluno.aluno_id == Aluno.id)
                .filter(
                    DTAluno.dt_turma_id == dt_turma.id,
                    DTAluno.id.in_(dt_aluno_ids),
                )
                .order_by(
                    Aluno.numero.is_(None),
                    Aluno.numero.asc(),
                    Aluno.nome.asc(),
                )
                .all()
            )

        agregados = {aluno.id: {} for aluno in alunos}
        totais_aluno = {aluno.id: 0 for aluno in alunos}

        for linha in linhas:
            total = int(linha.total or 0)
            agregados.setdefault(linha.dt_aluno_id, {})[linha.dt_disciplina_id] = total
            totais_aluno[linha.dt_aluno_id] = totais_aluno.get(linha.dt_aluno_id, 0) + total

        return {
            "disciplinas": disciplinas,
            "alunos": alunos,
            "agregados": agregados,
            "totais_aluno": totais_aluno,
            "tem_resultados": bool(linhas),
        }

    def _dt_ocorrencia_alunos_linha(ocorrencia):
        alunos = sorted((ocorrencia.alunos or []), key=_dt_ordem_dt_aluno)
        resultado = []
        for dt_aluno in alunos:
            aluno = dt_aluno.aluno
            numero = aluno.numero if aluno else None
            nome_curto = "—"
            if aluno:
                nome_curto = (aluno.nome_curto_exibicao or aluno.nome or "—").strip() or "—"
            resultado.append(
                {
                    "numero": numero,
                    "nome_curto": nome_curto,
                    "dt_aluno_id": dt_aluno.id,
                }
            )
        return resultado

    DT_ALUNO_CARGOS_VALIDOS = {"delegado", "subdelegado"}
    DT_EE_CARGOS_VALIDOS = {"representante_ee", "suplente_representante_ee"}

    def _parse_iso_date(value):
        value = (value or "").strip()
        if not value:
            return None
        return datetime.strptime(value, "%Y-%m-%d").date()

    def _parse_iso_datetime(value):
        value = (value or "").strip()
        if not value:
            return None
        if len(value) == 10:
            return datetime.strptime(value, "%Y-%m-%d")
        return datetime.fromisoformat(value)

    def _ensure_single_active_ee_for_aluno(aluno_id, exclude_id=None):
        q = EEAluno.query.filter(EEAluno.aluno_id == aluno_id, EEAluno.data_fim.is_(None))
        if exclude_id is not None:
            q = q.filter(EEAluno.id != exclude_id)
        return q.first() is None

    def _ensure_single_active_dt_cargo_aluno(dt_turma_id, cargo, exclude_id=None):
        q = DTCargoAluno.query.filter(
            DTCargoAluno.dt_turma_id == dt_turma_id,
            DTCargoAluno.cargo == cargo,
            DTCargoAluno.data_fim.is_(None),
        )
        if exclude_id is not None:
            q = q.filter(DTCargoAluno.id != exclude_id)
        return q.first() is None

    def _ensure_single_active_dt_cargo_ee(dt_turma_id, cargo, exclude_id=None):
        q = DTCargoEE.query.filter(
            DTCargoEE.dt_turma_id == dt_turma_id,
            DTCargoEE.cargo == cargo,
            DTCargoEE.data_fim.is_(None),
        )
        if exclude_id is not None:
            q = q.filter(DTCargoEE.id != exclude_id)
        return q.first() is None

    def _active_ee_rel_for_aluno(aluno_id):
        return (
            EEAluno.query.filter(EEAluno.aluno_id == aluno_id, EEAluno.data_fim.is_(None))
            .order_by(EEAluno.data_inicio.desc(), EEAluno.id.desc())
            .first()
        )

    def _create_contactos_em_lote(dt_turma_id, aluno_ids, base_payload, per_aluno_payload):
        grupos = defaultdict(list)
        for aluno_id in aluno_ids:
            rel = _active_ee_rel_for_aluno(aluno_id)
            if not rel:
                continue
            grupos[rel.ee_id].append((aluno_id, rel.id))

        created_ids = []
        tipo_ids = base_payload.get("tipo_contacto_ids") or []

        for ee_id, alunos_group in grupos.items():
            contacto = Contacto(
                ee_id=ee_id,
                dt_turma_id=dt_turma_id,
                data_hora=base_payload.get("data_hora") or datetime.utcnow(),
                iniciado_por=base_payload.get("iniciado_por") or "professor",
                resumo=base_payload.get("resumo"),
                observacoes_gerais=base_payload.get("observacoes_gerais"),
                estado_contacto=base_payload.get("estado_contacto") or "realizado",
                estado_reuniao=base_payload.get("estado_reuniao") or "nao_agendada",
                data_reuniao=base_payload.get("data_reuniao"),
                requer_followup=bool(base_payload.get("requer_followup")),
                data_followup=base_payload.get("data_followup"),
                confidencial=bool(base_payload.get("confidencial")),
                created_by=base_payload.get("created_by"),
            )
            db.session.add(contacto)
            db.session.flush()
            created_ids.append(contacto.id)

            for tipo_id in tipo_ids:
                db.session.add(ContactoTipo(contacto_id=contacto.id, tipo_contacto_id=tipo_id))

            for aluno_id, rel_id in alunos_group:
                dados_aluno = per_aluno_payload.get(str(aluno_id), {})
                ca = ContactoAluno(
                    contacto_id=contacto.id,
                    aluno_id=aluno_id,
                    ee_aluno_id_snapshot=rel_id,
                    observacoes=dados_aluno.get("observacoes"),
                    resultado_individual=dados_aluno.get("resultado_individual"),
                )
                db.session.add(ca)
                db.session.flush()
                for motivo_item in dados_aluno.get("motivos", []):
                    motivo_id = motivo_item.get("motivo_contacto_id")
                    if not motivo_id:
                        continue
                    db.session.add(
                        ContactoAlunoMotivo(
                            contacto_aluno_id=ca.id,
                            motivo_contacto_id=motivo_id,
                            detalhe=motivo_item.get("detalhe"),
                        )
                    )

        db.session.commit()
        return created_ids

    def _dt_default_start_date(dt_turma):
        if dt_turma and dt_turma.ano_letivo and dt_turma.ano_letivo.data_inicio_ano:
            return dt_turma.ano_letivo.data_inicio_ano
        if dt_turma and dt_turma.ano_letivo and dt_turma.ano_letivo.nome and "/" in str(dt_turma.ano_letivo.nome):
            try:
                ano_ini = int(str(dt_turma.ano_letivo.nome).split("/")[0])
                return date(ano_ini, 9, 1)
            except Exception:
                pass
        return date(date.today().year, 9, 1)

    def _dt_period_range(dt_turma, periodo, data_inicio_raw=None, data_fim_raw=None):
        periodo = (periodo or "anual").strip().lower()
        hoje = date.today()
        inicio = date(hoje.year, 1, 1)
        fim = date(hoje.year, 12, 31)

        ano = dt_turma.ano_letivo if dt_turma else None
        if ano and ano.data_inicio_ano and ano.data_fim_ano:
            inicio = ano.data_inicio_ano
            fim = ano.data_fim_ano

        if periodo == "semestre1" and ano and ano.data_fim_semestre1:
            fim = ano.data_fim_semestre1
        elif periodo == "semestre2" and ano and ano.data_inicio_semestre2 and ano.data_fim_ano:
            inicio = ano.data_inicio_semestre2
            fim = ano.data_fim_ano
        elif periodo == "mes":
            inicio = date(hoje.year, hoje.month, 1)
            fim = date(hoje.year, hoje.month, calendar.monthrange(hoje.year, hoje.month)[1])
        elif periodo == "intervalo":
            inicio = _parse_iso_date(data_inicio_raw) or inicio
            fim = _parse_iso_date(data_fim_raw) or fim

        return inicio, fim

    @app.route("/dt-disciplinas")
    def dt_disciplinas_list():
        termo = (request.args.get("q") or "").strip()
        query = DTDisciplina.query
        if termo:
            query = query.filter((DTDisciplina.nome.ilike(f"%{termo}%")) | (DTDisciplina.nome_curto.ilike(f"%{termo}%")) | (DTDisciplina.professor_nome.ilike(f"%{termo}%")))
        disciplinas = query.order_by(DTDisciplina.nome.asc()).all()
        return render_template("direcao_turma/disciplinas_list.html", disciplinas=disciplinas, termo=termo)

    @app.route("/dt-disciplinas/new", methods=["GET", "POST"])
    def dt_disciplinas_new():
        if request.method == "POST":
            nome = (request.form.get("nome") or "").strip()
            nome_curto = (request.form.get("nome_curto") or "").strip() or _default_nome_curto(nome)
            professor_nome = (request.form.get("professor_nome") or "").strip() or None
            ativa = bool(request.form.get("ativa"))
            if not nome:
                flash("Nome da disciplina é obrigatório.", "error")
                return redirect(url_for("dt_disciplinas_new"))
            existente = DTDisciplina.query.filter(func.lower(DTDisciplina.nome) == nome.lower()).first()
            if existente:
                flash("Já existe uma disciplina com esse nome.", "error")
                return redirect(url_for("dt_disciplinas_new"))
            db.session.add(DTDisciplina(nome=nome, nome_curto=nome_curto or None, professor_nome=professor_nome, ativa=ativa))
            db.session.commit()
            flash("Disciplina criada.", "success")
            return redirect(url_for("dt_disciplinas_list"))
        return render_template("direcao_turma/disciplinas_form.html", disciplina=None)

    @app.route("/dt-disciplinas/<int:disciplina_id>/edit", methods=["GET", "POST"])
    def dt_disciplinas_edit(disciplina_id):
        disciplina = DTDisciplina.query.get_or_404(disciplina_id)
        if request.method == "POST":
            nome = (request.form.get("nome") or "").strip()
            nome_curto = (request.form.get("nome_curto") or "").strip() or _default_nome_curto(nome)
            professor_nome = (request.form.get("professor_nome") or "").strip() or None
            ativa = bool(request.form.get("ativa"))
            if not nome:
                flash("Nome da disciplina é obrigatório.", "error")
                return redirect(url_for("dt_disciplinas_edit", disciplina_id=disciplina.id))
            existente = (
                DTDisciplina.query.filter(func.lower(DTDisciplina.nome) == nome.lower())
                .filter(DTDisciplina.id != disciplina.id)
                .first()
            )
            if existente:
                flash("Já existe uma disciplina com esse nome.", "error")
                return redirect(url_for("dt_disciplinas_edit", disciplina_id=disciplina.id))
            disciplina.nome = nome
            disciplina.nome_curto = nome_curto or None
            disciplina.professor_nome = professor_nome
            disciplina.ativa = ativa
            db.session.commit()
            flash("Disciplina atualizada.", "success")
            return redirect(url_for("dt_disciplinas_list"))
        return render_template("direcao_turma/disciplinas_form.html", disciplina=disciplina)

    @app.route("/dt-disciplinas/<int:disciplina_id>/delete", methods=["POST"])
    def dt_disciplinas_delete(disciplina_id):
        disciplina = DTDisciplina.query.get_or_404(disciplina_id)
        if disciplina.ocorrencias:
            disciplina.ativa = False
            db.session.commit()
            flash("Disciplina em uso: foi desativada.", "warning")
            return redirect(url_for("dt_disciplinas_list"))
        db.session.delete(disciplina)
        db.session.commit()
        flash("Disciplina removida.", "success")
        return redirect(url_for("dt_disciplinas_list"))

    @app.route("/direcao-turma")
    def direcao_turma_list():
        dt_turmas = (
            DTTurma.query.options(
                joinedload(DTTurma.turma),
                joinedload(DTTurma.ano_letivo),
            )
            .outerjoin(AnoLetivo, DTTurma.ano_letivo_id == AnoLetivo.id)
            .outerjoin(Turma, DTTurma.turma_id == Turma.id)
            .order_by(
                AnoLetivo.ativo.desc(),
                AnoLetivo.fechado.asc(),
                AnoLetivo.data_inicio_ano.desc(),
                Turma.nome,
            )
            .all()
        )

        dt_abertas = [
            dt for dt in dt_turmas if not (dt.ano_letivo and dt.ano_letivo.fechado)
        ]
        dt_fechadas = [
            dt for dt in dt_turmas if dt.ano_letivo and dt.ano_letivo.fechado
        ]

        dt_ids = [dt.id for dt in dt_turmas]
        cargos_resumo = {
            dt_id: {
                "delegado": "—",
                "subdelegado": "—",
                "representante_ee": "—",
                "suplente_representante_ee": "—",
            }
            for dt_id in dt_ids
        }

        if dt_ids:
            cargos_alunos_ativos = (
                DTCargoAluno.query.options(joinedload(DTCargoAluno.aluno))
                .filter(DTCargoAluno.dt_turma_id.in_(dt_ids), DTCargoAluno.data_fim.is_(None))
                .order_by(DTCargoAluno.id.desc())
                .all()
            )
            for cargo in cargos_alunos_ativos:
                if cargo.cargo in {"delegado", "subdelegado"}:
                    cargos_resumo[cargo.dt_turma_id][cargo.cargo] = cargo.aluno.nome if cargo.aluno else "—"

            cargos_ee_ativos = (
                DTCargoEE.query.options(joinedload(DTCargoEE.ee))
                .filter(DTCargoEE.dt_turma_id.in_(dt_ids), DTCargoEE.data_fim.is_(None))
                .order_by(DTCargoEE.id.desc())
                .all()
            )
            for cargo in cargos_ee_ativos:
                if cargo.cargo in {"representante_ee", "suplente_representante_ee"}:
                    cargos_resumo[cargo.dt_turma_id][cargo.cargo] = cargo.ee.nome if cargo.ee else "—"

        return render_template(
            "direcao_turma/list.html",
            dt_abertas=dt_abertas,
            dt_fechadas=dt_fechadas,
            cargos_resumo=cargos_resumo,
        )

    @app.route("/direcao-turma/justificacoes-texto")
    def direcao_turma_justificacoes_texto_list():
        textos = DTJustificacaoTexto.query.order_by(DTJustificacaoTexto.titulo.asc(), DTJustificacaoTexto.id.asc()).all()
        return render_template("direcao_turma/justificacoes_texto_list.html", textos=textos)

    @app.route("/direcao-turma/justificacoes-texto/add", methods=["GET", "POST"])
    def direcao_turma_justificacoes_texto_add():
        if request.method == "POST":
            titulo = (request.form.get("titulo") or "").strip()
            texto = (request.form.get("texto") or "").strip()
            if not titulo or not texto:
                flash("Preenche título e texto.", "error")
                return redirect(url_for("direcao_turma_justificacoes_texto_add"))

            novo = DTJustificacaoTexto(titulo=titulo[:120], texto=texto)
            db.session.add(novo)
            db.session.commit()
            flash("Texto de justificação criado.", "success")
            return redirect(url_for("direcao_turma_justificacoes_texto_list"))

        return render_template(
            "direcao_turma/justificacoes_texto_form.html",
            titulo_pagina="Novo texto de justificação",
            item=None,
        )

    @app.route("/direcao-turma/justificacoes-texto/<int:item_id>/edit", methods=["GET", "POST"])
    def direcao_turma_justificacoes_texto_edit(item_id):
        item = DTJustificacaoTexto.query.get_or_404(item_id)
        if request.method == "POST":
            titulo = (request.form.get("titulo") or "").strip()
            texto = (request.form.get("texto") or "").strip()
            if not titulo or not texto:
                flash("Preenche título e texto.", "error")
                return redirect(url_for("direcao_turma_justificacoes_texto_edit", item_id=item.id))

            item.titulo = titulo[:120]
            item.texto = texto
            db.session.commit()
            flash("Texto de justificação atualizado.", "success")
            return redirect(url_for("direcao_turma_justificacoes_texto_list"))

        return render_template(
            "direcao_turma/justificacoes_texto_form.html",
            titulo_pagina="Editar texto de justificação",
            item=item,
        )

    @app.route("/direcao-turma/justificacoes-texto/<int:item_id>/delete", methods=["POST"])
    def direcao_turma_justificacoes_texto_delete(item_id):
        item = DTJustificacaoTexto.query.get_or_404(item_id)
        db.session.delete(item)
        db.session.commit()
        flash("Texto de justificação removido.", "success")
        return redirect(url_for("direcao_turma_justificacoes_texto_list"))

    @app.route("/direcao-turma/alunos/<int:aluno_id>/contexto", methods=["GET", "POST"])
    def direcao_turma_aluno_contexto(aluno_id):
        aluno = Aluno.query.get_or_404(aluno_id)
        contexto = AlunoContextoDT.query.filter_by(aluno_id=aluno.id).first()
        if request.method == "POST":
            if not contexto:
                contexto = AlunoContextoDT(aluno_id=aluno.id)
                db.session.add(contexto)
            contexto.dt_observacoes = request.form.get("dt_observacoes") or None
            contexto.ee_observacoes = request.form.get("ee_observacoes") or None
            contexto.alerta_dt = request.form.get("alerta_dt") or None
            contexto.resumo_sinalizacao = request.form.get("resumo_sinalizacao") or None
            db.session.commit()
            return jsonify({"ok": True, "contexto_id": contexto.id})
        return jsonify({
            "aluno_id": aluno.id,
            "contexto": {
                "id": contexto.id if contexto else None,
                "dt_observacoes": contexto.dt_observacoes if contexto else None,
                "ee_observacoes": contexto.ee_observacoes if contexto else None,
                "alerta_dt": contexto.alerta_dt if contexto else None,
                "resumo_sinalizacao": contexto.resumo_sinalizacao if contexto else None,
            },
        })

    @app.route("/direcao-turma/ee", methods=["POST"])
    def direcao_turma_ee_create():
        nome = (request.form.get("nome") or "").strip()
        if not nome:
            return jsonify({"ok": False, "error": "Nome é obrigatório."}), 400
        ee = EncarregadoEducacao(
            nome=nome,
            telefone=(request.form.get("telefone") or "").strip() or None,
            email=(request.form.get("email") or "").strip() or None,
            observacoes=request.form.get("observacoes") or None,
            nome_alternativo=(request.form.get("nome_alternativo") or "").strip() or None,
            telefone_alternativo=(request.form.get("telefone_alternativo") or "").strip() or None,
            email_alternativo=(request.form.get("email_alternativo") or "").strip() or None,
        )
        db.session.add(ee)
        db.session.commit()
        return jsonify({"ok": True, "id": ee.id})

    @app.route("/direcao-turma/ee-alunos", methods=["POST"])
    def direcao_turma_ee_aluno_create():
        ee_id = request.form.get("ee_id", type=int)
        aluno_id = request.form.get("aluno_id", type=int)
        data_inicio = _parse_iso_date(request.form.get("data_inicio"))
        if not (ee_id and aluno_id and data_inicio):
            return jsonify({"ok": False, "error": "ee_id, aluno_id e data_inicio são obrigatórios."}), 400
        if not _ensure_single_active_ee_for_aluno(aluno_id):
            return jsonify({"ok": False, "error": "Já existe relação EE ativa para este aluno."}), 409
        rel = EEAluno(
            ee_id=ee_id,
            aluno_id=aluno_id,
            parentesco=(request.form.get("parentesco") or "").strip() or None,
            observacoes=request.form.get("observacoes") or None,
            data_inicio=data_inicio,
            data_fim=_parse_iso_date(request.form.get("data_fim")),
        )
        db.session.add(rel)
        db.session.commit()
        return jsonify({"ok": True, "id": rel.id})

    @app.route("/direcao-turma/cargos/aluno", methods=["POST"])
    def direcao_turma_cargo_aluno_create():
        dt_turma_id = request.form.get("dt_turma_id", type=int)
        aluno_id = request.form.get("aluno_id", type=int)
        cargo = (request.form.get("cargo") or "").strip()
        data_inicio = _parse_iso_date(request.form.get("data_inicio"))
        if cargo not in DT_ALUNO_CARGOS_VALIDOS:
            return jsonify({"ok": False, "error": "Cargo inválido."}), 400
        if not _ensure_single_active_dt_cargo_aluno(dt_turma_id, cargo):
            return jsonify({"ok": False, "error": f"Já existe {cargo} ativo nesta DT."}), 409
        item = DTCargoAluno(
            dt_turma_id=dt_turma_id,
            aluno_id=aluno_id,
            cargo=cargo,
            data_inicio=data_inicio,
            data_fim=_parse_iso_date(request.form.get("data_fim")),
            motivo_fim=request.form.get("motivo_fim") or None,
        )
        db.session.add(item)
        db.session.commit()
        return jsonify({"ok": True, "id": item.id})

    @app.route("/direcao-turma/cargos/ee", methods=["POST"])
    def direcao_turma_cargo_ee_create():
        dt_turma_id = request.form.get("dt_turma_id", type=int)
        ee_id = request.form.get("ee_id", type=int)
        cargo = (request.form.get("cargo") or "").strip()
        data_inicio = _parse_iso_date(request.form.get("data_inicio"))
        if cargo not in DT_EE_CARGOS_VALIDOS:
            return jsonify({"ok": False, "error": "Cargo inválido."}), 400
        if not _ensure_single_active_dt_cargo_ee(dt_turma_id, cargo):
            return jsonify({"ok": False, "error": f"Já existe {cargo} ativo nesta DT."}), 409
        item = DTCargoEE(
            dt_turma_id=dt_turma_id,
            ee_id=ee_id,
            cargo=cargo,
            data_inicio=data_inicio,
            data_fim=_parse_iso_date(request.form.get("data_fim")),
            motivo_fim=request.form.get("motivo_fim") or None,
        )
        db.session.add(item)
        db.session.commit()
        return jsonify({"ok": True, "id": item.id})

    @app.route("/direcao-turma/contactos/lote", methods=["POST"])
    def direcao_turma_contactos_lote_create():
        payload = request.get_json(silent=True) or {}
        dt_turma_id = payload.get("dt_turma_id")
        aluno_ids = payload.get("aluno_ids") or []
        if not dt_turma_id or not aluno_ids:
            return jsonify({"ok": False, "error": "dt_turma_id e aluno_ids são obrigatórios."}), 400

        base_payload = {
            "data_hora": _parse_iso_datetime(payload.get("data_hora")) if payload.get("data_hora") else datetime.utcnow(),
            "iniciado_por": payload.get("iniciado_por") or "professor",
            "resumo": payload.get("resumo"),
            "observacoes_gerais": payload.get("observacoes_gerais"),
            "estado_contacto": payload.get("estado_contacto") or "realizado",
            "estado_reuniao": payload.get("estado_reuniao") or "nao_agendada",
            "data_reuniao": _parse_iso_datetime(payload.get("data_reuniao")) if payload.get("data_reuniao") else None,
            "requer_followup": bool(payload.get("requer_followup")),
            "data_followup": _parse_iso_date(payload.get("data_followup")) if payload.get("data_followup") else None,
            "confidencial": bool(payload.get("confidencial")),
            "created_by": payload.get("created_by"),
            "tipo_contacto_ids": payload.get("tipo_contacto_ids") or [],
        }
        created_ids = _create_contactos_em_lote(
            dt_turma_id=dt_turma_id,
            aluno_ids=aluno_ids,
            base_payload=base_payload,
            per_aluno_payload=payload.get("por_aluno") or {},
        )
        return jsonify({"ok": True, "created_contactos": created_ids})

    @app.route("/direcao-turma/export/ee.csv")
    def direcao_turma_export_ee_csv():
        dt_turma_id = request.args.get("dt_turma_id", type=int)
        apenas_ativos = (request.args.get("ativos") or "1") == "1"
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "aluno_numero", "aluno_nome", "ee_nome", "parentesco", "telefone", "email",
            "nome_alternativo", "telefone_alternativo", "email_alternativo", "observacoes", "data_inicio", "data_fim",
        ])
        query = (
            EEAluno.query
            .join(Aluno, EEAluno.aluno_id == Aluno.id)
            .join(EncarregadoEducacao, EEAluno.ee_id == EncarregadoEducacao.id)
        )
        if dt_turma_id:
            dt_turma = DTTurma.query.get(dt_turma_id)
            if dt_turma:
                query = query.filter(Aluno.turma_id == dt_turma.turma_id)
        if apenas_ativos:
            query = query.filter(EEAluno.data_fim.is_(None))
        for rel in query.order_by(Aluno.numero.asc(), Aluno.nome.asc()).all():
            writer.writerow([
                rel.aluno.numero,
                rel.aluno.nome,
                rel.ee.nome,
                rel.parentesco or "",
                rel.ee.telefone or "",
                rel.ee.email or "",
                rel.ee.nome_alternativo or "",
                rel.ee.telefone_alternativo or "",
                rel.ee.email_alternativo or "",
                rel.observacoes or "",
                rel.data_inicio.isoformat() if rel.data_inicio else "",
                rel.data_fim.isoformat() if rel.data_fim else "",
            ])
        filename = f"ee_export_{dt_turma_id or 'all'}.csv"
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename={filename}"})

    @app.route("/direcao-turma/export/contactos.csv")
    def direcao_turma_export_contactos_csv():
        periodo = (request.args.get("periodo") or "anual").strip().lower()
        dt_turma_id = request.args.get("dt_turma_id", type=int)
        ee_id = request.args.get("ee_id", type=int)
        aluno_id = request.args.get("aluno_id", type=int)
        tipo_contacto_id = request.args.get("tipo_contacto_id", type=int)
        motivo_contacto_id = request.args.get("motivo_contacto_id", type=int)

        hoje = date.today()
        inicio = date(hoje.year, 1, 1)
        fim = date(hoje.year, 12, 31)
        if periodo == "semestre1":
            fim = date(hoje.year, 6, 30)
        elif periodo == "semestre2":
            inicio = date(hoje.year, 7, 1)
        elif periodo == "mes":
            inicio = date(hoje.year, hoje.month, 1)
            fim = date(hoje.year, hoje.month, calendar.monthrange(hoje.year, hoje.month)[1])
        elif periodo == "intervalo":
            inicio = _parse_iso_date(request.args.get("data_inicio")) or inicio
            fim = _parse_iso_date(request.args.get("data_fim")) or fim

        query = Contacto.query.join(EncarregadoEducacao, Contacto.ee_id == EncarregadoEducacao.id)
        query = query.filter(func.date(Contacto.data_hora) >= inicio, func.date(Contacto.data_hora) <= fim)
        if dt_turma_id:
            query = query.filter(Contacto.dt_turma_id == dt_turma_id)
        if ee_id:
            query = query.filter(Contacto.ee_id == ee_id)
        if tipo_contacto_id:
            query = query.join(ContactoTipo, ContactoTipo.contacto_id == Contacto.id).filter(ContactoTipo.tipo_contacto_id == tipo_contacto_id)
        if aluno_id:
            query = query.join(ContactoAluno, ContactoAluno.contacto_id == Contacto.id).filter(ContactoAluno.aluno_id == aluno_id)
        if motivo_contacto_id:
            query = query.join(ContactoAluno, ContactoAluno.contacto_id == Contacto.id).join(ContactoAlunoMotivo, ContactoAlunoMotivo.contacto_aluno_id == ContactoAluno.id).filter(ContactoAlunoMotivo.motivo_contacto_id == motivo_contacto_id)

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "data", "hora", "ee", "aluno_ou_alunos", "turma", "iniciado_por", "tipos_contacto", "motivos", "resumo",
            "observacoes_gerais", "estado_contacto", "estado_reuniao", "data_reuniao", "requer_followup", "data_followup", "confidencial", "links_externos",
        ])
        for c in query.order_by(Contacto.data_hora.desc()).all():
            alunos = [ca.aluno.nome for ca in ContactoAluno.query.join(Aluno).filter(ContactoAluno.contacto_id == c.id).all()]
            tipos = [t.nome for t in TipoContacto.query.join(ContactoTipo, ContactoTipo.tipo_contacto_id == TipoContacto.id).filter(ContactoTipo.contacto_id == c.id).all()]
            motivos = [m.nome for m in MotivoContacto.query.join(ContactoAlunoMotivo, ContactoAlunoMotivo.motivo_contacto_id == MotivoContacto.id).join(ContactoAluno, ContactoAluno.id == ContactoAlunoMotivo.contacto_aluno_id).filter(ContactoAluno.contacto_id == c.id).distinct().all()]
            links = [l.url for l in ContactoLink.query.filter_by(contacto_id=c.id).all()]
            dt_turma = DTTurma.query.get(c.dt_turma_id)
            writer.writerow([
                c.data_hora.date().isoformat() if c.data_hora else "",
                c.data_hora.time().isoformat(timespec="minutes") if c.data_hora else "",
                c.ee.nome if c.ee else "",
                " | ".join(alunos),
                dt_turma.turma.nome if dt_turma and dt_turma.turma else "",
                c.iniciado_por,
                " | ".join(tipos),
                " | ".join(motivos),
                c.resumo or "",
                c.observacoes_gerais or "",
                c.estado_contacto,
                c.estado_reuniao,
                c.data_reuniao.isoformat() if c.data_reuniao else "",
                "1" if c.requer_followup else "0",
                c.data_followup.isoformat() if c.data_followup else "",
                "1" if c.confidencial else "0",
                " | ".join(links),
            ])
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=contactos_export.csv"})

    @app.route("/direcao-turma/<int:dt_id>/ee")
    def direcao_turma_ee_list(dt_id):
        dt_turma = DTTurma.query.options(joinedload(DTTurma.turma), joinedload(DTTurma.ano_letivo)).get_or_404(dt_id)
        filtro = (request.args.get("filtro") or "todos").strip().lower()
        if filtro not in {"todos", "sem_associacao", "ativos", "historico"}:
            filtro = "todos"

        ees = EncarregadoEducacao.query.order_by(EncarregadoEducacao.nome.asc()).all()
        rels = (
            EEAluno.query
            .join(Aluno, EEAluno.aluno_id == Aluno.id)
            .filter(Aluno.turma_id == dt_turma.turma_id)
            .order_by(EEAluno.data_inicio.desc())
            .all()
        )

        rels_por_ee = {}
        for rel in rels:
            rels_por_ee.setdefault(rel.ee_id, []).append(rel)

        ee_items = []
        for ee in ees:
            historico = rels_por_ee.get(ee.id, [])
            ativos = [item for item in historico if item.data_fim is None]
            if not historico:
                estado = "sem_associacao"
            elif ativos:
                estado = "ativos"
            else:
                estado = "historico"

            if filtro != "todos" and estado != filtro:
                continue

            ee_items.append(
                {
                    "ee": ee,
                    "ativos": ativos,
                    "historico": historico,
                    "estado": estado,
                }
            )

        return render_template(
            "direcao_turma/ee_list.html",
            dt_turma=dt_turma,
            ee_items=ee_items,
            filtro=filtro,
        )

    @app.route("/direcao-turma/<int:dt_id>/ee/novo", methods=["GET", "POST"])
    def direcao_turma_ee_new(dt_id):
        dt_turma = DTTurma.query.options(joinedload(DTTurma.ano_letivo), joinedload(DTTurma.turma)).get_or_404(dt_id)
        bloqueado = bool(dt_turma.ano_letivo and dt_turma.ano_letivo.fechado)
        if request.method == "POST":
            if bloqueado:
                flash("Ano letivo fechado: apenas consulta.", "error")
                return redirect(url_for("direcao_turma_ee_list", dt_id=dt_id))
            nome = (request.form.get("nome") or "").strip()
            if not nome:
                flash("Nome é obrigatório.", "error")
                return redirect(url_for("direcao_turma_ee_new", dt_id=dt_id))
            ee = EncarregadoEducacao(
                nome=nome,
                telefone=(request.form.get("telefone") or "").strip() or None,
                email=(request.form.get("email") or "").strip() or None,
                observacoes=request.form.get("observacoes") or None,
                nome_alternativo=(request.form.get("nome_alternativo") or "").strip() or None,
                telefone_alternativo=(request.form.get("telefone_alternativo") or "").strip() or None,
                email_alternativo=(request.form.get("email_alternativo") or "").strip() or None,
            )
            db.session.add(ee)
            db.session.commit()
            flash("EE criado.", "success")
            submit_action = (request.form.get("submit_action") or "save").strip()
            if submit_action == "save_new":
                return redirect(url_for("direcao_turma_ee_new", dt_id=dt_id))
            if submit_action == "save_back":
                return redirect(url_for("direcao_turma_alunos", dt_id=dt_id))
            return redirect(url_for("direcao_turma_ee_detail", dt_id=dt_id, ee_id=ee.id))

        return render_template("direcao_turma/ee_form.html", dt_turma=dt_turma, bloqueado=bloqueado, ee=None, is_edit=False)

    @app.route("/direcao-turma/<int:dt_id>/ee/<int:ee_id>/edit", methods=["GET", "POST"])
    def direcao_turma_ee_edit(dt_id, ee_id):
        dt_turma = DTTurma.query.options(joinedload(DTTurma.turma), joinedload(DTTurma.ano_letivo)).get_or_404(dt_id)
        ee = EncarregadoEducacao.query.get_or_404(ee_id)
        bloqueado = bool(dt_turma.ano_letivo and dt_turma.ano_letivo.fechado)
        if request.method == "POST":
            if bloqueado:
                flash("Ano letivo fechado: apenas consulta.", "error")
                return redirect(url_for("direcao_turma_ee_detail", dt_id=dt_id, ee_id=ee_id))
            nome = (request.form.get("nome") or "").strip()
            if not nome:
                flash("Nome é obrigatório.", "error")
                return redirect(url_for("direcao_turma_ee_edit", dt_id=dt_id, ee_id=ee_id))
            ee.nome = nome
            ee.telefone = (request.form.get("telefone") or "").strip() or None
            ee.email = (request.form.get("email") or "").strip() or None
            ee.observacoes = request.form.get("observacoes") or None
            ee.nome_alternativo = (request.form.get("nome_alternativo") or "").strip() or None
            ee.telefone_alternativo = (request.form.get("telefone_alternativo") or "").strip() or None
            ee.email_alternativo = (request.form.get("email_alternativo") or "").strip() or None
            db.session.commit()
            flash("EE atualizado.", "success")
            return redirect(url_for("direcao_turma_ee_detail", dt_id=dt_id, ee_id=ee_id))
        return render_template("direcao_turma/ee_form.html", dt_turma=dt_turma, bloqueado=bloqueado, ee=ee, is_edit=True)

    @app.route("/direcao-turma/<int:dt_id>/ee/<int:ee_id>/associar", methods=["POST"])
    def direcao_turma_ee_associar_aluno(dt_id, ee_id):
        dt_turma = DTTurma.query.options(joinedload(DTTurma.ano_letivo)).get_or_404(dt_id)
        if dt_turma.ano_letivo and dt_turma.ano_letivo.fechado:
            flash("Ano letivo fechado: apenas consulta.", "error")
            return redirect(url_for("direcao_turma_ee_detail", dt_id=dt_id, ee_id=ee_id))
        aluno_id = request.form.get("aluno_id", type=int)
        if not aluno_id:
            flash("Seleciona um aluno.", "error")
            return redirect(url_for("direcao_turma_ee_detail", dt_id=dt_id, ee_id=ee_id))
        aluno = Aluno.query.get(aluno_id)
        if not aluno or aluno.turma_id != dt_turma.turma_id:
            flash("Aluno inválido para esta DT.", "error")
            return redirect(url_for("direcao_turma_ee_detail", dt_id=dt_id, ee_id=ee_id))
        default_inicio = dt_turma.ano_letivo.data_inicio_ano if (dt_turma.ano_letivo and dt_turma.ano_letivo.data_inicio_ano) else date(date.today().year, 9, 1)
        inicio = _parse_iso_date(request.form.get("data_inicio")) or default_inicio
        parentesco_base = (request.form.get("parentesco") or "").strip()
        parentesco_outro = (request.form.get("parentesco_outro") or "").strip()
        parentesco = parentesco_base
        if parentesco_base == "Outro" and parentesco_outro:
            parentesco = f"Outro: {parentesco_outro}"
        elif not parentesco_base:
            parentesco = None
        atual = _active_ee_rel_for_aluno(aluno_id)
        if atual and atual.data_inicio and inicio <= atual.data_inicio:
            flash("A nova data de início deve ser posterior à relação ativa atual.", "error")
            return redirect(url_for("direcao_turma_ee_detail", dt_id=dt_id, ee_id=ee_id))
        if atual:
            atual.data_fim = inicio - timedelta(days=1)
        db.session.add(EEAluno(ee_id=ee_id, aluno_id=aluno_id, parentesco=parentesco, observacoes=request.form.get("observacoes") or None, data_inicio=inicio))
        db.session.commit()
        flash("Aluno associado ao EE.", "success")
        return redirect(url_for("direcao_turma_ee_detail", dt_id=dt_id, ee_id=ee_id))

    @app.route("/direcao-turma/ee-alunos/<int:rel_id>/edit", methods=["GET", "POST"])
    def direcao_turma_ee_aluno_edit(rel_id):
        rel = EEAluno.query.options(joinedload(EEAluno.ee), joinedload(EEAluno.aluno)).get_or_404(rel_id)
        dt_id = request.args.get("dt_id", type=int) or request.form.get("dt_id", type=int)
        dt_turma = DTTurma.query.get(dt_id) if dt_id else None
        if not dt_turma and rel.aluno:
            dt_turma = (
                DTTurma.query.options(joinedload(DTTurma.ano_letivo), joinedload(DTTurma.turma))
                .filter(DTTurma.turma_id == rel.aluno.turma_id)
                .order_by(DTTurma.id.desc())
                .first()
            )
        ees = EncarregadoEducacao.query.order_by(EncarregadoEducacao.nome.asc()).all()
        alunos = Aluno.query.order_by(Aluno.nome.asc()).all()

        if request.method == "POST":
            action = (request.form.get("action") or "save").strip().lower()
            if action == "terminar":
                fim = _parse_iso_date(request.form.get("data_fim")) or date.today()
                if rel.data_inicio and fim < rel.data_inicio:
                    flash("Data de fim inválida: anterior à data de início.", "error")
                    return redirect(url_for("direcao_turma_ee_aluno_edit", rel_id=rel.id, dt_id=dt_turma.id if dt_turma else None))
                rel.data_fim = fim
                obs_term = (request.form.get("observacoes_termino") or "").strip()
                if obs_term:
                    rel.observacoes = ((rel.observacoes or "").strip() + "\n" if rel.observacoes else "") + f"Termino: {obs_term}"
                db.session.commit()
                flash("Associação terminada.", "success")
                return redirect(url_for("direcao_turma_ee_aluno_edit", rel_id=rel.id, dt_id=dt_turma.id if dt_turma else None))

            if action == "reabrir":
                if not _ensure_single_active_ee_for_aluno(rel.aluno_id, exclude_id=rel.id):
                    flash("Não é possível reabrir: já existe associação ativa para este aluno.", "error")
                    return redirect(url_for("direcao_turma_ee_aluno_edit", rel_id=rel.id, dt_id=dt_turma.id if dt_turma else None))
                rel.data_fim = None
                db.session.commit()
                flash("Associação reaberta.", "success")
                return redirect(url_for("direcao_turma_ee_aluno_edit", rel_id=rel.id, dt_id=dt_turma.id if dt_turma else None))

            ee_id = request.form.get("ee_id", type=int)
            aluno_id = request.form.get("aluno_id", type=int)
            data_inicio = _parse_iso_date(request.form.get("data_inicio"))
            data_fim = _parse_iso_date(request.form.get("data_fim")) if request.form.get("data_fim") else None
            parentesco_base = (request.form.get("parentesco") or "").strip()
            parentesco_outro = (request.form.get("parentesco_outro") or "").strip()
            parentesco = parentesco_base
            if parentesco_base == "Outro" and parentesco_outro:
                parentesco = f"Outro: {parentesco_outro}"
            elif not parentesco_base:
                parentesco = None

            if not ee_id or not aluno_id or not data_inicio:
                flash("EE, aluno e data de início são obrigatórios.", "error")
                return redirect(url_for("direcao_turma_ee_aluno_edit", rel_id=rel.id, dt_id=dt_turma.id if dt_turma else None))
            if data_fim and data_fim < data_inicio:
                flash("Data de fim inválida: anterior à data de início.", "error")
                return redirect(url_for("direcao_turma_ee_aluno_edit", rel_id=rel.id, dt_id=dt_turma.id if dt_turma else None))
            if data_fim is None and not _ensure_single_active_ee_for_aluno(aluno_id, exclude_id=rel.id):
                flash("Já existe associação ativa para este aluno.", "error")
                return redirect(url_for("direcao_turma_ee_aluno_edit", rel_id=rel.id, dt_id=dt_turma.id if dt_turma else None))

            rel.ee_id = ee_id
            rel.aluno_id = aluno_id
            rel.parentesco = parentesco
            rel.observacoes = request.form.get("observacoes") or None
            rel.data_inicio = data_inicio
            rel.data_fim = data_fim
            db.session.commit()
            flash("Associação EE↔aluno atualizada.", "success")
            return redirect(url_for("direcao_turma_ee_aluno_edit", rel_id=rel.id, dt_id=dt_turma.id if dt_turma else None))

        return render_template(
            "direcao_turma/ee_aluno_edit.html",
            rel=rel,
            dt_turma=dt_turma,
            ees=ees,
            alunos=alunos,
        )

    @app.route("/direcao-turma/<int:dt_id>/ee/<int:ee_id>")
    def direcao_turma_ee_detail(dt_id, ee_id):
        dt_turma = DTTurma.query.options(joinedload(DTTurma.turma), joinedload(DTTurma.ano_letivo)).get_or_404(dt_id)
        ee = EncarregadoEducacao.query.get_or_404(ee_id)
        rels = (
            EEAluno.query
            .join(Aluno, EEAluno.aluno_id == Aluno.id)
            .filter(EEAluno.ee_id == ee.id, Aluno.turma_id == dt_turma.turma_id)
            .order_by(EEAluno.data_inicio.desc())
            .all()
        )
        contactos = (
            Contacto.query.filter_by(dt_turma_id=dt_turma.id, ee_id=ee.id)
            .order_by(Contacto.data_hora.desc())
            .limit(30)
            .all()
        )
        contacto_ids = [c.id for c in contactos]
        tipos_por_contacto = {}
        alunos_por_contacto = {}
        if contacto_ids:
            tipo_rows = (
                db.session.query(ContactoTipo.contacto_id, TipoContacto.nome)
                .join(TipoContacto, TipoContacto.id == ContactoTipo.tipo_contacto_id)
                .filter(ContactoTipo.contacto_id.in_(contacto_ids))
                .all()
            )
            for cid, nome_tipo in tipo_rows:
                tipos_por_contacto.setdefault(cid, []).append(nome_tipo)

            aluno_rows = (
                db.session.query(ContactoAluno.contacto_id, Aluno.numero, Aluno.nome)
                .join(Aluno, Aluno.id == ContactoAluno.aluno_id)
                .filter(ContactoAluno.contacto_id.in_(contacto_ids))
                .all()
            )
            for cid, num, nome_aluno in aluno_rows:
                label = f"{num} - {nome_aluno}" if num is not None else nome_aluno
                alunos_por_contacto.setdefault(cid, []).append(label)

        alunos_dt = Aluno.query.filter_by(turma_id=dt_turma.turma_id).order_by(Aluno.numero.asc(), Aluno.nome.asc()).all()
        default_associar_inicio = None
        if dt_turma.ano_letivo and dt_turma.ano_letivo.data_inicio_ano:
            default_associar_inicio = dt_turma.ano_letivo.data_inicio_ano
        elif dt_turma.ano_letivo and dt_turma.ano_letivo.nome and "/" in dt_turma.ano_letivo.nome:
            try:
                default_associar_inicio = date(int(str(dt_turma.ano_letivo.nome).split("/")[0]), 9, 1)
            except Exception:
                default_associar_inicio = date(date.today().year, 9, 1)
        else:
            default_associar_inicio = date(date.today().year, 9, 1)

        return render_template(
            "direcao_turma/ee_detail.html",
            dt_turma=dt_turma,
            ee=ee,
            rels=rels,
            contactos=contactos,
            tipos_por_contacto=tipos_por_contacto,
            alunos_por_contacto=alunos_por_contacto,
            alunos_dt=alunos_dt,
            default_associar_inicio=default_associar_inicio,
        )

    @app.route("/direcao-turma/<int:dt_id>/alunos/<int:dt_aluno_id>/contexto", methods=["GET", "POST"])
    def direcao_turma_aluno_contexto_page(dt_id, dt_aluno_id):
        dt_turma = DTTurma.query.options(joinedload(DTTurma.ano_letivo), joinedload(DTTurma.turma)).get_or_404(dt_id)
        dt_aluno = DTAluno.query.options(joinedload(DTAluno.aluno)).filter_by(id=dt_aluno_id, dt_turma_id=dt_turma.id).first_or_404()
        contexto = AlunoContextoDT.query.filter_by(aluno_id=dt_aluno.aluno_id).first()
        bloqueado = bool(dt_turma.ano_letivo and dt_turma.ano_letivo.fechado)
        if request.method == "POST":
            if bloqueado:
                flash("Ano letivo fechado: apenas consulta.", "error")
                return redirect(url_for("direcao_turma_aluno_contexto_page", dt_id=dt_id, dt_aluno_id=dt_aluno_id))
            if not contexto:
                contexto = AlunoContextoDT(aluno_id=dt_aluno.aluno_id)
                db.session.add(contexto)
            contexto.dt_observacoes = request.form.get("dt_observacoes") or None
            contexto.ee_observacoes = request.form.get("ee_observacoes") or None
            contexto.alerta_dt = request.form.get("alerta_dt") or None
            contexto.resumo_sinalizacao = request.form.get("resumo_sinalizacao") or None
            db.session.commit()
            flash("Contexto DT atualizado.", "success")
            return redirect(url_for("direcao_turma_alunos", dt_id=dt_id))
        return render_template("direcao_turma/aluno_contexto_form.html", dt_turma=dt_turma, dt_aluno=dt_aluno, contexto=contexto, bloqueado=bloqueado)

    @app.route("/direcao-turma/<int:dt_id>/alunos/<int:dt_aluno_id>/ee", methods=["GET", "POST"])
    def direcao_turma_aluno_ee_edit(dt_id, dt_aluno_id):
        dt_turma = DTTurma.query.options(joinedload(DTTurma.ano_letivo), joinedload(DTTurma.turma)).get_or_404(dt_id)
        dt_aluno = DTAluno.query.options(joinedload(DTAluno.aluno)).filter_by(id=dt_aluno_id, dt_turma_id=dt_turma.id).first_or_404()
        bloqueado = bool(dt_turma.ano_letivo and dt_turma.ano_letivo.fechado)
        atual = _active_ee_rel_for_aluno(dt_aluno.aluno_id)
        historico = (
            EEAluno.query.options(joinedload(EEAluno.ee))
            .filter(EEAluno.aluno_id == dt_aluno.aluno_id)
            .order_by(EEAluno.data_inicio.desc())
            .all()
        )
        ees = EncarregadoEducacao.query.order_by(EncarregadoEducacao.nome.asc()).all()

        default_inicio = None
        if dt_turma.ano_letivo and dt_turma.ano_letivo.data_inicio_ano:
            default_inicio = dt_turma.ano_letivo.data_inicio_ano
        elif dt_turma.ano_letivo and dt_turma.ano_letivo.nome and "/" in dt_turma.ano_letivo.nome:
            try:
                ano_ini = int(str(dt_turma.ano_letivo.nome).split("/")[0])
                default_inicio = date(ano_ini, 9, 1)
            except Exception:
                default_inicio = date(date.today().year, 9, 1)
        else:
            default_inicio = date(date.today().year, 9, 1)

        if request.method == "POST":
            if bloqueado:
                flash("Ano letivo fechado: apenas consulta.", "error")
                return redirect(url_for("direcao_turma_aluno_ee_edit", dt_id=dt_id, dt_aluno_id=dt_aluno_id))
            ee_id = request.form.get("ee_id", type=int)
            data_inicio = _parse_iso_date(request.form.get("data_inicio")) or default_inicio
            parentesco_base = (request.form.get("parentesco") or "").strip()
            parentesco_outro = (request.form.get("parentesco_outro") or "").strip()
            parentesco = parentesco_base
            if parentesco_base == "Outro" and parentesco_outro:
                parentesco = f"Outro: {parentesco_outro}"
            elif not parentesco_base:
                parentesco = None
            observacoes = request.form.get("observacoes") or None
            if not ee_id:
                flash("Seleciona um EE.", "error")
                return redirect(url_for("direcao_turma_aluno_ee_edit", dt_id=dt_id, dt_aluno_id=dt_aluno_id))
            if atual and atual.data_inicio and data_inicio <= atual.data_inicio:
                flash("A nova data de início deve ser posterior à relação ativa atual.", "error")
                return redirect(url_for("direcao_turma_aluno_ee_edit", dt_id=dt_id, dt_aluno_id=dt_aluno_id))
            if atual:
                atual.data_fim = data_inicio - timedelta(days=1)
            nova = EEAluno(
                ee_id=ee_id,
                aluno_id=dt_aluno.aluno_id,
                data_inicio=data_inicio,
                parentesco=parentesco,
                observacoes=observacoes,
            )
            db.session.add(nova)
            db.session.commit()
            flash("Relação EE do aluno atualizada.", "success")
            return redirect(url_for("direcao_turma_alunos_edit", dt_id=dt_id, dt_aluno_id=dt_aluno_id))
        return render_template(
            "direcao_turma/aluno_ee_form.html",
            dt_turma=dt_turma,
            dt_aluno=dt_aluno,
            atual=atual,
            historico=historico,
            ees=ees,
            bloqueado=bloqueado,
            default_data_inicio=default_inicio,
        )

    @app.route("/direcao-turma/<int:dt_id>/alunos/<int:dt_aluno_id>/ee/historico")
    def direcao_turma_aluno_ee_historico(dt_id, dt_aluno_id):
        dt_turma = DTTurma.query.options(joinedload(DTTurma.turma), joinedload(DTTurma.ano_letivo)).get_or_404(dt_id)
        dt_aluno = DTAluno.query.options(joinedload(DTAluno.aluno)).filter_by(id=dt_aluno_id, dt_turma_id=dt_turma.id).first_or_404()
        rels = (
            EEAluno.query.join(EncarregadoEducacao, EEAluno.ee_id == EncarregadoEducacao.id)
            .filter(EEAluno.aluno_id == dt_aluno.aluno_id)
            .order_by(EEAluno.data_inicio.desc())
            .all()
        )
        return render_template("direcao_turma/aluno_ee_historico.html", dt_turma=dt_turma, dt_aluno=dt_aluno, rels=rels)

    @app.route("/direcao-turma/<int:dt_id>/contactos")
    def direcao_turma_contactos_list(dt_id):
        dt_turma = DTTurma.query.options(joinedload(DTTurma.turma), joinedload(DTTurma.ano_letivo)).get_or_404(dt_id)
        periodo = (request.args.get("periodo") or "anual").strip().lower()
        inicio, fim = _dt_period_range(dt_turma, periodo, request.args.get("data_inicio"), request.args.get("data_fim"))
        ee_id = request.args.get("ee_id", type=int)
        aluno_id = request.args.get("aluno_id", type=int)
        tipo_contacto_id = request.args.get("tipo_contacto_id", type=int)
        motivo_contacto_id = request.args.get("motivo_contacto_id", type=int)

        query = Contacto.query.filter(Contacto.dt_turma_id == dt_turma.id)
        query = query.filter(func.date(Contacto.data_hora) >= inicio, func.date(Contacto.data_hora) <= fim)
        if ee_id:
            query = query.filter(Contacto.ee_id == ee_id)
        if tipo_contacto_id:
            query = query.join(ContactoTipo, ContactoTipo.contacto_id == Contacto.id).filter(ContactoTipo.tipo_contacto_id == tipo_contacto_id)
        if aluno_id:
            query = query.join(ContactoAluno, ContactoAluno.contacto_id == Contacto.id).filter(ContactoAluno.aluno_id == aluno_id)
        if motivo_contacto_id:
            query = query.join(ContactoAluno, ContactoAluno.contacto_id == Contacto.id).join(ContactoAlunoMotivo, ContactoAlunoMotivo.contacto_aluno_id == ContactoAluno.id).filter(ContactoAlunoMotivo.motivo_contacto_id == motivo_contacto_id)

        contactos = query.order_by(Contacto.data_hora.desc()).all()
        ees = EncarregadoEducacao.query.order_by(EncarregadoEducacao.nome.asc()).all()
        tipos = TipoContacto.query.order_by(TipoContacto.ordem.asc(), TipoContacto.nome.asc()).all()
        motivos = MotivoContacto.query.order_by(MotivoContacto.ordem.asc(), MotivoContacto.nome.asc()).all()
        dt_alunos = DTAluno.query.options(joinedload(DTAluno.aluno)).filter_by(dt_turma_id=dt_turma.id).all()

        return render_template(
            "direcao_turma/contactos_list.html",
            dt_turma=dt_turma,
            contactos=contactos,
            ees=ees,
            tipos=tipos,
            motivos=motivos,
            dt_alunos=dt_alunos,
            filtro={"periodo": periodo, "data_inicio": inicio.isoformat(), "data_fim": fim.isoformat(), "ee_id": ee_id, "aluno_id": aluno_id, "tipo_contacto_id": tipo_contacto_id, "motivo_contacto_id": motivo_contacto_id},
        )

    @app.route("/direcao-turma/<int:dt_id>/contactos/novo-lote", methods=["GET", "POST"])
    def direcao_turma_contactos_lote_form(dt_id):
        dt_turma = DTTurma.query.options(joinedload(DTTurma.turma), joinedload(DTTurma.ano_letivo)).get_or_404(dt_id)
        bloqueado = bool(dt_turma.ano_letivo and dt_turma.ano_letivo.fechado)
        dt_alunos = DTAluno.query.options(joinedload(DTAluno.aluno)).filter_by(dt_turma_id=dt_turma.id).all()
        tipos = TipoContacto.query.order_by(TipoContacto.ordem.asc(), TipoContacto.nome.asc()).all()
        motivos = MotivoContacto.query.order_by(MotivoContacto.ordem.asc(), MotivoContacto.nome.asc()).all()

        if request.method == "POST":
            if bloqueado:
                flash("Ano letivo fechado: apenas consulta.", "error")
                return redirect(url_for("direcao_turma_contactos_lote_form", dt_id=dt_id))
            aluno_ids = [int(x) for x in request.form.getlist("aluno_ids") if str(x).strip().isdigit()]
            if not aluno_ids:
                flash("Seleciona pelo menos um aluno.", "error")
                return redirect(url_for("direcao_turma_contactos_lote_form", dt_id=dt_id))

            tipo_ids = [int(x) for x in request.form.getlist("tipo_contacto_ids") if str(x).strip().isdigit()]
            per_aluno = {}
            for aluno_id in aluno_ids:
                motivo_id = request.form.get(f"motivo_{aluno_id}", type=int)
                detalhe = request.form.get(f"motivo_detalhe_{aluno_id}") or None
                obs = request.form.get(f"obs_{aluno_id}") or None
                resultado = request.form.get(f"resultado_{aluno_id}") or None
                motivos_payload = []
                if motivo_id:
                    motivos_payload.append({"motivo_contacto_id": motivo_id, "detalhe": detalhe})
                per_aluno[str(aluno_id)] = {"observacoes": obs, "resultado_individual": resultado, "motivos": motivos_payload}

            base_payload = {
                "data_hora": _parse_iso_datetime(request.form.get("data_hora")) if request.form.get("data_hora") else datetime.utcnow(),
                "iniciado_por": (request.form.get("iniciado_por") or "professor").strip(),
                "resumo": request.form.get("resumo") or None,
                "observacoes_gerais": request.form.get("observacoes_gerais") or None,
                "estado_contacto": (request.form.get("estado_contacto") or "realizado").strip(),
                "estado_reuniao": (request.form.get("estado_reuniao") or "nao_agendada").strip(),
                "data_reuniao": _parse_iso_datetime(request.form.get("data_reuniao")) if request.form.get("data_reuniao") else None,
                "requer_followup": bool(request.form.get("requer_followup")),
                "data_followup": _parse_iso_date(request.form.get("data_followup")) if request.form.get("data_followup") else None,
                "confidencial": bool(request.form.get("confidencial")),
                "created_by": (request.form.get("created_by") or "").strip() or None,
                "tipo_contacto_ids": tipo_ids,
            }
            created_ids = _create_contactos_em_lote(dt_turma.id, aluno_ids, base_payload, per_aluno)

            links_titulo = request.form.get("links_titulo") or ""
            links_url = request.form.get("links_url") or ""
            links_tipo = request.form.get("links_tipo") or ""
            links_obs = request.form.get("links_obs") or ""
            if links_url.strip() and created_ids:
                for contacto_id in created_ids:
                    db.session.add(
                        ContactoLink(
                            contacto_id=contacto_id,
                            titulo=links_titulo.strip() or "Link externo",
                            url=links_url.strip(),
                            tipo=links_tipo.strip() or None,
                            observacoes=links_obs.strip() or None,
                        )
                    )
                db.session.commit()

            flash(f"{len(created_ids)} contacto(s) criado(s).", "success")
            return redirect(url_for("direcao_turma_contactos_list", dt_id=dt_id))

        return render_template("direcao_turma/contactos_lote_form.html", dt_turma=dt_turma, dt_alunos=dt_alunos, tipos=tipos, motivos=motivos, bloqueado=bloqueado)

    @app.route("/direcao-turma/<int:dt_id>/cargos/alunos", methods=["GET", "POST"])
    def direcao_turma_cargos_alunos_page(dt_id):
        dt_turma = DTTurma.query.options(joinedload(DTTurma.turma), joinedload(DTTurma.ano_letivo)).get_or_404(dt_id)
        bloqueado = bool(dt_turma.ano_letivo and dt_turma.ano_letivo.fechado)
        if request.method == "POST":
            if bloqueado:
                flash("Ano letivo fechado: apenas consulta.", "error")
                return redirect(url_for("direcao_turma_cargos_alunos_page", dt_id=dt_id))
            aluno_id = request.form.get("aluno_id", type=int)
            cargo = (request.form.get("cargo") or "").strip()
            data_inicio = _parse_iso_date(request.form.get("data_inicio")) or _dt_default_start_date(dt_turma)
            if cargo not in DT_ALUNO_CARGOS_VALIDOS:
                flash("Cargo inválido.", "error")
            elif not _ensure_single_active_dt_cargo_aluno(dt_turma.id, cargo):
                flash(f"Já existe {cargo} ativo.", "error")
            else:
                db.session.add(DTCargoAluno(dt_turma_id=dt_turma.id, aluno_id=aluno_id, cargo=cargo, data_inicio=data_inicio, data_fim=_parse_iso_date(request.form.get("data_fim")), motivo_fim=request.form.get("motivo_fim") or None))
                db.session.commit()
                flash("Cargo de aluno registado.", "success")
            return redirect(url_for("direcao_turma_cargos_alunos_page", dt_id=dt_id))

        cargos = DTCargoAluno.query.options(joinedload(DTCargoAluno.aluno)).filter_by(dt_turma_id=dt_turma.id).order_by(DTCargoAluno.data_inicio.desc()).all()
        alunos = DTAluno.query.options(joinedload(DTAluno.aluno)).filter_by(dt_turma_id=dt_turma.id).all()
        return render_template("direcao_turma/cargos_alunos.html", dt_turma=dt_turma, cargos=cargos, alunos=alunos, bloqueado=bloqueado, default_data_inicio=_dt_default_start_date(dt_turma))

    @app.route("/direcao-turma/<int:dt_id>/cargos/ee", methods=["GET", "POST"])
    def direcao_turma_cargos_ee_page(dt_id):
        dt_turma = DTTurma.query.options(joinedload(DTTurma.turma), joinedload(DTTurma.ano_letivo)).get_or_404(dt_id)
        bloqueado = bool(dt_turma.ano_letivo and dt_turma.ano_letivo.fechado)
        if request.method == "POST":
            if bloqueado:
                flash("Ano letivo fechado: apenas consulta.", "error")
                return redirect(url_for("direcao_turma_cargos_ee_page", dt_id=dt_id))
            ee_id = request.form.get("ee_id", type=int)
            cargo = (request.form.get("cargo") or "").strip()
            data_inicio = _parse_iso_date(request.form.get("data_inicio")) or _dt_default_start_date(dt_turma)
            if cargo not in DT_EE_CARGOS_VALIDOS:
                flash("Cargo inválido.", "error")
            elif not _ensure_single_active_dt_cargo_ee(dt_turma.id, cargo):
                flash(f"Já existe {cargo} ativo.", "error")
            else:
                db.session.add(DTCargoEE(dt_turma_id=dt_turma.id, ee_id=ee_id, cargo=cargo, data_inicio=data_inicio, data_fim=_parse_iso_date(request.form.get("data_fim")), motivo_fim=request.form.get("motivo_fim") or None))
                db.session.commit()
                flash("Cargo de EE registado.", "success")
            return redirect(url_for("direcao_turma_cargos_ee_page", dt_id=dt_id))

        cargos = DTCargoEE.query.options(joinedload(DTCargoEE.ee)).filter_by(dt_turma_id=dt_turma.id).order_by(DTCargoEE.data_inicio.desc()).all()
        ees = (
            EncarregadoEducacao.query.join(EEAluno, EEAluno.ee_id == EncarregadoEducacao.id)
            .join(Aluno, Aluno.id == EEAluno.aluno_id)
            .filter(Aluno.turma_id == dt_turma.turma_id)
            .distinct()
            .order_by(EncarregadoEducacao.nome.asc())
            .all()
        )
        return render_template("direcao_turma/cargos_ee.html", dt_turma=dt_turma, cargos=cargos, ees=ees, bloqueado=bloqueado, default_data_inicio=_dt_default_start_date(dt_turma))

    @app.route("/direcao-turma/add", methods=["GET", "POST"])
    def direcao_turma_add():
        anos_letivos = AnoLetivo.query.order_by(AnoLetivo.data_inicio_ano.desc()).all()
        turmas = (
            Turma.query.options(joinedload(Turma.ano_letivo))
            .order_by(Turma.nome)
            .all()
        )

        if request.method == "POST":
            turma_id = request.form.get("turma_id", type=int)
            ano_letivo_id = request.form.get("ano_letivo_id", type=int)
            observacoes = request.form.get("observacoes") or None

            turma, ano = _validar_dt_turma(turma_id, ano_letivo_id)
            if not turma:
                return redirect(url_for("direcao_turma_add"))

            existente = DTTurma.query.filter_by(
                turma_id=turma.id,
                ano_letivo_id=ano.id,
            ).first()
            if existente:
                flash("Já existe uma Direção de Turma para esta turma/ano.", "error")
                return redirect(url_for("direcao_turma_add"))

            dt_turma = DTTurma(
                turma_id=turma.id,
                ano_letivo_id=ano.id,
                observacoes=observacoes,
            )
            db.session.add(dt_turma)
            db.session.commit()
            flash("Direção de Turma criada.", "success")
            return redirect(url_for("direcao_turma_list"))

        return render_template(
            "direcao_turma/form.html",
            titulo="Nova Direção de Turma",
            dt_turma=None,
            anos_letivos=anos_letivos,
            turmas=turmas,
        )

    @app.route("/direcao-turma/<int:dt_id>/edit", methods=["GET", "POST"])
    def direcao_turma_edit(dt_id):
        dt_turma = DTTurma.query.options(
            joinedload(DTTurma.turma),
            joinedload(DTTurma.ano_letivo),
        ).get_or_404(dt_id)

        if dt_turma.ano_letivo and dt_turma.ano_letivo.fechado:
            flash("Ano letivo fechado: apenas consulta.", "error")
            return redirect(url_for("direcao_turma_list"))

        anos_letivos = AnoLetivo.query.order_by(AnoLetivo.data_inicio_ano.desc()).all()
        turmas = (
            Turma.query.options(joinedload(Turma.ano_letivo))
            .order_by(Turma.nome)
            .all()
        )

        if request.method == "POST":
            turma_id = request.form.get("turma_id", type=int)
            ano_letivo_id = request.form.get("ano_letivo_id", type=int)
            observacoes = request.form.get("observacoes") or None

            turma, ano = _validar_dt_turma(turma_id, ano_letivo_id)
            if not turma:
                return redirect(url_for("direcao_turma_edit", dt_id=dt_turma.id))

            existente = (
                DTTurma.query.filter_by(
                    turma_id=turma.id,
                    ano_letivo_id=ano.id,
                )
                .filter(DTTurma.id != dt_turma.id)
                .first()
            )
            if existente:
                flash("Já existe uma Direção de Turma para esta turma/ano.", "error")
                return redirect(url_for("direcao_turma_edit", dt_id=dt_turma.id))

            dt_turma.turma_id = turma.id
            dt_turma.ano_letivo_id = ano.id
            dt_turma.observacoes = observacoes
            db.session.commit()
            flash("Direção de Turma atualizada.", "success")
            return redirect(url_for("direcao_turma_list"))

        return render_template(
            "direcao_turma/form.html",
            titulo="Editar Direção de Turma",
            dt_turma=dt_turma,
            anos_letivos=anos_letivos,
            turmas=turmas,
        )

    @app.route("/direcao-turma/<int:dt_id>/mapa-mensal")
    def direcao_turma_mapa_mensal(dt_id):
        dt_turma = DTTurma.query.options(
            joinedload(DTTurma.turma),
            joinedload(DTTurma.ano_letivo),
            joinedload(DTTurma.alunos),
        ).get_or_404(dt_id)

        hoje = date.today()
        mes_ano = request.args.get("mes_ano") or ""
        ano_txt, mes_txt = (mes_ano.split("-", 1) + ["", ""])[:2]
        year = _clamp_int(request.args.get("ano") or ano_txt, default=hoje.year, min_val=2000, max_val=2100)
        month = _clamp_int(request.args.get("mes") or mes_txt, default=hoje.month, min_val=1, max_val=12)
        ano_mes = date(year, month, 1)
        ultimo_dia = calendar.monthrange(year, month)[1]
        dias = [
            date(year, month, dia)
            for dia in range(1, ultimo_dia + 1)
            if date(year, month, dia).weekday() < 5
        ]

        justificacoes = (
            DTJustificacao.query.join(DTAluno)
            .filter(
                DTAluno.dt_turma_id == dt_turma.id,
                DTJustificacao.data >= dias[0],
                DTJustificacao.data <= dias[-1],
            )
            .all()
        )
        mapa_justificacoes = defaultdict(dict)
        mapa_motivos_dia = {
            motivo.data: motivo.motivo
            for motivo in DTMotivoDia.query.filter(
                DTMotivoDia.dt_turma_id == dt_turma.id,
                DTMotivoDia.data >= dias[0],
                DTMotivoDia.data <= dias[-1],
            ).all()
        }
        for justificacao in justificacoes:
            mapa_justificacoes[justificacao.dt_aluno_id][justificacao.data] = justificacao

        dt_alunos = (
            DTAluno.query.options(joinedload(DTAluno.aluno))
            .filter_by(dt_turma_id=dt_turma.id)
            .all()
        )
        dt_alunos.sort(
            key=lambda dt_aluno: (
                dt_aluno.aluno.numero is None,
                dt_aluno.aluno.numero or 0,
                dt_aluno.aluno.nome or "",
            )
        )

        return render_template(
            "direcao_turma/mapa_mensal.html",
            dt_turma=dt_turma,
            alunos=dt_alunos,
            dias=dias,
            ano_mes=ano_mes,
            mapa_justificacoes=mapa_justificacoes,
            mapa_motivos_dia=mapa_motivos_dia,
        )

    @app.route("/direcao-turma/<int:dt_id>/mapa-mensal/atualizar", methods=["POST"])
    def direcao_turma_mapa_mensal_atualizar(dt_id):
        dt_turma = DTTurma.query.options(
            joinedload(DTTurma.ano_letivo),
        ).get_or_404(dt_id)

        if dt_turma.ano_letivo and dt_turma.ano_letivo.fechado:
            flash("Ano letivo fechado: apenas consulta.", "error")
            return redirect(url_for("direcao_turma_mapa_mensal", dt_id=dt_id))

        hoje = date.today()
        year = _clamp_int(request.form.get("ano"), default=hoje.year, min_val=2000, max_val=2100)
        month = _clamp_int(request.form.get("mes"), default=hoje.month, min_val=1, max_val=12)
        aluno_id = request.form.get("dt_aluno_id", type=int)
        dia_txt = request.form.get("dia")

        if not dia_txt:
            flash("Dia inválido.", "error")
            return redirect(url_for("direcao_turma_mapa_mensal", dt_id=dt_id))

        try:
            dia = datetime.strptime(dia_txt, "%Y-%m-%d").date()
        except ValueError:
            flash("Dia inválido.", "error")
            return redirect(url_for("direcao_turma_mapa_mensal", dt_id=dt_id))

        if dia.year != year or dia.month != month:
            flash("Dia fora do mês selecionado.", "error")
            return redirect(url_for("direcao_turma_mapa_mensal", dt_id=dt_id))

        if dia.weekday() >= 5:
            flash("Dia inválido.", "error")
            return redirect(url_for("direcao_turma_mapa_mensal", dt_id=dt_id))

        motivo = (request.form.get(f"motivo_{dia_txt}") or "").strip()
        if not aluno_id:
            motivo_dia = DTMotivoDia.query.filter_by(
                dt_turma_id=dt_turma.id,
                data=dia,
            ).first()

            if motivo:
                if not motivo_dia:
                    motivo_dia = DTMotivoDia(
                        dt_turma_id=dt_turma.id,
                        data=dia,
                        motivo=motivo,
                    )
                    db.session.add(motivo_dia)
                else:
                    motivo_dia.motivo = motivo
            elif motivo_dia:
                db.session.delete(motivo_dia)

            db.session.commit()
            flash("Motivo atualizado.", "success")
            return redirect(
                url_for("direcao_turma_mapa_mensal", dt_id=dt_id, ano=year, mes=month)
            )

        aluno = DTAluno.query.filter_by(id=aluno_id, dt_turma_id=dt_turma.id).first()
        if not aluno:
            flash("Aluno não encontrado nesta Direção de Turma.", "error")
            return redirect(url_for("direcao_turma_mapa_mensal", dt_id=dt_id))

        marcado = request.form.get(f"dia_{aluno_id}_{dia_txt}") == "1"

        justificacao = DTJustificacao.query.filter_by(
            dt_aluno_id=aluno.id,
            data=dia,
        ).first()

        if not marcado and not motivo:
            if justificacao:
                db.session.delete(justificacao)
        else:
            if not justificacao:
                justificacao = DTJustificacao(
                    dt_aluno_id=aluno.id,
                    data=dia,
                )
                db.session.add(justificacao)

            justificacao.motivo = motivo or None

        db.session.commit()
        flash("Mapa mensal atualizado.", "success")
        return redirect(
            url_for("direcao_turma_mapa_mensal", dt_id=dt_id, ano=year, mes=month)
        )

    @app.route("/direcao-turma/<int:dt_id>/alunos")
    def direcao_turma_alunos(dt_id):
        dt_turma = DTTurma.query.options(
            joinedload(DTTurma.turma),
            joinedload(DTTurma.ano_letivo),
            joinedload(DTTurma.alunos),
        ).get_or_404(dt_id)

        dt_alunos = (
            DTAluno.query.options(joinedload(DTAluno.aluno))
            .filter_by(dt_turma_id=dt_turma.id)
            .all()
        )
        dt_alunos.sort(
            key=lambda dt_aluno: (
                dt_aluno.aluno.numero is None,
                dt_aluno.aluno.numero or 0,
                dt_aluno.aluno.nome or "",
            )
        )
        bloqueado = bool(dt_turma.ano_letivo and dt_turma.ano_letivo.fechado)
        aluno_ids = [item.aluno_id for item in dt_alunos if item.aluno_id]
        rels_ativas = (
            EEAluno.query.filter(EEAluno.aluno_id.in_(aluno_ids), EEAluno.data_fim.is_(None)).all()
            if aluno_ids else []
        )
        ee_atual_por_aluno = {rel.aluno_id: rel for rel in rels_ativas}
        contactos_totais = {}
        if aluno_ids:
            rows = (
                db.session.query(ContactoAluno.aluno_id, func.count(ContactoAluno.id))
                .join(Contacto, Contacto.id == ContactoAluno.contacto_id)
                .filter(Contacto.dt_turma_id == dt_turma.id, ContactoAluno.aluno_id.in_(aluno_ids))
                .group_by(ContactoAluno.aluno_id)
                .all()
            )
            contactos_totais = {aluno_id: total for aluno_id, total in rows}

        return render_template(
            "direcao_turma/alunos.html",
            dt_turma=dt_turma,
            alunos=dt_alunos,
            bloqueado=bloqueado,
            ee_atual_por_aluno=ee_atual_por_aluno,
            contactos_totais=contactos_totais,
        )

    @app.route("/direcao-turma/<int:dt_id>/alunos/importar", methods=["POST"])
    def direcao_turma_alunos_importar(dt_id):
        dt_turma = DTTurma.query.options(
            joinedload(DTTurma.turma),
            joinedload(DTTurma.ano_letivo),
        ).get_or_404(dt_id)

        if dt_turma.ano_letivo and dt_turma.ano_letivo.fechado:
            flash("Ano letivo fechado: apenas consulta.", "error")
            return redirect(url_for("direcao_turma_alunos", dt_id=dt_id))

        alunos_turma = Aluno.query.filter_by(turma_id=dt_turma.turma_id).all()
        dt_existentes = DTAluno.query.filter_by(dt_turma_id=dt_turma.id).all()
        existentes = {aluno.aluno_id for aluno in dt_existentes if aluno.aluno_id}

        novos = 0
        for aluno in alunos_turma:
            if aluno.id in existentes:
                continue
            db.session.add(
                DTAluno(
                    dt_turma_id=dt_turma.id,
                    aluno_id=aluno.id,
                )
            )
            novos += 1

        db.session.commit()
        if novos:
            flash(f"{novos} aluno(s) importado(s) para a Direção de Turma.", "success")
        else:
            flash("Não há novos alunos para importar.", "info")

        return redirect(url_for("direcao_turma_alunos", dt_id=dt_turma.id))

    @app.route("/direcao-turma/<int:dt_id>/alunos/guardar", methods=["POST"])
    def direcao_turma_alunos_guardar(dt_id):
        dt_turma = DTTurma.query.options(joinedload(DTTurma.ano_letivo)).get_or_404(dt_id)

        if dt_turma.ano_letivo and dt_turma.ano_letivo.fechado:
            flash("Ano letivo fechado: apenas consulta.", "error")
            return redirect(url_for("direcao_turma_alunos", dt_id=dt_id))

        ids = request.form.getlist("aluno_ids")
        if not ids:
            flash("Nenhum aluno selecionado.", "error")
            return redirect(url_for("direcao_turma_alunos", dt_id=dt_id))

        alunos = DTAluno.query.options(joinedload(DTAluno.aluno)).filter(
            DTAluno.dt_turma_id == dt_turma.id,
            DTAluno.id.in_(ids),
        ).all()
        alunos_map = {str(aluno.id): aluno for aluno in alunos}

        for aluno_id in ids:
            aluno = alunos_map.get(aluno_id)
            if not aluno:
                continue
            nome_curto = _normalizar_nome_curto(
                aluno.aluno.nome if aluno.aluno else "",
                request.form.get(f"nome_curto_{aluno_id}"),
            )
            if aluno.aluno:
                aluno.aluno.nome_curto = nome_curto

        db.session.commit()
        flash("Nomes curtos atualizados.", "success")
        return redirect(url_for("direcao_turma_alunos", dt_id=dt_id))

    @app.route(
        "/direcao-turma/<int:dt_id>/alunos/<int:dt_aluno_id>/nome-curto",
        methods=["POST"],
    )
    def direcao_turma_alunos_nome_curto(dt_id, dt_aluno_id):
        dt_turma = DTTurma.query.options(joinedload(DTTurma.ano_letivo)).get_or_404(dt_id)

        if dt_turma.ano_letivo and dt_turma.ano_letivo.fechado:
            return jsonify({"status": "error", "message": "Ano letivo fechado."}), 403

        dt_aluno = DTAluno.query.options(joinedload(DTAluno.aluno)).filter_by(
            id=dt_aluno_id,
            dt_turma_id=dt_turma.id,
        ).first()
        if not dt_aluno or not dt_aluno.aluno:
            return jsonify({"status": "error", "message": "Aluno não encontrado."}), 404

        nome_curto = _normalizar_nome_curto(
            dt_aluno.aluno.nome if dt_aluno.aluno else "",
            request.form.get("nome_curto"),
        )
        dt_aluno.aluno.nome_curto = nome_curto
        db.session.commit()
        return jsonify({"status": "ok"})

    @app.route("/direcao-turma/<int:dt_id>/alunos/<int:dt_aluno_id>/delete", methods=["POST"])
    def direcao_turma_alunos_delete(dt_id, dt_aluno_id):
        dt_turma = DTTurma.query.options(joinedload(DTTurma.ano_letivo)).get_or_404(dt_id)

        if dt_turma.ano_letivo and dt_turma.ano_letivo.fechado:
            flash("Ano letivo fechado: apenas consulta.", "error")
            return redirect(url_for("direcao_turma_alunos", dt_id=dt_id))

        dt_aluno = DTAluno.query.filter_by(id=dt_aluno_id, dt_turma_id=dt_turma.id).first()
        if not dt_aluno:
            flash("Aluno não encontrado nesta Direção de Turma.", "error")
            return redirect(url_for("direcao_turma_alunos", dt_id=dt_id))

        db.session.delete(dt_aluno)
        db.session.commit()
        flash("Aluno removido da Direção de Turma.", "success")
        return redirect(url_for("direcao_turma_alunos", dt_id=dt_id))

    @app.route("/direcao-turma/<int:dt_id>/alunos/<int:dt_aluno_id>/edit", methods=["GET", "POST"])
    def direcao_turma_alunos_edit(dt_id, dt_aluno_id):
        dt_turma = DTTurma.query.options(joinedload(DTTurma.ano_letivo)).get_or_404(dt_id)

        if dt_turma.ano_letivo and dt_turma.ano_letivo.fechado:
            flash("Ano letivo fechado: apenas consulta.", "error")
            return redirect(url_for("direcao_turma_alunos", dt_id=dt_id))

        dt_aluno = DTAluno.query.options(joinedload(DTAluno.aluno)).filter_by(
            id=dt_aluno_id,
            dt_turma_id=dt_turma.id,
        ).first()
        if not dt_aluno or not dt_aluno.aluno:
            flash("Aluno não encontrado nesta Direção de Turma.", "error")
            return redirect(url_for("direcao_turma_alunos", dt_id=dt_id))

        contexto = AlunoContextoDT.query.filter_by(aluno_id=dt_aluno.aluno_id).first()
        ee_atual = _active_ee_rel_for_aluno(dt_aluno.aluno_id)
        ee_historico = (
            EEAluno.query.options(joinedload(EEAluno.ee))
            .filter(EEAluno.aluno_id == dt_aluno.aluno_id)
            .order_by(EEAluno.data_inicio.desc())
            .all()
        )
        contactos = (
            Contacto.query.join(ContactoAluno, ContactoAluno.contacto_id == Contacto.id)
            .filter(Contacto.dt_turma_id == dt_turma.id, ContactoAluno.aluno_id == dt_aluno.aluno_id)
            .order_by(Contacto.data_hora.desc())
            .limit(20)
            .all()
        )

        if request.method == "POST":
            aluno = dt_aluno.aluno
            aluno.numero = _clamp_int(request.form.get("numero"), default=None, min_val=1)
            aluno.processo = request.form.get("processo") or None
            aluno.nome = (request.form.get("nome") or "").strip()
            aluno.nome_curto = _normalizar_nome_curto(
                aluno.nome,
                request.form.get("nome_curto"),
            )
            aluno.nee = request.form.get("nee") or None
            aluno.observacoes = request.form.get("observacoes") or None
            aluno.data_nascimento = _parse_iso_date(request.form.get("data_nascimento")) if request.form.get("data_nascimento") else None
            aluno.tipo_identificacao = (request.form.get("tipo_identificacao") or "").strip() or None
            aluno.numero_identificacao = (request.form.get("numero_identificacao") or "").strip() or None
            aluno.email = (request.form.get("email") or "").strip() or None
            aluno.telefone = (request.form.get("telefone") or "").strip() or None
            aluno.numero_utente_sns = (request.form.get("numero_utente_sns") or "").strip() or None
            aluno.numero_processo = (request.form.get("numero_processo") or "").strip() or None

            if not contexto:
                contexto = AlunoContextoDT(aluno_id=dt_aluno.aluno_id)
                db.session.add(contexto)
            contexto.dt_observacoes = request.form.get("dt_observacoes") or None
            contexto.ee_observacoes = request.form.get("ee_observacoes") or None
            contexto.alerta_dt = request.form.get("alerta_dt") or None
            contexto.resumo_sinalizacao = request.form.get("resumo_sinalizacao") or None

            if not aluno.nome:
                flash("O nome do aluno é obrigatório.", "error")
                return redirect(
                    url_for("direcao_turma_alunos_edit", dt_id=dt_id, dt_aluno_id=dt_aluno_id)
                )

            db.session.commit()
            flash("Aluno atualizado.", "success")
            return redirect(url_for("direcao_turma_alunos_edit", dt_id=dt_id, dt_aluno_id=dt_aluno_id))

        return render_template(
            "direcao_turma/alunos_form.html",
            dt_turma=dt_turma,
            dt_aluno=dt_aluno,
            contexto=contexto,
            ee_atual=ee_atual,
            ee_historico=ee_historico,
            contactos=contactos,
        )

    @app.route("/direcao-turma/<int:dt_id>/ocorrencias")
    def direcao_turma_ocorrencias(dt_id):
        dt_turma = DTTurma.query.options(
            joinedload(DTTurma.turma),
            joinedload(DTTurma.ano_letivo),
        ).get_or_404(dt_id)
        filtros = _dt_ocorrencias_filters(dt_turma)
        qs = _dt_filtros_to_qs(filtros)
        ocorrencias = _dt_ocorrencias_query(dt_turma, filtros).all()
        agregado = _dt_ocorrencias_agregado(dt_turma, filtros)
        for ocorrencia in ocorrencias:
            ocorrencia.alunos_linha = _dt_ocorrencia_alunos_linha(ocorrencia)
        disciplinas = DTDisciplina.query.filter_by(ativa=True).order_by(DTDisciplina.nome.asc()).all()
        alunos = (
            DTAluno.query.options(joinedload(DTAluno.aluno))
            .filter_by(dt_turma_id=dt_turma.id)
            .all()
        )
        return render_template(
            "direcao_turma/ocorrencias_list.html",
            dt_turma=dt_turma,
            bloqueado=_dt_locked(dt_turma),
            ocorrencias=ocorrencias,
            filtros=filtros,
            disciplinas=disciplinas,
            alunos=alunos,
            qs=qs,
            disciplinas_agregadas=agregado["disciplinas"],
            alunos_agregados=agregado["alunos"],
            agregados=agregado["agregados"],
            totais_aluno=agregado["totais_aluno"],
            agregados_tem_resultados=agregado["tem_resultados"],
        )

    @app.route("/direcao-turma/<int:dt_id>/ocorrencias/new", methods=["GET", "POST"])
    def direcao_turma_ocorrencias_new(dt_id):
        dt_turma = DTTurma.query.options(joinedload(DTTurma.turma), joinedload(DTTurma.ano_letivo)).get_or_404(dt_id)
        if _dt_locked(dt_turma):
            flash("Ano letivo fechado: apenas consulta/export.", "error")
            return redirect_com_filtros("direcao_turma_ocorrencias", dt_id=dt_id)

        disciplinas = DTDisciplina.query.filter_by(ativa=True).order_by(DTDisciplina.nome.asc()).all()
        if not disciplinas:
            flash("Sem disciplinas ativas. Cria disciplinas primeiro.", "warning")
            return redirect(url_for("dt_disciplinas_new"))
        alunos = DTAluno.query.options(joinedload(DTAluno.aluno)).filter_by(dt_turma_id=dt_turma.id).all()

        if request.method == "POST":
            data = _parse_date_form(request.form.get("data"))
            disciplina_id = request.form.get("dt_disciplina_id", type=int)
            hora_inicio = _parse_time_form(request.form.get("hora_inicio"))
            hora_fim = _parse_time_form(request.form.get("hora_fim"))
            num_tempos = _clamp_int(request.form.get("num_tempos"), default=None, min_val=1)
            observacoes = request.form.get("observacoes") or None
            aluno_ids = [int(v) for v in request.form.getlist("dt_aluno_ids") if str(v).isdigit()]
            if not data or not disciplina_id:
                flash("Data e disciplina são obrigatórios.", "error")
                return redirect_com_filtros("direcao_turma_ocorrencias_new", dt_id=dt_id)
            ocorr = DTOcorrencia(
                dt_turma_id=dt_turma.id,
                data=data,
                hora_inicio=hora_inicio,
                hora_fim=hora_fim,
                num_tempos=num_tempos,
                dt_disciplina_id=disciplina_id,
                observacoes=observacoes,
            )
            if aluno_ids:
                ocorr.alunos = DTAluno.query.filter(DTAluno.dt_turma_id == dt_turma.id, DTAluno.id.in_(aluno_ids)).all()
            db.session.add(ocorr)
            db.session.commit()
            flash("Ocorrência registada.", "success")
            fallback = url_for("direcao_turma_ocorrencias", dt_id=dt_id, **_clean_query_params(dict(parse_qsl(request.form.get("_qs") or ""))))
            return redirect(_safe_next_url(request.form.get("next"), fallback))

        return render_template(
            "direcao_turma/ocorrencias_form.html",
            dt_turma=dt_turma,
            bloqueado=False,
            ocorrencia=None,
            disciplinas=disciplinas,
            alunos=alunos,
            qs=_clean_query_params(request.args.to_dict(flat=True)),
            next_url=request.full_path,
        )

    @app.route("/direcao-turma/<int:dt_id>/ocorrencias/<int:oc_id>/edit", methods=["GET", "POST"])
    def direcao_turma_ocorrencias_edit(dt_id, oc_id):
        dt_turma = DTTurma.query.options(joinedload(DTTurma.turma), joinedload(DTTurma.ano_letivo)).get_or_404(dt_id)
        ocorrencia = DTOcorrencia.query.options(joinedload(DTOcorrencia.alunos), joinedload(DTOcorrencia.disciplina)).filter_by(id=oc_id, dt_turma_id=dt_turma.id).first_or_404()
        disciplinas = DTDisciplina.query.filter_by(ativa=True).order_by(DTDisciplina.nome.asc()).all()
        alunos = DTAluno.query.options(joinedload(DTAluno.aluno)).filter_by(dt_turma_id=dt_turma.id).all()
        if _dt_locked(dt_turma):
            flash("Ano letivo fechado: apenas consulta/export.", "error")
            return redirect_com_filtros("direcao_turma_ocorrencias", dt_id=dt_id)

        if request.method == "POST":
            data = _parse_date_form(request.form.get("data"))
            disciplina_id = request.form.get("dt_disciplina_id", type=int)
            if not data or not disciplina_id:
                flash("Data e disciplina são obrigatórios.", "error")
                return redirect_com_filtros("direcao_turma_ocorrencias_edit", dt_id=dt_id, oc_id=oc_id)
            ocorrencia.data = data
            ocorrencia.hora_inicio = _parse_time_form(request.form.get("hora_inicio"))
            ocorrencia.hora_fim = _parse_time_form(request.form.get("hora_fim"))
            ocorrencia.num_tempos = _clamp_int(request.form.get("num_tempos"), default=None, min_val=1)
            ocorrencia.dt_disciplina_id = disciplina_id
            ocorrencia.observacoes = request.form.get("observacoes") or None
            aluno_ids = [int(v) for v in request.form.getlist("dt_aluno_ids") if str(v).isdigit()]
            ocorrencia.alunos = DTAluno.query.filter(DTAluno.dt_turma_id == dt_turma.id, DTAluno.id.in_(aluno_ids)).all() if aluno_ids else []
            db.session.commit()
            flash("Ocorrência atualizada.", "success")
            fallback = url_for("direcao_turma_ocorrencias", dt_id=dt_id, **_clean_query_params(dict(parse_qsl(request.form.get("_qs") or ""))))
            return redirect(_safe_next_url(request.form.get("next"), fallback))

        return render_template(
            "direcao_turma/ocorrencias_form.html",
            dt_turma=dt_turma,
            bloqueado=False,
            ocorrencia=ocorrencia,
            disciplinas=disciplinas,
            alunos=alunos,
            qs=_clean_query_params(request.args.to_dict(flat=True)),
            next_url=request.full_path,
        )

    @app.route("/direcao-turma/<int:dt_id>/ocorrencias/<int:oc_id>/delete", methods=["POST"])
    def direcao_turma_ocorrencias_delete(dt_id, oc_id):
        dt_turma = DTTurma.query.options(joinedload(DTTurma.ano_letivo)).get_or_404(dt_id)
        if _dt_locked(dt_turma):
            flash("Ano letivo fechado: apenas consulta/export.", "error")
            return redirect_com_filtros("direcao_turma_ocorrencias", dt_id=dt_id)
        ocorrencia = DTOcorrencia.query.filter_by(id=oc_id, dt_turma_id=dt_turma.id).first_or_404()
        db.session.delete(ocorrencia)
        db.session.commit()
        flash("Ocorrência removida.", "success")
        fallback = url_for("direcao_turma_ocorrencias", dt_id=dt_id, **_clean_query_params(dict(parse_qsl(request.form.get("_qs") or ""))))
        return redirect(_safe_next_url(request.form.get("next"), fallback))

    @app.route("/direcao-turma/<int:dt_id>/ocorrencias/export/csv")
    def direcao_turma_ocorrencias_export_csv(dt_id):
        dt_turma = DTTurma.query.options(joinedload(DTTurma.turma), joinedload(DTTurma.ano_letivo)).get_or_404(dt_id)
        filtros = _dt_ocorrencias_filters(dt_turma)
        ocorrencias = _dt_ocorrencias_query(dt_turma, filtros).all()
        rows = []
        for ocorr in ocorrencias:
            alunos_txt = "; ".join(
                f"{(a.aluno.numero if a.aluno and a.aluno.numero is not None else '—')} - {(a.aluno.nome if a.aluno else '—')}"
                for a in sorted(ocorr.alunos, key=lambda x: (x.aluno.numero if x.aluno and x.aluno.numero is not None else 9999, x.aluno.nome if x.aluno else ""))
            )
            rows.append([
                ocorr.data.strftime("%d/%m/%Y") if ocorr.data else "",
                ocorr.hora_inicio.strftime("%H:%M") if ocorr.hora_inicio else "",
                ocorr.hora_fim.strftime("%H:%M") if ocorr.hora_fim else "",
                csv_text(ocorr.num_tempos) if ocorr.num_tempos is not None else "",
                ocorr.disciplina.nome if ocorr.disciplina else "",
                alunos_txt,
                ocorr.observacoes or "",
            ])
        filename = f"ocorrencias_{_slugify_filename(dt_turma.turma.nome if dt_turma.turma else 'dt', 'dt')}.csv"
        data = build_csv_data(["Data", "Hora início", "Hora fim", "N.º tempos", "Disciplina", "Alunos", "Observações"], rows)
        return Response(
            data,
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    @app.route("/direcao-turma/<int:dt_id>/delete", methods=["POST"])
    def direcao_turma_delete(dt_id):
        dt_turma = DTTurma.query.options(joinedload(DTTurma.ano_letivo)).get_or_404(dt_id)

        if dt_turma.ano_letivo and dt_turma.ano_letivo.fechado:
            abort(
                403,
                description="Ano letivo fechado: não é possível eliminar esta Direção de Turma.",
            )

        db.session.delete(dt_turma)
        db.session.commit()
        flash("Direção de Turma removida.", "success")
        return redirect(url_for("direcao_turma_list"))

    @app.route("/turmas/importar", methods=["GET", "POST"])
    def turmas_importar():
        if request.method == "POST":
            ficheiro = request.files.get("ficheiro")
            if not ficheiro or not ficheiro.filename:
                flash("Seleciona um ficheiro .ndjson.gz.", "error")
                return redirect(request.url)

            try:
                resumo = importar_backup_ndjson_gz(ficheiro)
                db.session.commit()
            except Exception as exc:
                db.session.rollback()
                app.logger.exception("Erro na importacao de backup NDJSON.")
                flash(f"Erro na importacao: {exc}", "error")
                return redirect(request.url)

            flash(
                (
                    "Importacao concluida com sucesso. "
                    f"Linhas importadas: {resumo['linhas_importadas']} | "
                    f"novas insercoes: {resumo['linhas_inseridas']}."
                ),
                "success",
            )
            return redirect(url_for("turmas_list"))

        return render_template("turmas/importar.html")

    @app.route("/backup/export/completo", methods=["GET", "POST"])
    def backup_export_completo():
        params = request.values
        try:
            ano_letivo_id = params.get("ano_letivo_id", type=int)
            ano_letivo = AnoLetivo.query.get(ano_letivo_id) if ano_letivo_id else None
            if ano_letivo_id and not ano_letivo:
                raise ValueError("Ano letivo invalido para exportacao.")

            intervalo = (params.get("intervalo") or "custom").strip().lower()
            if intervalo not in BACKUP_INTERVALOS_VALIDOS:
                raise ValueError("Intervalo invalido. Usa: ano, s1, s2 ou custom.")

            desde, ate = _resolver_intervalo_export(
                ano_letivo=ano_letivo,
                intervalo=intervalo,
                desde_str=params.get("desde"),
                ate_str=params.get("ate"),
            )
            if desde and ate and desde > ate:
                raise ValueError("Intervalo invalido: 'desde' nao pode ser maior do que 'ate'.")
            _validar_intervalo_dentro_ano_letivo(ano_letivo, desde, ate)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("turmas_list"))

        app.logger.info(
            "Inicio backup NDJSON | scope=completo | ano_letivo_id=%s | intervalo=%s | desde=%s | ate=%s",
            ano_letivo.id if ano_letivo else None,
            intervalo,
            desde.isoformat() if desde else None,
            ate.isoformat() if ate else None,
        )
        specs = _build_backup_ndjson_specs(desde=desde, ate=ate)
        return _build_backup_ndjson_response(
            "completo",
            specs,
            desde=desde,
            ate=ate,
            intervalo=intervalo,
            ano_letivo=ano_letivo,
        )

    @app.route("/turmas/<int:turma_id>/backup/export", methods=["GET", "POST"])
    def backup_export_turma(turma_id):
        turma = Turma.query.options(joinedload(Turma.ano_letivo)).get_or_404(turma_id)
        params = request.values

        try:
            intervalo = (params.get("intervalo") or "custom").strip().lower()
            if intervalo not in BACKUP_INTERVALOS_VALIDOS:
                raise ValueError("Intervalo invalido. Usa: ano, s1, s2 ou custom.")

            ano_letivo = turma.ano_letivo
            desde, ate = _resolver_intervalo_export(
                ano_letivo=ano_letivo,
                intervalo=intervalo,
                desde_str=params.get("desde"),
                ate_str=params.get("ate"),
            )
            if desde and ate and desde > ate:
                raise ValueError("Intervalo invalido: 'desde' nao pode ser maior do que 'ate'.")
            _validar_intervalo_dentro_ano_letivo(ano_letivo, desde, ate)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("turmas_list"))

        app.logger.info(
            "Inicio backup NDJSON | scope=turma | turma_id=%s | intervalo=%s | desde=%s | ate=%s",
            turma.id,
            intervalo,
            desde.isoformat() if desde else None,
            ate.isoformat() if ate else None,
        )
        specs = _build_backup_ndjson_specs(turma=turma, desde=desde, ate=ate)
        return _build_backup_ndjson_response(
            "turma",
            specs,
            desde=desde,
            ate=ate,
            turma=turma,
            intervalo=intervalo,
            ano_letivo=turma.ano_letivo,
        )

    @app.route("/backup/ano/export", methods=["POST"])
    def backup_ano_export():
        ano_id = request.form.get("ano_letivo_id", type=int)
        ano = AnoLetivo.query.get(ano_id) if ano_id else None
        backup_json_dir = (request.form.get("backup_json_dir") or "").strip()

        if not ano:
            flash("Escolhe um ano letivo para exportar.", "error")
            return redirect(url_for("turmas_list"))

        if not backup_json_dir:
            flash("Indica uma pasta de destino para o backup.", "error")
            return redirect(url_for("turmas_list"))

        try:
            os.makedirs(backup_json_dir, exist_ok=True)
        except OSError as exc:
            flash(f"Não foi possível usar a pasta indicada: {exc}", "error")
            return redirect(url_for("turmas_list"))

        try:
            payload = exportar_backup_ano(ano)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("turmas_list"))

        data_export = date.today().isoformat()
        filename = f"backup_{_slugify_filename(ano.nome, 'ano')}_{data_export}.json"
        destino = os.path.join(backup_json_dir, filename)

        try:
            with open(destino, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
        except OSError as exc:
            flash(f"Não foi possível gravar o backup: {exc}", "error")
            return redirect(url_for("turmas_list"))

        _save_export_options(backup_json_dir=backup_json_dir)
        flash(f"Backup gravado em {destino}", "success")
        return redirect(url_for("turmas_list"))

    @app.route("/backup/ano/import", methods=["POST"])
    def backup_ano_import():
        ficheiro = request.files.get("ano_json")
        substituir = bool(request.form.get("substituir"))

        if not ficheiro or not ficheiro.filename:
            flash("Seleciona um ficheiro JSON de backup.", "error")
            return redirect(url_for("turmas_list"))

        try:
            conteudo = ficheiro.read().decode("utf-8", errors="ignore")
            payload = json.loads(conteudo)
        except Exception:
            flash("Ficheiro JSON inválido ou corrompido.", "error")
            return redirect(url_for("turmas_list"))

        try:
            resumo = importar_backup_ano(payload, substituir=substituir)
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "error")
            return redirect(url_for("turmas_list"))

        mensagem = (
            f"Backup importado para o ano '{resumo['ano']}' "
            f"({resumo['turmas']} turmas, {resumo['alunos']} alunos, {resumo['disciplinas']} disciplinas)."
        )
        flash(mensagem, "success")
        return redirect(url_for("turmas_list"))

    @app.route("/turmas/<int:turma_id>/edit", methods=["GET", "POST"])
    def turmas_edit(turma_id):
        turma = Turma.query.get_or_404(turma_id)
        ano = turma.ano_letivo

        if ano and ano.fechado:
            flash("Ano letivo fechado: não é possível editar esta turma.", "error")
            return redirect(url_for("turmas_list"))

        ano_atual = ano or get_ano_letivo_atual()
        anos_letivos = (
            AnoLetivo.query.order_by(AnoLetivo.data_inicio_ano.desc()).all()
        )

        if request.method == "POST":
            nome = (request.form.get("nome") or "").strip()
            tipo = request.form.get("tipo") or turma.tipo
            periodo_tipo = request.form.get("periodo_tipo") or turma.periodo_tipo or "anual"
            ano_id = request.form.get("ano_letivo_id", type=int)
            letiva = request.form.get("letiva") == "1"
            carga_seg = request.form.get("carga_segunda", type=float)
            carga_ter = request.form.get("carga_terca", type=float)
            carga_qua = request.form.get("carga_quarta", type=float)
            carga_qui = request.form.get("carga_quinta", type=float)
            carga_sex = request.form.get("carga_sexta", type=float)
            tempo_seg = request.form.get("tempo_segunda", type=int)
            tempo_ter = request.form.get("tempo_terca", type=int)
            tempo_qua = request.form.get("tempo_quarta", type=int)
            tempo_qui = request.form.get("tempo_quinta", type=int)
            tempo_sex = request.form.get("tempo_sexta", type=int)
            modulos_form = _ler_modulos_form()

            if not nome:
                flash("O nome da turma é obrigatório.", "error")
                return render_template(
                    "turmas/form.html",
                    titulo="Editar Turma",
                    turma=turma,
                    ano_atual=ano_atual,
                    anos_letivos=anos_letivos,
                    modulos=modulos_form,
                )

            ano_escolhido = AnoLetivo.query.get(ano_id) if ano_id else None
            if not ano_escolhido:
                flash("Seleciona um ano letivo válido.", "error")
                return render_template(
                    "turmas/form.html",
                    titulo="Editar Turma",
                    turma=turma,
                    ano_atual=ano_atual,
                    anos_letivos=anos_letivos,
                    modulos=modulos_form,
                )

            if tipo == "profissional":
                modulos_validos = [m for m in modulos_form if m.get("nome")]
                if not modulos_validos or any(m["total"] <= 0 for m in modulos_validos):
                    flash(
                        "Adiciona módulos com carga horária positiva para turmas profissionais.",
                        "error",
                    )
                    return render_template(
                        "turmas/form.html",
                        titulo="Editar Turma",
                        turma=turma,
                        ano_atual=ano_atual,
                        anos_letivos=anos_letivos,
                        modulos=modulos_form,
                    )
                modulos_form = modulos_validos

            if periodo_tipo not in PERIODOS_TURMA_VALIDOS:
                periodo_tipo = "anual"

            turma.nome = nome
            turma.tipo = tipo
            turma.periodo_tipo = periodo_tipo
            turma.ano_letivo_id = ano_escolhido.id
            turma.letiva = letiva
            turma.carga_segunda = carga_seg
            turma.carga_terca = carga_ter
            turma.carga_quarta = carga_qua
            turma.carga_quinta = carga_qui
            turma.carga_sexta = carga_sex
            turma.tempo_segunda = tempo_seg
            turma.tempo_terca = tempo_ter
            turma.tempo_quarta = tempo_qua
            turma.tempo_quinta = tempo_qui
            turma.tempo_sexta = tempo_sex

            modulos_existentes = {
                m.id: m for m in Modulo.query.filter_by(turma_id=turma.id).all()
            }
            usados = set()
            if tipo == "profissional":
                for mod_data in modulos_form:
                    mid = mod_data.get("id")
                    if mid and mid in modulos_existentes:
                        mod = modulos_existentes[mid]
                        mod.nome = mod_data["nome"] or mod.nome
                        mod.total_aulas = mod_data["total"]
                        usados.add(mid)
                    else:
                        novo = Modulo(
                            turma_id=turma.id,
                            nome=mod_data["nome"],
                            total_aulas=mod_data["total"],
                        )
                        db.session.add(novo)
            else:
                usados = set(modulos_existentes.keys())

            for mid, mod in modulos_existentes.items():
                if mid not in usados and tipo == "profissional":
                    db.session.delete(mod)

            db.session.commit()
            garantir_periodos_basicos_para_turma(turma)
            flash("Turma atualizada.", "success")
            return redirect(url_for("turmas_list"))

        return render_template(
            "turmas/form.html",
            titulo="Editar Turma",
            turma=turma,
            ano_atual=ano_atual,
            anos_letivos=anos_letivos,
            modulos=Modulo.query.filter_by(turma_id=turma.id).order_by(Modulo.id).all(),
        )

    @app.route("/turmas/add", methods=["GET", "POST"])
    def turmas_add():
        # usar sempre o ano letivo atual
        ano_atual = get_ano_letivo_atual()
        anos_letivos = (
            AnoLetivo.query.order_by(AnoLetivo.data_inicio_ano.desc()).all()
        )
        if not anos_letivos:
            flash("Não há anos letivos configurados.", "error")
            return redirect(url_for("anos_letivos_list"))

        if request.method == "POST":
            nome = (request.form.get("nome") or "").strip()
            tipo = request.form.get("tipo") or "regular"
            periodo_tipo = request.form.get("periodo_tipo") or "anual"
            ano_id = request.form.get("ano_letivo_id", type=int)
            letiva = request.form.get("letiva") == "1"
            carga_seg = request.form.get("carga_segunda", type=float)
            carga_ter = request.form.get("carga_terca", type=float)
            carga_qua = request.form.get("carga_quarta", type=float)
            carga_qui = request.form.get("carga_quinta", type=float)
            carga_sex = request.form.get("carga_sexta", type=float)
            tempo_seg = request.form.get("tempo_segunda", type=int)
            tempo_ter = request.form.get("tempo_terca", type=int)
            tempo_qua = request.form.get("tempo_quarta", type=int)
            tempo_qui = request.form.get("tempo_quinta", type=int)
            tempo_sex = request.form.get("tempo_sexta", type=int)
            modulos_form = _ler_modulos_form()

            if not nome:
                flash("O nome da turma é obrigatório.", "error")
                return render_template(
                    "turmas/form.html",
                    titulo="Nova Turma",
                    turma=None,
                    ano_atual=ano_atual,
                    anos_letivos=anos_letivos,
                    modulos=modulos_form,
                )

            ano_escolhido = AnoLetivo.query.get(ano_id) if ano_id else ano_atual
            if not ano_escolhido or ano_escolhido.fechado:
                flash("Seleciona um ano letivo aberto.", "error")
                return render_template(
                    "turmas/form.html",
                    titulo="Nova Turma",
                    turma=None,
                    ano_atual=ano_atual,
                    anos_letivos=anos_letivos,
                    modulos=modulos_form,
                )

            if tipo == "profissional":
                modulos_validos = [m for m in modulos_form if m.get("nome")]
                if not modulos_validos or any(m["total"] <= 0 for m in modulos_validos):
                    flash(
                        "Adiciona módulos com carga horária positiva para turmas profissionais.",
                        "error",
                    )
                    return render_template(
                        "turmas/form.html",
                        titulo="Nova Turma",
                        turma=None,
                        ano_atual=ano_atual,
                        anos_letivos=anos_letivos,
                        modulos=modulos_form,
                    )
                modulos_form = modulos_validos

            if periodo_tipo not in PERIODOS_TURMA_VALIDOS:
                periodo_tipo = "anual"

            turma = Turma(
                nome=nome,
                tipo=tipo,
                periodo_tipo=periodo_tipo,
                ano_letivo_id=ano_escolhido.id,
                letiva=letiva,
                carga_segunda=carga_seg,
                carga_terca=carga_ter,
                carga_quarta=carga_qua,
                carga_quinta=carga_qui,
                carga_sexta=carga_sex,
                tempo_segunda=tempo_seg,
                tempo_terca=tempo_ter,
                tempo_quarta=tempo_qua,
                tempo_quinta=tempo_qui,
                tempo_sexta=tempo_sex,
            )

            db.session.add(turma)
            db.session.commit()

            if tipo == "profissional":
                for mod_data in modulos_form:
                    novo = Modulo(
                        turma_id=turma.id,
                        nome=mod_data["nome"],
                        total_aulas=mod_data["total"],
                    )
                    db.session.add(novo)
                db.session.commit()

            # Gera automaticamente Anual / 1.º / 2.º semestre para esta turma
            garantir_periodos_basicos_para_turma(turma)
            flash(f"Turma criada no ano letivo {ano_escolhido.nome}.", "success")
            return redirect(url_for("turmas_list"))

        return render_template(
            "turmas/form.html",
            titulo="Nova Turma",
            turma=None,
            ano_atual=ano_atual,
            anos_letivos=anos_letivos,
            modulos=None,
        )

    @app.route("/turmas/<int:turma_id>/alunos", methods=["GET", "POST"])
    def turma_alunos(turma_id):
        turma = (
            Turma.query.options(joinedload(Turma.ano_letivo))
            .filter_by(id=turma_id)
            .first_or_404()
        )
        ano = turma.ano_letivo
        ano_fechado = bool(ano and ano.fechado)

        turmas_destino = (
            Turma.query.options(joinedload(Turma.ano_letivo))
            .filter(Turma.id != turma.id)
            .order_by(Turma.nome)
            .all()
        )
        turmas_destino_abertas = [
            t for t in turmas_destino if not (t.ano_letivo and t.ano_letivo.fechado)
        ]

        def _lista_alunos():
            return (
                Aluno.query.filter_by(turma_id=turma.id)
                .order_by(Aluno.numero.is_(None), Aluno.numero, Aluno.nome)
                .all()
            )

        if request.method == "POST":
            if ano_fechado:
                flash("Ano letivo fechado: não é possível adicionar alunos.", "error")
                return redirect(url_for("turma_alunos", turma_id=turma.id))

            processo = (request.form.get("processo") or "").strip()
            numero_raw = (request.form.get("numero") or "").strip()
            nome = (request.form.get("nome") or "").strip()
            nome_curto = _normalizar_nome_curto(
                nome,
                request.form.get("nome_curto"),
            )
            nee = (request.form.get("nee") or "").strip()
            observacoes = (request.form.get("observacoes") or "").strip()

            numero = None
            if numero_raw:
                try:
                    numero = int(numero_raw)
                except ValueError:
                    flash("Número do aluno inválido.", "error")
                return render_template(
                    "turmas/alunos.html",
                    turma=turma,
                    ano_fechado=ano_fechado,
                    turmas_destino=turmas_destino_abertas,
                    alunos=_lista_alunos(),
                )

            if not nome:
                flash("O nome do aluno é obrigatório.", "error")
                return render_template(
                    "turmas/alunos.html",
                    turma=turma,
                    ano_fechado=ano_fechado,
                    turmas_destino=turmas_destino_abertas,
                    alunos=_lista_alunos(),
                )

            aluno = Aluno(
                turma_id=turma.id,
                processo=processo or None,
                numero=numero,
                nome=nome,
                nome_curto=nome_curto,
                nee=nee or None,
                observacoes=observacoes or None,
            )
            db.session.add(aluno)
            db.session.commit()

            flash("Aluno adicionado.", "success")
            return redirect(url_for("turma_alunos", turma_id=turma.id))

        return render_template(
            "turmas/alunos.html",
            turma=turma,
            ano_fechado=ano_fechado,
            turmas_destino=turmas_destino_abertas,
            alunos=_lista_alunos(),
        )

    @app.route("/turmas/<int:turma_id>/alunos/<int:aluno_id>/update", methods=["POST"])
    def turma_alunos_update(turma_id, aluno_id):
        turma = Turma.query.get_or_404(turma_id)
        ano = turma.ano_letivo
        ano_fechado = bool(ano and ano.fechado)

        aluno = Aluno.query.get_or_404(aluno_id)
        if aluno.turma_id != turma.id:
            flash("Aluno não pertence a esta turma.", "error")
            return redirect(url_for("turma_alunos", turma_id=turma.id))

        if ano_fechado:
            flash("Ano letivo fechado: não é possível editar alunos.", "error")
            return redirect(url_for("turma_alunos", turma_id=turma.id))

        processo = (request.form.get("processo") or "").strip()
        numero_raw = (request.form.get("numero") or "").strip()
        nome = (request.form.get("nome") or "").strip()
        nome_curto = _normalizar_nome_curto(nome, request.form.get("nome_curto"))
        nee = (request.form.get("nee") or "").strip()
        observacoes = (request.form.get("observacoes") or "").strip()

        numero = None
        if numero_raw:
            try:
                numero = int(numero_raw)
            except ValueError:
                flash("Número do aluno inválido.", "error")
                return redirect(url_for("turma_alunos", turma_id=turma.id))

        if not nome:
            flash("O nome do aluno é obrigatório.", "error")
            return redirect(url_for("turma_alunos", turma_id=turma.id))

        aluno.processo = processo or None
        aluno.numero = numero
        aluno.nome = nome
        aluno.nome_curto = nome_curto
        aluno.nee = nee or None
        aluno.observacoes = observacoes or None

        db.session.commit()
        flash("Aluno atualizado.", "success")
        return redirect(url_for("turma_alunos", turma_id=turma.id))

    @app.route("/turmas/<int:turma_id>/alunos/<int:aluno_id>/delete", methods=["POST"])
    def turma_alunos_delete(turma_id, aluno_id):
        turma = Turma.query.get_or_404(turma_id)
        ano = turma.ano_letivo
        ano_fechado = bool(ano and ano.fechado)

        aluno = Aluno.query.get_or_404(aluno_id)
        if aluno.turma_id != turma.id:
            flash("Aluno não pertence a esta turma.", "error")
            return redirect(url_for("turma_alunos", turma_id=turma.id))

        if ano_fechado:
            flash("Ano letivo fechado: não é possível eliminar alunos.", "error")
            return redirect(url_for("turma_alunos", turma_id=turma.id))

        db.session.delete(aluno)
        db.session.commit()
        flash("Aluno removido.", "success")
        return redirect(url_for("turma_alunos", turma_id=turma.id))

    @app.route(
        "/turmas/<int:turma_id>/alunos/import", methods=["POST"], endpoint="turma_alunos_import"
    )
    def turma_alunos_import(turma_id):
        turma = (
            Turma.query.options(joinedload(Turma.ano_letivo))
            .filter_by(id=turma_id)
            .first_or_404()
        )
        ficheiro = request.files.get("ficheiro")
        if not ficheiro or ficheiro.filename == "":
            flash("Selecione um ficheiro CSV.", "error")
            return redirect(url_for("turma_alunos", turma_id=turma.id))

        try:
            conteudo = ficheiro.read().decode("utf-8-sig")
        except Exception:
            flash("Não foi possível ler o ficheiro. Confirme se é um CSV em UTF-8.", "error")
            return redirect(url_for("turma_alunos", turma_id=turma.id))

        sample = conteudo[:1024]
        delim = ";" if sample.count(";") >= sample.count(",") else ","
        reader = csv.DictReader(io.StringIO(conteudo), delimiter=delim)
        if not reader.fieldnames:
            flash("Cabeçalho do CSV inválido.", "error")
            return redirect(url_for("turma_alunos", turma_id=turma.id))

        def _norm_header(texto: str) -> str:
            base = unicodedata.normalize("NFD", (texto or "").strip().lower())
            base = "".join(ch for ch in base if unicodedata.category(ch) != "Mn")
            base = (
                base.replace(" ", "_")
                .replace("-", "_")
                .replace(".", "_")
                .replace("__", "_")
            )
            return base

        header_map = {}
        for h in reader.fieldnames:
            chave = _norm_header(h)
            if chave and chave not in header_map:
                header_map[chave] = h

        obrigatorios = ["nome"]
        if not all(col in header_map for col in obrigatorios):
            flash("O CSV deve incluir pelo menos a coluna 'nome'.", "error")
            return redirect(url_for("turma_alunos", turma_id=turma.id))

        inseridos = 0
        for row in reader:
            def _valor(col):
                header = header_map.get(col)
                return (row.get(header, "") if header else "") or ""

            nome = _valor("nome").strip()
            if not nome:
                continue
            processo = _valor("processo").strip() or None
            numero_raw = _valor("numero").strip()
            nome_curto = _normalizar_nome_curto(nome, _valor("nome_curto"))
            nee = _valor("nee").strip() or None
            observacoes = _valor("observacoes").strip() or None

            numero = None
            if numero_raw:
                try:
                    numero = int(numero_raw)
                except ValueError:
                    pass

            novo = Aluno(
                turma_id=turma.id,
                processo=processo,
                numero=numero,
                nome=nome,
                nome_curto=nome_curto,
                nee=nee,
                observacoes=observacoes,
            )
            db.session.add(novo)
            inseridos += 1

        if inseridos:
            db.session.commit()
            flash(f"{inseridos} aluno(s) importado(s).", "success")
        else:
            db.session.rollback()
            flash("Nenhum aluno importado.", "warning")

        return redirect(url_for("turma_alunos", turma_id=turma.id))

    @app.route(
        "/turmas/<int:turma_id>/alunos/transfer", methods=["POST"], endpoint="turma_alunos_transfer"
    )
    def turma_alunos_transfer(turma_id):
        turma_origem = (
            Turma.query.options(joinedload(Turma.ano_letivo))
            .filter_by(id=turma_id)
            .first_or_404()
        )
        ano_origem_fechado = bool(turma_origem.ano_letivo and turma_origem.ano_letivo.fechado)

        destino_id_raw = (request.form.get("destino_turma") or "").strip()
        acao = (request.form.get("acao") or "").strip()
        selecionados = request.form.getlist("aluno_ids")

        if not selecionados:
            flash("Selecione pelo menos um aluno.", "error")
            return redirect(url_for("turma_alunos", turma_id=turma_origem.id))

        try:
            destino_id = int(destino_id_raw)
        except ValueError:
            flash("Selecione uma turma de destino.", "error")
            return redirect(url_for("turma_alunos", turma_id=turma_origem.id))

        turma_destino = (
            Turma.query.options(joinedload(Turma.ano_letivo))
            .filter_by(id=destino_id)
            .first()
        )
        if not turma_destino or turma_destino.id == turma_origem.id:
            flash("Turma de destino inválida.", "error")
            return redirect(url_for("turma_alunos", turma_id=turma_origem.id))

        ano_destino_fechado = bool(turma_destino.ano_letivo and turma_destino.ano_letivo.fechado)

        if ano_destino_fechado:
            flash("Ano letivo fechado: não é possível adicionar alunos na turma de destino.", "error")
            return redirect(url_for("turma_alunos", turma_id=turma_origem.id))

        alunos = (
            Aluno.query.filter(Aluno.id.in_(selecionados), Aluno.turma_id == turma_origem.id)
            .order_by(Aluno.id)
            .all()
        )
        if not alunos:
            flash("Nenhum aluno válido selecionado.", "error")
            return redirect(url_for("turma_alunos", turma_id=turma_origem.id))

        if acao == "copiar":
            for aluno in alunos:
                copia = Aluno(
                    turma_id=turma_destino.id,
                    processo=aluno.processo,
                    numero=aluno.numero,
                    nome=aluno.nome,
                    nome_curto=aluno.nome_curto,
                    nee=aluno.nee,
                    observacoes=aluno.observacoes,
                )
                db.session.add(copia)
            db.session.commit()
            flash(f"{len(alunos)} aluno(s) copiado(s) para {turma_destino.nome}.", "success")
        elif acao == "mover":
            for aluno in alunos:
                aluno.turma_id = turma_destino.id
            db.session.commit()
            flash(f"{len(alunos)} aluno(s) movido(s) para {turma_destino.nome}.", "success")
        else:
            flash("Ação inválida.", "error")

        return redirect(url_for("turma_alunos", turma_id=turma_origem.id))

    def _listar_alunos_turma(turma_id):
        return (
            Aluno.query.filter_by(turma_id=turma_id)
            .order_by(Aluno.numero.is_(None), Aluno.numero, Aluno.nome)
            .all()
        )

    def _parse_datetime_local(raw):
        if not raw:
            return None
        raw = str(raw).strip()
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except Exception:
            for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%d/%m/%Y", "%d/%m/%Y %H:%M"):
                try:
                    return datetime.strptime(raw, fmt)
                except Exception:
                    continue
        return None

    def _parse_date_local(raw):
        if not raw:
            return None
        raw = str(raw).strip()
        if not raw:
            return None
        try:
            return date.fromisoformat(raw)
        except Exception:
            for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
                try:
                    return datetime.strptime(raw, fmt).date()
                except Exception:
                    continue
        return None

    def _estado_info(trabalho, entrega):
        if not entrega or not entrega.entregue:
            return "Por entregar", "badge-por-entregar", 0.0
        if trabalho.data_limite and entrega.data_entrega and entrega.data_entrega > trabalho.data_limite:
            return "Atrasado", "badge-atrasado", 0.5
        return "No prazo", "badge-no-prazo", 1.0

    def _calcular_metricas_entrega(trabalho, entrega, params_map, parametros):
        estado, estado_css, fator_estado = _estado_info(trabalho, entrega)

        valores = []
        if entrega:
            if entrega.consecucao is not None:
                valores.append(float(entrega.consecucao))
            if entrega.qualidade is not None:
                valores.append(float(entrega.qualidade))

            for p in parametros:
                if p.tipo != "numerico":
                    continue
                ep = params_map.get(p.id)
                if ep and ep.valor_numerico is not None:
                    valores.append(float(ep.valor_numerico))

        media_base = (sum(valores) / len(valores)) if valores else 0.0
        nota_final = media_base * fator_estado

        return {
            "estado": estado,
            "estado_css": estado_css,
            "fator_estado": fator_estado,
            "media_base": media_base,
            "nota_final": nota_final,
        }

    def _ensure_individual_groups(trabalho):
        alunos = _listar_alunos_turma(trabalho.turma_id)
        existing_members = {m.aluno_id for g in trabalho.grupos for m in g.membros}
        for aluno in alunos:
            if aluno.id in existing_members:
                continue
            nome = (aluno.nome_curto or aluno.nome or f"Aluno {aluno.id}").strip()
            grupo = TrabalhoGrupo(trabalho_id=trabalho.id, nome=nome)
            db.session.add(grupo)
            db.session.flush()
            db.session.add(TrabalhoGrupoMembro(trabalho_grupo_id=grupo.id, aluno_id=aluno.id))

    def _build_trabalho_grid(trabalho):
        parametros = sorted(trabalho.parametros, key=lambda p: (p.ordem, p.id))
        entregas = {e.trabalho_grupo_id: e for e in trabalho.entregas}
        rows = []
        for grupo in sorted(trabalho.grupos, key=lambda g: g.nome.lower() if g.nome else ""):
            entrega = entregas.get(grupo.id)
            params_map = {}
            if entrega:
                for ep in entrega.parametros:
                    params_map[ep.parametro_definicao_id] = ep

            metrics = _calcular_metricas_entrega(trabalho, entrega, params_map, parametros)

            membros = sorted(
                [m.aluno for m in grupo.membros if m.aluno],
                key=lambda a: ((a.numero is None), a.numero if a.numero is not None else 0, (a.nome or "").lower()),
            )
            aluno_principal = membros[0] if membros else None
            aluno_label = ""
            if aluno_principal:
                numero = aluno_principal.numero if aluno_principal.numero is not None else "—"
                aluno_label = f"{numero} {aluno_principal.nome_curto_exibicao}".strip()

            rows.append({
                "grupo": grupo,
                "entrega": entrega,
                "params": params_map,
                "membros": membros,
                "aluno_label": aluno_label,
                "estado": metrics["estado"],
                "estado_css": metrics["estado_css"],
                "media_base": metrics["media_base"],
                "fator_estado": metrics["fator_estado"],
                "nota_final": metrics["nota_final"],
            })

        return parametros, rows[:30]

    @app.route("/turmas/<int:turma_id>/grupos", methods=["GET", "POST"])
    def turma_grupos_catalogo(turma_id):
        turma = Turma.query.get_or_404(turma_id)
        if request.method == "POST":
            payload = request.get_json(silent=True) if request.is_json else request.form
            nome = (payload.get("nome") or payload.get("nome_grupo") or "").strip()
            raw_ids = payload.get("aluno_ids") if request.is_json else request.form.getlist("aluno_ids")
            if raw_ids is None:
                raw_ids = []
            if not isinstance(raw_ids, list):
                raw_ids = [raw_ids]
            aluno_ids = sorted({int(v) for v in raw_ids if str(v).isdigit()})
            wants_json = request.is_json or request.accept_mimetypes.best == "application/json"

            if not nome:
                if wants_json:
                    return jsonify({"ok": False, "error": "Nome do grupo é obrigatório."}), 400
                flash("Nome do grupo é obrigatório.", "error")
                return redirect(url_for("turma_grupos_catalogo", turma_id=turma.id))
            if not aluno_ids:
                msg = "Um grupo tem de ter, pelo menos, um aluno."
                if wants_json:
                    return jsonify({"ok": False, "error": msg}), 400
                flash(msg, "error")
                return redirect(url_for("turma_grupos_catalogo", turma_id=turma.id))

            usados = {
                m.aluno_id
                for g in GrupoTurma.query.filter_by(turma_id=turma.id).all()
                for m in g.membros
                if m.aluno_id is not None
            }
            duplicados = [aid for aid in aluno_ids if aid in usados]
            if duplicados:
                msg = "Um ou mais alunos já estão atribuídos a outro grupo da turma."
                if wants_json:
                    return jsonify({"ok": False, "error": msg, "aluno_ids": duplicados}), 400
                flash(msg, "error")
                return redirect(url_for("turma_grupos_catalogo", turma_id=turma.id))

            grupo = GrupoTurma(turma_id=turma.id, nome=nome)
            db.session.add(grupo)
            db.session.flush()
            for aluno_id in aluno_ids:
                db.session.add(GrupoTurmaMembro(grupo_turma_id=grupo.id, aluno_id=aluno_id))
            db.session.commit()

            if wants_json:
                membros_payload = []
                if aluno_ids:
                    alunos_map = {
                        a.id: a
                        for a in Aluno.query.filter(Aluno.id.in_(aluno_ids)).all()
                    }
                    for aid in aluno_ids:
                        a = alunos_map.get(aid)
                        if not a:
                            continue
                        numero = a.numero if a.numero is not None else "—"
                        membros_payload.append({"id": aid, "label": f"{numero} {a.nome_curto_exibicao}".strip()})
                return jsonify({"ok": True, "grupo_id": grupo.id, "nome": grupo.nome, "membros_ids": aluno_ids, "membros": membros_payload})

            flash("Grupo da turma criado.", "success")
            return redirect(url_for("turma_grupos_catalogo", turma_id=turma.id))

        grupos = GrupoTurma.query.filter_by(turma_id=turma.id).order_by(GrupoTurma.nome).all()
        alunos = _listar_alunos_turma(turma.id)
        usados = {
            m.aluno_id
            for g in grupos
            for m in g.membros
            if m.aluno_id is not None
        }
        alunos_disponiveis = [a for a in alunos if a.id not in usados]
        return render_template("trabalhos/catalogo_grupos.html", turma=turma, grupos=grupos, alunos=alunos, alunos_disponiveis=alunos_disponiveis)

    @app.route("/turmas/<int:turma_id>/grupos/<int:grupo_id>/delete", methods=["POST"])
    def turma_grupo_catalogo_delete(turma_id, grupo_id):
        grupo = GrupoTurma.query.filter_by(id=grupo_id, turma_id=turma_id).first_or_404()
        db.session.delete(grupo)
        db.session.commit()
        flash("Grupo do catálogo removido.", "success")
        return redirect(url_for("turma_grupos_catalogo", turma_id=turma_id))

    @app.route("/turmas/<int:turma_id>/grupos/<int:grupo_id>/membros/<int:aluno_id>/remove", methods=["POST"])
    def turma_grupo_remove_membro(turma_id, grupo_id, aluno_id):
        grupo = GrupoTurma.query.filter_by(id=grupo_id, turma_id=turma_id).first_or_404()
        membro = GrupoTurmaMembro.query.filter_by(grupo_turma_id=grupo.id, aluno_id=aluno_id).first()
        if not membro:
            return jsonify({"ok": False, "error": "Aluno não pertence a este grupo."}), 404

        aluno = Aluno.query.filter_by(id=aluno_id, turma_id=turma_id).first()
        numero = aluno.numero if (aluno and aluno.numero is not None) else "—"
        nome_curto = aluno.nome_curto_exibicao if aluno else "Aluno"

        db.session.delete(membro)
        db.session.flush()

        restantes = GrupoTurmaMembro.query.filter_by(grupo_turma_id=grupo.id).count()
        if restantes == 0:
            gid = grupo.id
            db.session.delete(grupo)
            db.session.commit()
            return jsonify({
                "ok": True,
                "deleted": True,
                "group_deleted": True,
                "remaining": 0,
                "grupo_id": gid,
                "membros_repostos": [{"id": aluno_id, "label": f"{numero} {nome_curto}".strip()}],
            })

        db.session.commit()
        return jsonify({
            "ok": True,
            "deleted": False,
            "group_deleted": False,
            "remaining": restantes,
            "grupo_id": grupo.id,
            "removed_members_ids": [aluno_id],
            "membros_repostos": [{"id": aluno_id, "label": f"{numero} {nome_curto}".strip()}],
        })

    @app.route("/turmas/<int:turma_id>/trabalhos", methods=["GET", "POST"])
    def turma_trabalhos(turma_id):
        turma = Turma.query.get_or_404(turma_id)
        turmas_letivas = (
            Turma.query
            .filter(Turma.letiva.is_(True))
            .order_by(Turma.nome.asc())
            .all()
        )
        if request.method == "POST":
            titulo = (request.form.get("titulo") or "").strip()
            if not titulo:
                flash("Título é obrigatório.", "error")
                return redirect(url_for("turma_trabalhos", turma_id=turma.id))

            trabalho = Trabalho(
                turma_id=turma.id,
                titulo=titulo,
                descricao=(request.form.get("descricao") or "").strip() or None,
                modo=(request.form.get("modo") or "individual").strip().lower(),
                data_limite=_parse_date_local(request.form.get("data_limite")),
            )
            if trabalho.modo not in {"individual", "grupo"}:
                trabalho.modo = "individual"
            db.session.add(trabalho)
            db.session.commit()
            flash("Trabalho criado.", "success")
            return redirect(url_for("trabalho_detail", turma_id=turma.id, trabalho_id=trabalho.id))

        trabalhos = Trabalho.query.filter_by(turma_id=turma.id).order_by(Trabalho.created_at.desc()).all()
        return render_template(
            "trabalhos/list.html",
            turma=turma,
            turma_atual=turma,
            turmas_letivas=turmas_letivas,
            trabalhos=trabalhos,
        )

    @app.route("/turmas/<int:turma_id>/trabalhos/mapa")
    def turma_trabalhos_mapa(turma_id):
        turma = Turma.query.get_or_404(turma_id)
        trabalhos = Trabalho.query.filter_by(turma_id=turma.id).order_by(Trabalho.created_at.asc(), Trabalho.id.asc()).all()

        houve_alteracao = False
        for trabalho in trabalhos:
            if trabalho.modo == "individual":
                before = sum(len(g.membros) for g in trabalho.grupos)
                _ensure_individual_groups(trabalho)
                after = sum(len(g.membros) for g in trabalho.grupos)
                if after != before:
                    houve_alteracao = True
        if houve_alteracao:
            db.session.commit()
            trabalhos = Trabalho.query.filter_by(turma_id=turma.id).order_by(Trabalho.created_at.asc(), Trabalho.id.asc()).all()

        alunos = _listar_alunos_turma(turma.id)
        parametros_por_trabalho = {
            t.id: sorted(t.parametros, key=lambda p: (p.ordem, p.id))
            for t in trabalhos
        }

        grupo_por_aluno_trabalho = {}
        for t in trabalhos:
            mapping = {}
            for g in t.grupos:
                for m in g.membros:
                    mapping[m.aluno_id] = g
            grupo_por_aluno_trabalho[t.id] = mapping

        entregas_por_chave = {}
        for t in trabalhos:
            for e in t.entregas:
                entregas_por_chave[(t.id, e.trabalho_grupo_id)] = e

        mapa_rows = []
        for aluno in alunos:
            cells = []
            notas = []
            for t in trabalhos:
                grupo = grupo_por_aluno_trabalho.get(t.id, {}).get(aluno.id)
                entrega = entregas_por_chave.get((t.id, grupo.id)) if grupo else None
                params_map = {ep.parametro_definicao_id: ep for ep in (entrega.parametros if entrega else [])}
                metrics = _calcular_metricas_entrega(t, entrega, params_map, parametros_por_trabalho.get(t.id, []))
                nota = metrics["nota_final"] if entrega else 0.0
                cells.append({"nota_final": nota})
                notas.append(nota)

            media_global = (sum(notas) / len(notas)) if notas else 0.0
            mapa_rows.append({
                "aluno": aluno,
                "cells": cells,
                "media_global": media_global,
            })

        return render_template("trabalhos/mapa.html", turma=turma, trabalhos=trabalhos, mapa_rows=mapa_rows)

    @app.route("/turmas/<int:turma_id>/trabalhos/<int:trabalho_id>/delete", methods=["POST"])
    def trabalho_delete(turma_id, trabalho_id):
        trabalho = Trabalho.query.filter_by(id=trabalho_id, turma_id=turma_id).first_or_404()
        db.session.delete(trabalho)
        db.session.commit()
        flash("Trabalho removido.", "success")
        return redirect(url_for("turma_trabalhos", turma_id=turma_id))

    @app.route("/turmas/<int:turma_id>/trabalhos/<int:trabalho_id>/importar-grupos", methods=["POST"])
    def trabalho_importar_grupos_turma(turma_id, trabalho_id):
        trabalho = Trabalho.query.filter_by(id=trabalho_id, turma_id=turma_id).first_or_404()
        catalogo = GrupoTurma.query.filter_by(turma_id=turma_id).all()
        if not catalogo:
            flash("Não existem grupos no catálogo da turma.", "error")
            return redirect(url_for("trabalho_detail", turma_id=turma_id, trabalho_id=trabalho_id))

        if trabalho.modo != "grupo":
            trabalho.modo = "grupo"

        for g in catalogo:
            membro_ids = [m.aluno_id for m in g.membros if m.aluno_id is not None]
            if not membro_ids:
                continue
            nome = g.nome
            exists = TrabalhoGrupo.query.filter_by(trabalho_id=trabalho.id, nome=nome).first()
            if exists:
                continue
            ng = TrabalhoGrupo(trabalho_id=trabalho.id, nome=nome)
            db.session.add(ng)
            db.session.flush()
            for aluno_id in membro_ids:
                db.session.add(TrabalhoGrupoMembro(trabalho_grupo_id=ng.id, aluno_id=aluno_id))

        db.session.commit()
        flash("Grupos importados para este trabalho (snapshot).", "success")
        return redirect(url_for("trabalho_detail", turma_id=turma_id, trabalho_id=trabalho_id))

    @app.route("/turmas/<int:turma_id>/trabalhos/<int:trabalho_id>")
    def trabalho_detail(turma_id, trabalho_id):
        trabalho = Trabalho.query.filter_by(id=trabalho_id, turma_id=turma_id).first_or_404()
        if trabalho.modo == "individual":
            _ensure_individual_groups(trabalho)
            db.session.commit()

        parametros, rows = _build_trabalho_grid(trabalho)
        alunos = _listar_alunos_turma(turma_id)
        usados = {
            m.aluno_id
            for grupo in trabalho.grupos
            for m in grupo.membros
            if m.aluno_id is not None
        }
        alunos_disponiveis = [a for a in alunos if a.id not in usados]
        return render_template(
            "trabalhos/detail.html",
            trabalho=trabalho,
            turma=trabalho.turma,
            parametros=parametros,
            rows=rows,
            alunos=alunos,
            alunos_disponiveis=alunos_disponiveis,
        )

    @app.route("/turmas/<int:turma_id>/trabalhos/<int:trabalho_id>/edit", methods=["GET", "POST"])
    def trabalho_edit(turma_id, trabalho_id):
        trabalho = Trabalho.query.filter_by(id=trabalho_id, turma_id=turma_id).first_or_404()

        if request.method == "POST":
            titulo = (request.form.get("titulo") or "").strip()
            descricao = (request.form.get("descricao") or "").strip() or None
            modo = (request.form.get("modo") or trabalho.modo or "individual").strip().lower()
            data_limite_raw = request.form.get("data_limite")

            if not titulo:
                flash("Título é obrigatório.", "error")
                return redirect(url_for("trabalho_edit", turma_id=turma_id, trabalho_id=trabalho_id, toast="error"))

            if modo not in {"individual", "grupo"}:
                modo = trabalho.modo if trabalho.modo in {"individual", "grupo"} else "individual"

            parsed_data_limite = _parse_date_local(data_limite_raw)
            if data_limite_raw and str(data_limite_raw).strip() and parsed_data_limite is None:
                flash("Data limite inválida.", "error")
                return redirect(url_for("trabalho_edit", turma_id=turma_id, trabalho_id=trabalho_id, toast="error"))

            try:
                trabalho.titulo = titulo
                trabalho.descricao = descricao
                trabalho.modo = modo
                trabalho.data_limite = parsed_data_limite
                if trabalho.modo == "individual":
                    _ensure_individual_groups(trabalho)
                db.session.commit()
                flash("Trabalho atualizado.", "success")
                return redirect(url_for("trabalho_detail", turma_id=turma_id, trabalho_id=trabalho_id, toast="updated"))
            except Exception:
                db.session.rollback()
                app.logger.exception("Erro ao atualizar trabalho id=%s turma=%s", trabalho_id, turma_id)
                flash("Erro ao atualizar trabalho.", "error")
                return redirect(url_for("trabalho_edit", turma_id=turma_id, trabalho_id=trabalho_id, toast="error"))

        return render_template("trabalhos/edit.html", trabalho=trabalho, turma=trabalho.turma)

    @app.route("/turmas/<int:turma_id>/trabalhos/<int:trabalho_id>/parametros", methods=["POST"])
    def trabalho_add_parametro(turma_id, trabalho_id):
        trabalho = Trabalho.query.filter_by(id=trabalho_id, turma_id=turma_id).first_or_404()
        nome = (request.form.get("nome") or "").strip()
        tipo = (request.form.get("tipo") or "numerico").strip().lower()
        if tipo not in {"numerico", "texto"}:
            tipo = "numerico"
        if not nome:
            flash("Nome do parâmetro é obrigatório.", "error")
            return redirect(url_for("trabalho_detail", turma_id=turma_id, trabalho_id=trabalho_id))

        exists = ParametroDefinicao.query.filter_by(trabalho_id=trabalho.id, nome=nome).first()
        if exists:
            flash("Já existe um parâmetro com esse nome.", "error")
            return redirect(url_for("trabalho_detail", turma_id=turma_id, trabalho_id=trabalho_id))

        ordem = (db.session.query(func.max(ParametroDefinicao.ordem)).filter_by(trabalho_id=trabalho.id).scalar() or 0) + 1
        db.session.add(ParametroDefinicao(trabalho_id=trabalho.id, nome=nome, tipo=tipo, ordem=ordem))
        db.session.commit()
        flash("Parâmetro adicionado.", "success")
        return redirect(url_for("trabalho_detail", turma_id=turma_id, trabalho_id=trabalho_id))

    @app.route("/turmas/<int:turma_id>/trabalhos/<int:trabalho_id>/grupos", methods=["POST"])
    def trabalho_add_grupo(turma_id, trabalho_id):
        trabalho = Trabalho.query.filter_by(id=trabalho_id, turma_id=turma_id).first_or_404()
        payload = request.get_json(silent=True) if request.is_json else request.form
        nome = (payload.get("nome") or payload.get("nome_grupo") or "").strip()

        raw_ids = payload.get("aluno_ids") if request.is_json else request.form.getlist("aluno_ids")
        if raw_ids is None:
            raw_ids = []
        if not isinstance(raw_ids, list):
            raw_ids = [raw_ids]
        aluno_ids = sorted({int(v) for v in raw_ids if str(v).isdigit()})

        wants_json = request.is_json or request.accept_mimetypes.best == "application/json"

        if not nome:
            if wants_json:
                return jsonify({"ok": False, "error": "Nome do grupo é obrigatório."}), 400
            flash("Nome do grupo é obrigatório.", "error")
            return redirect(url_for("trabalho_detail", turma_id=turma_id, trabalho_id=trabalho_id))
        if not aluno_ids:
            msg = "Um grupo tem de ter, pelo menos, um aluno."
            if wants_json:
                return jsonify({"ok": False, "error": msg}), 400
            flash(msg, "error")
            return redirect(url_for("trabalho_detail", turma_id=turma_id, trabalho_id=trabalho_id))
        if trabalho.modo != "grupo":
            if wants_json:
                return jsonify({"ok": False, "error": "Trabalho está em modo individual."}), 400
            flash("Trabalho está em modo individual.", "error")
            return redirect(url_for("trabalho_detail", turma_id=turma_id, trabalho_id=trabalho_id))

        usados = {
            m.aluno_id
            for grupo in trabalho.grupos
            for m in grupo.membros
            if m.aluno_id is not None
        }
        duplicados = [aid for aid in aluno_ids if aid in usados]
        if duplicados:
            msg = "Um ou mais alunos já estão atribuídos a outro grupo deste trabalho."
            if wants_json:
                return jsonify({"ok": False, "error": msg, "aluno_ids": duplicados}), 400
            flash(msg, "error")
            return redirect(url_for("trabalho_detail", turma_id=turma_id, trabalho_id=trabalho_id))

        grupo = TrabalhoGrupo(trabalho_id=trabalho.id, nome=nome)
        db.session.add(grupo)
        db.session.flush()
        for aluno_id in aluno_ids:
            db.session.add(TrabalhoGrupoMembro(trabalho_grupo_id=grupo.id, aluno_id=aluno_id))
        db.session.commit()

        if wants_json:
            return jsonify({"ok": True, "grupo_id": grupo.id, "membros_ids": aluno_ids})

        flash("Grupo criado.", "success")
        return redirect(url_for("trabalho_detail", turma_id=turma_id, trabalho_id=trabalho_id))

    @app.route("/turmas/<int:turma_id>/trabalhos/<int:trabalho_id>/grupos/<int:grupo_id>/membros/<int:aluno_id>/remove", methods=["POST"])
    def trabalho_remove_membro_grupo(turma_id, trabalho_id, grupo_id, aluno_id):
        trabalho = Trabalho.query.filter_by(id=trabalho_id, turma_id=turma_id).first_or_404()
        grupo = TrabalhoGrupo.query.filter_by(id=grupo_id, trabalho_id=trabalho.id).first_or_404()

        membro = TrabalhoGrupoMembro.query.filter_by(trabalho_grupo_id=grupo.id, aluno_id=aluno_id).first()
        if not membro:
            return jsonify({"ok": False, "error": "Aluno não pertence a este grupo."}), 404

        aluno = Aluno.query.filter_by(id=aluno_id, turma_id=turma_id).first()
        numero = aluno.numero if (aluno and aluno.numero is not None) else "—"
        nome_curto = aluno.nome_curto_exibicao if aluno else "Aluno"

        db.session.delete(membro)
        db.session.flush()

        restantes = TrabalhoGrupoMembro.query.filter_by(trabalho_grupo_id=grupo.id).count()
        if restantes == 0:
            entrega = Entrega.query.filter_by(trabalho_grupo_id=grupo.id).first()
            if entrega:
                for ep in list(entrega.parametros):
                    db.session.delete(ep)
                db.session.delete(entrega)
            grupo_id_deleted = grupo.id
            db.session.delete(grupo)
            db.session.commit()
            return jsonify({
                "ok": True,
                "deleted": True,
                "group_deleted": True,
                "remaining": 0,
                "grupo_id": grupo_id_deleted,
                "aluno": {
                    "id": aluno_id,
                    "label": f"{numero} {nome_curto}".strip(),
                },
            })

        db.session.commit()
        return jsonify({
            "ok": True,
            "deleted": False,
            "group_deleted": False,
            "remaining": restantes,
            "grupo_id": grupo.id,
            "aluno": {
                "id": aluno_id,
                "label": f"{numero} {nome_curto}".strip(),
            },
        })

    @app.route("/turmas/<int:turma_id>/trabalhos/<int:trabalho_id>/entregas/<int:grupo_id>/save", methods=["POST"])
    def trabalho_save_entrega(turma_id, trabalho_id, grupo_id):
        trabalho = Trabalho.query.filter_by(id=trabalho_id, turma_id=turma_id).first_or_404()
        grupo = TrabalhoGrupo.query.filter_by(id=grupo_id, trabalho_id=trabalho.id).first_or_404()

        payload = request.get_json(silent=True) or request.form
        entregue = bool(payload.get("entregue"))

        def _score(name):
            raw = payload.get(name)
            if raw in (None, ""):
                return None
            v = int(raw)
            if v < 1 or v > 5:
                raise ValueError(f"{name} fora do intervalo 1..5")
            return v

        try:
            consecucao = _score("consecucao")
            qualidade = _score("qualidade")
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        entrega = Entrega.query.filter_by(trabalho_id=trabalho.id, trabalho_grupo_id=grupo.id).first()
        if not entrega:
            entrega = Entrega(trabalho_id=trabalho.id, trabalho_grupo_id=grupo.id)
            db.session.add(entrega)
            db.session.flush()

        entrega.entregue = entregue
        entrega.consecucao = consecucao
        entrega.qualidade = qualidade
        entrega.observacoes = (payload.get("observacoes") or "").strip() or None

        parsed_data_entrega = _parse_date_local(payload.get("data_entrega"))
        if entregue:
            entrega.data_entrega = parsed_data_entrega or date.today()
        else:
            entrega.data_entrega = None
        entrega.updated_at = datetime.utcnow()

        parametros = ParametroDefinicao.query.filter_by(trabalho_id=trabalho.id).all()
        defs_by_id = {p.id: p for p in parametros}
        extra = payload.get("extra") or {}
        if isinstance(extra, str):
            extra = {}

        for param_id, value in extra.items():
            try:
                pid = int(param_id)
            except Exception:
                continue
            definicao = defs_by_id.get(pid)
            if not definicao:
                continue

            ep = EntregaParametro.query.filter_by(entrega_id=entrega.id, parametro_definicao_id=pid).first()
            if not ep:
                ep = EntregaParametro(entrega_id=entrega.id, parametro_definicao_id=pid)
                db.session.add(ep)

            if definicao.tipo == "numerico":
                if value in (None, ""):
                    ep.valor_numerico = None
                    ep.valor_texto = None
                else:
                    iv = int(value)
                    if iv < 1 or iv > 5:
                        return jsonify({"ok": False, "error": f"{definicao.nome} fora do intervalo 1..5"}), 400
                    ep.valor_numerico = iv
                    ep.valor_texto = None
            else:
                ep.valor_texto = (str(value).strip() if value is not None else None) or None
                ep.valor_numerico = None

        db.session.commit()

        params_map = {ep.parametro_definicao_id: ep for ep in entrega.parametros}
        metrics = _calcular_metricas_entrega(trabalho, entrega, params_map, parametros)

        return jsonify({
            "ok": True,
            "updated_at": entrega.updated_at.isoformat(timespec="seconds"),
            "data_entrega": entrega.data_entrega.isoformat() if entrega.data_entrega else None,
            "estado": metrics["estado"],
            "estado_css": metrics["estado_css"],
            "media_base": round(metrics["media_base"], 2),
            "fator_estado": round(metrics["fator_estado"], 2),
            "nota_final": round(metrics["nota_final"], 2),
        })

    @app.route("/turmas/<int:turma_id>/calendario")
    def turma_calendario(turma_id):
        turma = Turma.query.get_or_404(turma_id)
        ano = turma.ano_letivo
        ano_fechado = bool(ano and ano.fechado)

        periodos_base = (
            Periodo.query
            .filter_by(turma_id=turma.id)
            .order_by(Periodo.data_inicio)
            .all()
        )
        periodos_disponiveis = filtrar_periodos_para_turma(turma, periodos_base)
        periodos_export = list(periodos_disponiveis)
        if turma.periodo_tipo == "anual":
            extras = [p for p in periodos_base if p.tipo in ("semestre1", "semestre2")]
            periodos_map = {p.id: p for p in periodos_export}
            for periodo in extras:
                periodos_map.setdefault(periodo.id, periodo)
            periodos_export = sorted(
                periodos_map.values(),
                key=lambda p: (p.data_inicio or date.min, p.data_fim or date.min),
            )

        periodo_id = request.args.get("periodo_id", type=int)
        periodo_atual = None
        if periodo_id:
            periodo_atual = Periodo.query.get(periodo_id)
        elif periodos_disponiveis:
            periodo_atual = periodos_disponiveis[0]

        query_aulas = CalendarioAula.query.filter_by(
            turma_id=turma.id, apagado=False
        )
        if periodo_atual:
            query_aulas = query_aulas.filter_by(periodo_id=periodo_atual.id)
        aulas = query_aulas.order_by(CalendarioAula.data).all()
        faltas_por_aula = _mapear_alunos_em_falta(aulas)
        aulas_com_avaliacao = _mapear_aulas_com_avaliacao(aulas)
        sumarios_anteriores = _mapear_sumarios_anteriores(aulas)

        calendario_existe = (
            db.session.query(CalendarioAula.id)
            .filter_by(turma_id=turma.id, apagado=False)
            .first()
            is not None
        )

        return render_template(
            "turmas/calendario.html",
            turma=turma,
            ano=ano,
            ano_fechado=ano_fechado,
            aulas=aulas,
            faltas_por_aula=faltas_por_aula,
            aulas_com_avaliacao=aulas_com_avaliacao,
            sumarios_anteriores=sumarios_anteriores,
            periodo_atual=periodo_atual,
            periodos_disponiveis=periodos_disponiveis,
            periodos_export=periodos_export,
            calendario_existe=calendario_existe,
            tipos_sem_aula=DEFAULT_TIPOS_SEM_AULA,
            tipos_aula=TIPOS_AULA,
            tipo_labels=dict(TIPOS_AULA),
        )

    @app.route("/turmas/<int:turma_id>/calendario/simplificado")
    def turma_calendario_simplificado(turma_id):
        turma = Turma.query.get_or_404(turma_id)
        ano = turma.ano_letivo
        ano_fechado = bool(ano and ano.fechado)

        periodos_base = (
            Periodo.query.filter_by(turma_id=turma.id)
            .order_by(Periodo.data_inicio)
            .all()
        )
        periodos_disponiveis = filtrar_periodos_para_turma(turma, periodos_base)

        periodo_id = request.args.get("periodo_id", type=int)
        periodo_atual = None
        if periodo_id:
            periodo_atual = Periodo.query.get(periodo_id)
        elif periodos_disponiveis:
            periodo_atual = periodos_disponiveis[0]

        query_aulas = CalendarioAula.query.filter_by(
            turma_id=turma.id, apagado=False
        )
        if periodo_atual:
            query_aulas = query_aulas.filter_by(periodo_id=periodo_atual.id)
        aulas = query_aulas.order_by(CalendarioAula.data).all()

        return render_template(
            "turmas/calendario_simplificado.html",
            turma=turma,
            ano=ano,
            ano_fechado=ano_fechado,
            aulas=aulas,
            periodo_atual=periodo_atual,
            periodos_disponiveis=periodos_disponiveis,
        )

    @app.route("/turmas/<int:turma_id>/mapa-avaliacao-diaria")
    def turma_mapa_avaliacao_diaria(turma_id):
        turma = Turma.query.get_or_404(turma_id)
        ano = turma.ano_letivo

        modulos = (
            Modulo.query.filter_by(turma_id=turma.id)
            .order_by(Modulo.nome)
            .all()
        )

        periodos_base = (
            Periodo.query.filter_by(turma_id=turma.id)
            .order_by(Periodo.data_inicio)
            .all()
        )
        periodos_disponiveis = filtrar_periodos_para_turma(turma, periodos_base)
        if turma.periodo_tipo == "anual":
            extras = [p for p in periodos_base if p.tipo in ("semestre1", "semestre2")]
            periodos_map = {p.id: p for p in periodos_disponiveis}
            for periodo in extras:
                periodos_map.setdefault(periodo.id, periodo)
            periodos_disponiveis = sorted(
                periodos_map.values(),
                key=lambda p: (p.data_inicio or date.min, p.data_fim or date.min),
            )

        periodo_id = request.args.get("periodo_id", type=int)
        modulo_id = request.args.get("modulo_id", type=int)
        periodo_atual = None
        if periodo_id:
            periodo_atual = next((p for p in periodos_disponiveis if p.id == periodo_id), None)
        elif periodos_disponiveis:
            periodo_atual = periodos_disponiveis[0]

        data_inicio = _parse_date_form(request.args.get("data_inicio"))
        data_fim = _parse_date_form(request.args.get("data_fim"))

        if not data_inicio and periodo_atual:
            data_inicio = periodo_atual.data_inicio
        if not data_fim and periodo_atual:
            data_fim = periodo_atual.data_fim

        alunos = (
            Aluno.query.filter_by(turma_id=turma.id)
            .order_by(Aluno.numero.is_(None), Aluno.numero, Aluno.nome)
            .all()
        )

        periodo_filtro_id = periodo_atual.id if periodo_atual else None
        if turma.periodo_tipo == "anual" and periodo_atual and periodo_atual.tipo in ("semestre1", "semestre2"):
            periodo_filtro_id = None

        mapa = calcular_mapa_avaliacao_diaria(
            turma,
            alunos,
            data_inicio=data_inicio,
            data_fim=data_fim,
            periodo_id=periodo_filtro_id,
            modulo_id=modulo_id,
        )
        dias = mapa.get("dias", [])
        atividades = mapa.get("atividades", [])

        return render_template(
            "turmas/mapa_avaliacao_diaria.html",
            turma=turma,
            ano=ano,
            dias=dias,
            atividades=atividades,
            alunos=alunos,
            periodo_atual=periodo_atual,
            periodos_disponiveis=periodos_disponiveis,
            modulos=modulos,
            modulo_id=modulo_id,
            data_inicio=data_inicio,
            data_fim=data_fim,
        )

    @app.route("/turmas/<int:turma_id>/mapa-avaliacao-diaria/export")
    def turma_mapa_avaliacao_diaria_export(turma_id):
        turma = Turma.query.get_or_404(turma_id)

        modulos = (
            Modulo.query.filter_by(turma_id=turma.id)
            .order_by(Modulo.nome)
            .all()
        )

        periodos_base = (
            Periodo.query.filter_by(turma_id=turma.id)
            .order_by(Periodo.data_inicio)
            .all()
        )
        periodos_disponiveis = filtrar_periodos_para_turma(turma, periodos_base)
        if turma.periodo_tipo == "anual":
            extras = [p for p in periodos_base if p.tipo in ("semestre1", "semestre2")]
            periodos_map = {p.id: p for p in periodos_disponiveis}
            for periodo in extras:
                periodos_map.setdefault(periodo.id, periodo)
            periodos_disponiveis = sorted(
                periodos_map.values(),
                key=lambda p: (p.data_inicio or date.min, p.data_fim or date.min),
            )

        periodo_id = request.args.get("periodo_id", type=int)
        modulo_id = request.args.get("modulo_id", type=int)
        periodo_atual = None
        if periodo_id:
            periodo_atual = next((p for p in periodos_disponiveis if p.id == periodo_id), None)
        elif periodos_disponiveis:
            periodo_atual = periodos_disponiveis[0]

        data_inicio = _parse_date_form(request.args.get("data_inicio"))
        data_fim = _parse_date_form(request.args.get("data_fim"))

        if not data_inicio and periodo_atual:
            data_inicio = periodo_atual.data_inicio
        if not data_fim and periodo_atual:
            data_fim = periodo_atual.data_fim

        alunos = (
            Aluno.query.filter_by(turma_id=turma.id)
            .order_by(Aluno.numero.is_(None), Aluno.numero, Aluno.nome)
            .all()
        )

        periodo_filtro_id = periodo_atual.id if periodo_atual else None
        if turma.periodo_tipo == "anual" and periodo_atual and periodo_atual.tipo in ("semestre1", "semestre2"):
            periodo_filtro_id = None

        mapa = calcular_mapa_avaliacao_diaria(
            turma,
            alunos,
            data_inicio=data_inicio,
            data_fim=data_fim,
            periodo_id=periodo_filtro_id,
            modulo_id=modulo_id,
        )
        dias = mapa.get("dias", [])
        atividades = mapa.get("atividades", [])

        datas = dias

        def _media_formatada(valor):
            return "—" if valor is None else f"{valor:.2f}"

        safe_nome = unicodedata.normalize("NFKD", turma.nome).encode("ascii", "ignore").decode()
        safe_nome = "_".join(filter(None, ["".join(c if c.isalnum() else "_" for c in safe_nome).strip("_")]))
        if not safe_nome:
            safe_nome = "turma"
        data_export = datetime.now().strftime("%Y%m%d")
        filename = f"mapa_avaliacao_{safe_nome}_{data_export}.xls"

        output = io.StringIO()
        output.write("<html><head><meta charset='utf-8'></head><body>")
        output.write("<table border='1'>")
        output.write("<thead><tr><th>#</th><th>Aluno</th>")
        for d in datas:
            sumarios_txt = d.get("sumarios")
            titulo = d["data"].strftime("%d/%m/%Y")
            if sumarios_txt:
                titulo += f"<br>N.º {sumarios_txt}"
            if d.get("tem_falta_disciplinar") or d.get("tem_avaliacao_negativa"):
                if d.get("tem_falta_disciplinar"):
                    titulo += "<br><small style='color:#dc3545;font-weight:bold'>Falta disciplinar</small>"
                if d.get("tem_avaliacao_negativa"):
                    titulo += "<br><small style='color:#dc3545;font-weight:bold'>Avaliação negativa</small>"
                output.write("<th style='background:#f8d7da;'>" + titulo + "</th>")
            else:
                output.write(f"<th>{titulo}</th>")
        output.write("<th>Faltas</th><th>Média</th></tr></thead><tbody>")

        for aluno in alunos:
            valores = []
            faltas_total = 0
            output.write("<tr>")
            output.write(f"<td>{aluno.numero if aluno.numero is not None else '--'}</td>")
            output.write(f"<td>{aluno.nome}</td>")
            for dia in dias:
                media = dia["medias"].get(aluno.id)
                falta_disc = dia.get("falta_disciplinar_por_aluno", {}).get(aluno.id)
                avaliacao_negativa = dia.get("avaliacao_negativa_por_aluno", {}).get(aluno.id)
                if media is not None:
                    valores.append(media)
                estilo = (
                    " style='background:#f8d7da;'"
                    if falta_disc
                    or avaliacao_negativa
                    or dia.get("tem_falta_disciplinar")
                    or dia.get("tem_avaliacao_negativa")
                    else ""
                )
                output.write(f"<td{estilo}>{_media_formatada(media)}</td>")
                faltas_total += dia.get("faltas", {}).get(aluno.id, 0)
            output.write(f"<td>{faltas_total}</td>")
            if valores:
                media_final = sum(valores) / len(valores)
                output.write(f"<td>{media_final:.2f}</td>")
            else:
                output.write("<td>—</td>")
            output.write("</tr>")

        output.write("</tbody></table>")

        if atividades:
            output.write("<br><br><table border='1'>")
            output.write("<thead><tr><th>#</th><th>Aluno</th>")
            for at in atividades:
                titulo = f"{at['data'].strftime('%d/%m/%Y')} — {at['titulo']}" if at.get('titulo') else at['data'].strftime('%d/%m/%Y')
                output.write(f"<th>{titulo}</th>")
            output.write("<th>Média atividades</th></tr></thead><tbody>")

            for aluno in alunos:
                notas_aluno = []
                output.write("<tr>")
                output.write(f"<td>{aluno.numero if aluno.numero is not None else '--'}</td>")
                output.write(f"<td>{aluno.nome}</td>")
                for at in atividades:
                    nota = at.get("notas", {}).get(aluno.id)
                    if nota is not None:
                        notas_aluno.append(nota)
                    output.write(f"<td>{_media_formatada(nota)}</td>")
                if notas_aluno:
                    media_ativ = sum(notas_aluno) / len(notas_aluno)
                    output.write(f"<td>{media_ativ:.2f}</td>")
                else:
                    output.write("<td>—</td>")
                output.write("</tr>")

            output.write("</tbody></table>")

        output.write("</body></html>")

        return Response(
            output.getvalue(),
            mimetype="application/vnd.ms-excel",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    @app.route("/calendario/dia")
    @app.route("/turmas/<int:turma_id>/calendario/dia")
    def turma_calendario_dia(turma_id=None):
        todas_turmas = turmas_abertas_ativas()

        turma_id_param = request.args.get("turma_id", type=int)
        turma_selecionada = None
        if turma_id_param:
            turma_selecionada = Turma.query.get(turma_id_param)
        elif turma_id:
            turma_selecionada = Turma.query.get_or_404(turma_id)

        periodo_id = request.args.get("periodo_id", type=int)
        periodos_disponiveis = []
        periodo_atual = None
        if turma_selecionada:
            periodos_disponiveis = filtrar_periodos_para_turma(
                turma_selecionada,
                (
                    Periodo.query.filter_by(turma_id=turma_selecionada.id)
                    .order_by(Periodo.data_inicio)
                    .all()
                ),
            )
            if periodo_id:
                periodo_atual = next(
                    (p for p in periodos_disponiveis if p.id == periodo_id), None
                )
            if not periodo_atual and periodos_disponiveis:
                periodo_atual = periodos_disponiveis[0]

        data_txt = request.args.get("data")
        hoje = date.today()
        try:
            data_atual = date.fromisoformat(data_txt) if data_txt else hoje
        except ValueError:
            data_atual = hoje

        duplicados = (
            db.session.query(CalendarioAula.turma_id)
            .filter(
                CalendarioAula.apagado == False,  # noqa: E712
                CalendarioAula.data == data_atual,
            )
            .group_by(CalendarioAula.turma_id)
            .having(func.count(CalendarioAula.id) > 1)
            .all()
        )
        for (turma_dup_id,) in duplicados:
            renumerar_calendario_turma(turma_dup_id)

        query = (
            CalendarioAula.query.options(
                joinedload(CalendarioAula.turma).joinedload(Turma.ano_letivo),
                joinedload(CalendarioAula.modulo),
            )
            .filter_by(apagado=False)
            .filter(CalendarioAula.data == data_atual)
            .join(Turma)
        )
        if turma_selecionada:
            query = query.filter(CalendarioAula.turma_id == turma_selecionada.id)
        if periodo_atual:
            query = query.filter(CalendarioAula.periodo_id == periodo_atual.id)

        aulas = (
            query.order_by(
                Turma.nome.asc(),
                CalendarioAula.data.asc(),
                CalendarioAula.numero_modulo.asc().nulls_last(),
                CalendarioAula.total_geral.asc().nulls_last(),
                CalendarioAula.id.asc(),
            )
            .all()
        )

        aulas.sort(key=_chave_ordenacao_aula)
        tempos_por_aula = {
            a.id: _tempo_da_turma_no_dia(a.turma, a.data) for a in aulas
        }

        anos_fechados = {
            a.turma_id: bool(a.turma and a.turma.ano_letivo and a.turma.ano_letivo.fechado)
            for a in aulas
            if a.turma_id
        }
        faltas_por_aula = _mapear_alunos_em_falta(aulas)
        aulas_com_avaliacao = _mapear_aulas_com_avaliacao(aulas)
        sumarios_anteriores = _mapear_sumarios_anteriores(aulas)

        return render_template(
            "turmas/calendario_diario.html",
            turma=turma_selecionada,
            periodo_atual=periodo_atual,
            periodos_disponiveis=periodos_disponiveis,
            aulas=aulas,
            faltas_por_aula=faltas_por_aula,
            aulas_com_avaliacao=aulas_com_avaliacao,
            tempos_por_aula=tempos_por_aula,
            sumarios_anteriores=sumarios_anteriores,
            data_atual=data_atual,
            dia_anterior=data_atual - timedelta(days=1),
            dia_seguinte=data_atual + timedelta(days=1),
            tipos_sem_aula=DEFAULT_TIPOS_SEM_AULA,
            tipos_aula=TIPOS_AULA,
            tipo_labels=dict(TIPOS_AULA),
            turmas=todas_turmas,
            anos_fechados=anos_fechados,
        )

    @app.route("/calendario/semana")
    def calendario_semana():
        todas_turmas = turmas_abertas_ativas()

        turma_id_param = request.args.get("turma_id", type=int)
        turma_selecionada = Turma.query.get(turma_id_param) if turma_id_param else None

        periodo_id = request.args.get("periodo_id", type=int)
        periodos_disponiveis = []
        periodo_atual = None
        if turma_selecionada:
            periodos_disponiveis = filtrar_periodos_para_turma(
                turma_selecionada,
                (
                    Periodo.query.filter_by(turma_id=turma_selecionada.id)
                    .order_by(Periodo.data_inicio)
                    .all()
                ),
            )
            if periodo_id:
                periodo_atual = next(
                    (p for p in periodos_disponiveis if p.id == periodo_id), None
                )
            if not periodo_atual and periodos_disponiveis:
                periodo_atual = periodos_disponiveis[0]

        data_txt = request.args.get("data")
        hoje = date.today()
        try:
            data_base = date.fromisoformat(data_txt) if data_txt else hoje
        except ValueError:
            data_base = hoje

        semana_inicio = data_base - timedelta(days=data_base.weekday())
        dias_semana = [semana_inicio + timedelta(days=i) for i in range(5)]
        semana_fim = dias_semana[-1]

        duplicados = (
            db.session.query(CalendarioAula.turma_id, CalendarioAula.data)
            .filter(
                CalendarioAula.apagado == False,  # noqa: E712
                CalendarioAula.data >= semana_inicio,
                CalendarioAula.data <= semana_fim,
            )
            .group_by(CalendarioAula.turma_id, CalendarioAula.data)
            .having(func.count(CalendarioAula.id) > 1)
            .all()
        )
        for turma_dup_id, _ in duplicados:
            renumerar_calendario_turma(turma_dup_id)

        query = (
            CalendarioAula.query.options(
                joinedload(CalendarioAula.turma).joinedload(Turma.ano_letivo),
                joinedload(CalendarioAula.modulo),
            )
            .filter_by(apagado=False)
            .filter(
                CalendarioAula.data >= semana_inicio,
                CalendarioAula.data <= semana_fim,
            )
            .join(Turma)
        )
        if turma_selecionada:
            query = query.filter(CalendarioAula.turma_id == turma_selecionada.id)
        if periodo_atual:
            query = query.filter(CalendarioAula.periodo_id == periodo_atual.id)

        aulas = (
            query.order_by(
                CalendarioAula.data.asc(),
                Turma.nome.asc(),
                CalendarioAula.numero_modulo.asc().nulls_last(),
                CalendarioAula.total_geral.asc().nulls_last(),
                CalendarioAula.id.asc(),
            )
            .all()
        )
        tempos_por_aula = {
            a.id: _tempo_da_turma_no_dia(a.turma, a.data) for a in aulas
        }
        faltas_por_aula = _mapear_alunos_em_falta(aulas)
        aulas_com_avaliacao = _mapear_aulas_com_avaliacao(aulas)
        sumarios_anteriores = _mapear_sumarios_anteriores(aulas)

        aulas_por_data = {}
        for aula in aulas:
            aulas_por_data.setdefault(aula.data, []).append(aula)
        for lista in aulas_por_data.values():
            lista.sort(key=_chave_ordenacao_aula)

        anos_fechados = {
            a.turma_id: bool(a.turma and a.turma.ano_letivo and a.turma.ano_letivo.fechado)
            for a in aulas
            if a.turma_id
        }

        return render_template(
            "turmas/calendario_semanal.html",
            turmas=todas_turmas,
            turma=turma_selecionada,
            periodo_atual=periodo_atual,
            periodos_disponiveis=periodos_disponiveis,
            data_base=data_base,
            semana_inicio=semana_inicio,
            semana_fim=semana_fim,
            dias_semana=dias_semana,
            semana_anterior=semana_inicio - timedelta(days=7),
            semana_seguinte=semana_inicio + timedelta(days=7),
            aulas_por_data=aulas_por_data,
            faltas_por_aula=faltas_por_aula,
            aulas_com_avaliacao=aulas_com_avaliacao,
            tempos_por_aula=tempos_por_aula,
            sumarios_anteriores=sumarios_anteriores,
            tipos_sem_aula=DEFAULT_TIPOS_SEM_AULA,
            tipos_aula=TIPOS_AULA,
            tipo_labels=dict(TIPOS_AULA),
            anos_fechados=anos_fechados,
        )

    @app.route("/calendario/semana/previsao")
    def calendario_semana_previsao():
        mostrar_todas = request.args.get("mostrar_todas") == "1"
        todas_turmas = turmas_abertas_ativas()
        if not mostrar_todas:
            todas_turmas = [t for t in todas_turmas if t.letiva]

        turma_id_param = request.args.get("turma_id", type=int)
        turma_selecionada = Turma.query.get(turma_id_param) if turma_id_param else None
        if turma_selecionada and not mostrar_todas and not turma_selecionada.letiva:
            turma_selecionada = None

        periodo_id = request.args.get("periodo_id", type=int)
        periodos_disponiveis = []
        periodo_atual = None
        if turma_selecionada:
            periodos_disponiveis = filtrar_periodos_para_turma(
                turma_selecionada,
                (
                    Periodo.query.filter_by(turma_id=turma_selecionada.id)
                    .order_by(Periodo.data_inicio)
                    .all()
                ),
            )
            if periodo_id:
                periodo_atual = next(
                    (p for p in periodos_disponiveis if p.id == periodo_id), None
                )
            if not periodo_atual and periodos_disponiveis:
                periodo_atual = periodos_disponiveis[0]

        data_txt = request.args.get("data")
        hoje = date.today()
        try:
            data_base = date.fromisoformat(data_txt) if data_txt else hoje
        except ValueError:
            data_base = hoje

        semana_inicio = data_base - timedelta(days=data_base.weekday())
        dias_semana = [semana_inicio + timedelta(days=i) for i in range(5)]
        semana_fim = dias_semana[-1]

        query = (
            CalendarioAula.query.options(
                joinedload(CalendarioAula.turma).joinedload(Turma.ano_letivo),
            )
            .filter_by(apagado=False)
            .filter(
                CalendarioAula.data >= semana_inicio,
                CalendarioAula.data <= semana_fim,
            )
            .join(Turma)
        )
        if turma_selecionada:
            query = query.filter(CalendarioAula.turma_id == turma_selecionada.id)
        elif not mostrar_todas:
            query = query.filter(Turma.letiva.is_(True))
        if periodo_atual:
            query = query.filter(CalendarioAula.periodo_id == periodo_atual.id)

        aulas = (
            query.order_by(
                CalendarioAula.data.asc(),
                Turma.nome.asc(),
                CalendarioAula.numero_modulo.asc().nulls_last(),
                CalendarioAula.total_geral.asc().nulls_last(),
                CalendarioAula.id.asc(),
            )
            .all()
        )

        aulas_por_data = {}
        for aula in aulas:
            aulas_por_data.setdefault(aula.data, []).append(aula)
        for lista in aulas_por_data.values():
            lista.sort(key=_chave_ordenacao_aula)

        anos_fechados = {
            a.turma_id: bool(
                a.turma and a.turma.ano_letivo and a.turma.ano_letivo.fechado
            )
            for a in aulas
            if a.turma_id
        }

        return render_template(
            "turmas/calendario_previsao_semanal.html",
            turmas=todas_turmas,
            turma=turma_selecionada,
            mostrar_todas=mostrar_todas,
            periodo_atual=periodo_atual,
            periodos_disponiveis=periodos_disponiveis,
            data_base=data_base,
            semana_inicio=semana_inicio,
            dias_semana=dias_semana,
            semana_anterior=semana_inicio - timedelta(days=7),
            semana_seguinte=semana_inicio + timedelta(days=7),
            aulas_por_data=aulas_por_data,
            anos_fechados=anos_fechados,
        )

    @app.route("/calendario/sumarios-pendentes")
    def calendario_sumarios_pendentes():
        hoje = date.today()
        turma_id = request.args.get("turma_id", type=int)
        turma_selecionada = Turma.query.get(turma_id) if turma_id else None

        aulas = listar_sumarios_pendentes(hoje, turma_id=turma_id)
        faltas_por_aula = _mapear_alunos_em_falta(aulas)
        aulas_com_avaliacao = _mapear_aulas_com_avaliacao(aulas)
        anos_fechados = {
            a.turma_id: bool(
                a.turma and a.turma.ano_letivo and a.turma.ano_letivo.fechado
            )
            for a in aulas
            if a.turma_id
        }
        sumarios_anteriores = _mapear_sumarios_anteriores(aulas)

        return render_template(
            "turmas/sumarios_pendentes.html",
            hoje=hoje,
            aulas=aulas,
            turmas=turmas_abertas_ativas(),
            turma_selecionada=turma_selecionada,
            faltas_por_aula=faltas_por_aula,
            aulas_com_avaliacao=aulas_com_avaliacao,
            sumarios_anteriores=sumarios_anteriores,
            tipos_sem_aula=DEFAULT_TIPOS_SEM_AULA,
            tipos_aula=TIPOS_AULA,
            tipo_labels=dict(TIPOS_AULA),
            anos_fechados=anos_fechados,
        )


    @app.route("/calendario/outras-datas")
    def calendario_outras_datas():
        tipo_filtro, turma_filtro, data_inicio, data_fim = _extrair_filtros_outras_datas(
            request.args
        )

        turmas = turmas_abertas_ativas()
        turmas_letivas = (
            Turma.query.join(AnoLetivo)
            .filter(AnoLetivo.ativo == True)  # noqa: E712
            .filter(AnoLetivo.fechado == False)  # noqa: E712
            .filter(Turma.letiva.is_(True))
            .order_by(Turma.nome)
            .all()
        )
        aulas = listar_aulas_especiais(turma_filtro, tipo_filtro, data_inicio, data_fim)

        return render_template(
            "turmas/outras_datas.html",
            aulas=aulas,
            tipos_aula=TIPOS_AULA,
            tipos_sem_aula=DEFAULT_TIPOS_SEM_AULA,
            tipo_labels=dict(TIPOS_AULA),
            tipos_especiais=TIPOS_ESPECIAIS,
            filtro_tipo=tipo_filtro,
            filtro_turma_id=turma_filtro,
            data_inicio=data_inicio,
            data_fim=data_fim,
            turmas=turmas,
            turmas_letivas=turmas_letivas,
        )

    @app.route("/calendario/outras-datas/add", methods=["POST"])
    def calendario_outras_datas_add():
        tipo_filtro, turma_filtro, data_inicio, data_fim = _extrair_filtros_outras_datas(
            request.form
        )
        turma_id = request.form.get("turma_id", type=int)
        data_txt = request.form.get("data")
        data_aula = _parse_date_form(data_txt)
        numero_aulas = request.form.get("numero_aulas", type=int) or 1
        sumario_txt = None
        previsao_txt = None
        observacoes_txt = None

        filtros_limpos = _filtros_outras_datas_redirect(
            tipo_filtro, turma_filtro or turma_id, data_inicio, data_fim
        )

        if not turma_id:
            flash("Seleciona a turma para adicionar a aula extra.", "error")
            return redirect(url_for("calendario_outras_datas", **filtros_limpos))

        turma = Turma.query.get(turma_id)
        if not turma or not turma.letiva:
            abort(
                400,
                description="Turma n\u00e3o letiva. Opera\u00e7\u00e3o n\u00e3o permitida.",
            )

        ano = turma.ano_letivo
        if ano and ano.fechado:
            flash("Ano letivo fechado: não é possível editar o calendário desta turma.", "error")
            return redirect(url_for("calendario_outras_datas", **filtros_limpos))

        if not data_aula:
            flash("Indica a data para a aula extra.", "error")
            return redirect(url_for("calendario_outras_datas", **filtros_limpos))

        try:
            criar_aula_extra(
                turma,
                data_aula,
                numero_aulas=numero_aulas,
                sumario=sumario_txt,
                previsao=previsao_txt,
                observacoes=observacoes_txt,
            )
            renumerar_calendario_turma(turma.id)
            flash("Aula extra adicionada e numeração recalculada.", "success")
        except ValueError as exc:
            flash(str(exc), "error")

        return redirect(url_for("calendario_outras_datas", **filtros_limpos))

    @app.route("/outras-datas/<int:aula_id>/observacoes", methods=["POST"])
    def outras_datas_observacoes_save(aula_id):
        payload = request.get_json(silent=True) or {}
        if "observacoes_html" not in payload:
            return jsonify({"ok": False, "error": "Campo observacoes_html em falta."}), 400

        aula = (
            CalendarioAula.query.options(joinedload(CalendarioAula.turma))
            .filter_by(id=aula_id, apagado=False)
            .first_or_404()
        )
        ano = aula.turma.ano_letivo if aula.turma else None
        if ano and ano.fechado:
            return jsonify(
                {
                    "ok": False,
                    "error": "Ano letivo fechado: não é possível editar observações.",
                }
            ), 400

        observacoes_html = _sanitize_observacoes_html(payload.get("observacoes_html"))
        observacoes_txt = _strip_html_to_text(observacoes_html or "").strip() or None

        aula.observacoes_html = observacoes_html
        aula.observacoes = observacoes_txt
        db.session.commit()

        saved_at = (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        return jsonify(
            {
                "ok": True,
                "saved_at": saved_at,
                "observacoes_html": aula.observacoes_html or "",
            }
        )

    @app.route("/calendario/outras-datas/mudar-tipo", methods=["POST"])
    def calendario_outras_datas_mudar_tipo():
        data_txt = request.form.get("data")
        novo_tipo = request.form.get("novo_tipo")

        tipo_filtro, turma_filtro, data_inicio, data_fim = _extrair_filtros_outras_datas(
            request.form
        )
        filtros_limpos = _filtros_outras_datas_redirect(
            tipo_filtro, turma_filtro, data_inicio, data_fim
        )
        tempos_sem_aula = request.form.get("tempos_sem_aula", type=int)

        data_alvo = _parse_date_form(data_txt)
        tipos_validos = {valor for valor, _ in TIPOS_AULA if valor != "extra"}

        if not data_alvo:
            flash("Indica a data para alterar o tipo das aulas.", "error")
            return redirect(url_for("calendario_outras_datas", **filtros_limpos))

        if novo_tipo not in tipos_validos:
            flash("Seleciona um tipo de aula válido (exceto Extra).", "error")
            return redirect(url_for("calendario_outras_datas", **filtros_limpos))

        aulas = (
            CalendarioAula.query.options(joinedload(CalendarioAula.turma))
            .filter(CalendarioAula.apagado == False)  # noqa: E712
            .filter(CalendarioAula.data == data_alvo)
            .filter(CalendarioAula.tipo != "extra")
            .join(Turma)
            .all()
        )

        if not aulas:
            flash("Não há aulas para essa data que possam ser atualizadas.", "info")
            return redirect(url_for("calendario_outras_datas", **filtros_limpos))

        turmas_bloqueadas = []
        turmas_para_renumerar = set()
        alteracoes = 0

        for aula in aulas:
            ano = aula.turma.ano_letivo if aula.turma else None
            if ano and ano.fechado:
                turmas_bloqueadas.append(aula.turma.nome)
                continue

            if aula.tipo == novo_tipo:
                continue

            aula.tipo = novo_tipo
            total_previsto = _total_previsto_ui(
                aula.sumarios,
                tempos_sem_aula if tempos_sem_aula is not None else aula.tempos_sem_aula,
            )
            if novo_tipo in DEFAULT_TIPOS_SEM_AULA:
                valor_tempos = tempos_sem_aula
                if valor_tempos is None:
                    valor_tempos = aula.tempos_sem_aula
                if valor_tempos is None:
                    valor_tempos = total_previsto
                aula.tempos_sem_aula = max(0, min(valor_tempos, total_previsto))
            else:
                aula.tempos_sem_aula = 0

            turmas_para_renumerar.add(aula.turma_id)
            alteracoes += 1

        if alteracoes == 0:
            msg = "Não foram feitas alterações porque as aulas já tinham esse tipo."
            if turmas_bloqueadas:
                msg += f" Turmas bloqueadas: {', '.join(sorted(set(turmas_bloqueadas)))}."
            flash(msg, "info")
            return redirect(url_for("calendario_outras_datas", **filtros_limpos))

        db.session.commit()

        for turma_id in turmas_para_renumerar:
            renumerar_calendario_turma(turma_id)

        msg_sucesso = "Tipos de aula atualizados e numeração recalculada."
        if turmas_bloqueadas:
            msg_sucesso += f" Turmas bloqueadas: {', '.join(sorted(set(turmas_bloqueadas)))}."
        flash(msg_sucesso, "success")

        return redirect(url_for("calendario_outras_datas", **filtros_limpos))

    @app.route("/turmas/<int:turma_id>/calendario/gerar", methods=["POST"])
    def turma_calendario_gerar(turma_id):
        turma = Turma.query.get_or_404(turma_id)
        ano = turma.ano_letivo
        if ano and ano.fechado:
            flash("Ano letivo fechado: não é possível gerar calendário.", "error")
            return redirect(url_for("turma_calendario", turma_id=turma.id))

        
        ja_tem_calendario = (
            db.session.query(CalendarioAula.id)
            .filter_by(turma_id=turma.id, apagado=False)
            .first()
            is not None
        )
        if ja_tem_calendario:
            flash(
                "A turma já tem um calendário gerado. Use 'Limpar calendário' antes de gerar novamente.",
                "warning",
            )
            return redirect(url_for("turma_calendario", turma_id=turma.id))

        periodos = (
            Periodo.query.filter_by(turma_id=turma.id)
            .order_by(Periodo.data_inicio)
            .all()
        )
        modulos = garantir_modulos_para_turma(turma)

        if not periodos:
            flash("Defina períodos letivos para a turma antes de gerar o calendário.", "error")
            return redirect(url_for("turma_calendario", turma_id=turma.id))

        if not modulos:
            flash(
                "Crie módulos com a respetiva carga horária antes de gerar o calendário.",
                "error",
            )
            return redirect(url_for("turma_calendario", turma_id=turma.id))

        linhas_criadas = gerar_calendario_turma(turma.id, recalcular_tudo=True)

        if linhas_criadas:
            flash("Calendário anual gerado para a turma.", "success")
        else:
            flash(
                "Não foi possível gerar aulas: defina a carga horária diária ou os horários da turma.",
                "warning",
            )
        return redirect(url_for("turma_calendario", turma_id=turma.id))

    @app.route("/turmas/<int:turma_id>/calendario/reset", methods=["POST"])
    def turma_calendario_reset(turma_id):
        turma = Turma.query.get_or_404(turma_id)
        ano = turma.ano_letivo
        if ano and ano.fechado:
            flash("Ano letivo fechado: não é possível editar o calendário.", "error")
            return redirect(url_for("turma_calendario", turma_id=turma.id))

        total_apagadas = (
            CalendarioAula.query.filter_by(turma_id=turma.id).delete()
            or 0
        )
        db.session.commit()

        if total_apagadas:
            flash(
                f"Calendário limpo: {total_apagadas} linhas removidas.",
                "success",
            )
        else:
            flash("Calendário já estava vazio para esta turma.", "info")

        return redirect(url_for("turma_calendario", turma_id=turma.id))



    @app.route("/turmas/<int:turma_id>/delete", methods=["POST"])
    def turmas_delete(turma_id):
        turma = Turma.query.get_or_404(turma_id)

        # Apaga dependências explícitas antes da turma para evitar violar FKs
        CalendarioAula.query.filter_by(turma_id=turma.id).delete()
        Extra.query.filter_by(turma_id=turma.id).delete()
        Exclusao.query.filter_by(turma_id=turma.id).delete()
        Horario.query.filter_by(turma_id=turma.id).delete()
        Periodo.query.filter_by(turma_id=turma.id).delete()
        Modulo.query.filter_by(turma_id=turma.id).delete()
        TurmaDisciplina.query.filter_by(turma_id=turma.id).delete()
        LivroTurma.query.filter_by(turma_id=turma.id).delete()

        db.session.delete(turma)
        db.session.commit()
        flash("Turma eliminada.", "success")
        return redirect(url_for("turmas_list"))
    @app.route("/turmas/<int:turma_id>/calendario/<int:aula_id>/edit", methods=["GET", "POST"])
    def calendario_edit(turma_id, aula_id):
        turma = Turma.query.get_or_404(turma_id)
        ano = turma.ano_letivo
        if ano and ano.fechado:
            flash("Ano letivo fechado: não é possível editar o calendário.", "error")
            return redirect(url_for("turma_calendario", turma_id=turma.id))

        aula = (
            CalendarioAula.query.filter_by(id=aula_id, apagado=False)
            .first_or_404()
        )
        if aula.turma_id != turma.id:
            flash("Linha de calendário não pertence a esta turma.", "error")
            return redirect(url_for("turma_calendario", turma_id=turma.id))

        aulas_mesma_disciplina_query = CalendarioAula.query.filter_by(
            turma_id=turma.id,
            apagado=False,
        )
        if aula.modulo_id:
            aulas_mesma_disciplina_query = aulas_mesma_disciplina_query.filter_by(
                modulo_id=aula.modulo_id
            )
        else:
            aulas_mesma_disciplina_query = aulas_mesma_disciplina_query.filter(
                CalendarioAula.modulo_id.is_(None)
            )
        aulas_mesma_disciplina = (
            aulas_mesma_disciplina_query
            .order_by(CalendarioAula.data.asc(), CalendarioAula.id.asc())
            .all()
        )
        sumario_anterior = _mapear_sumarios_anteriores(aulas_mesma_disciplina).get(
            aula.id
        )

        periodo = Periodo.query.get_or_404(aula.periodo_id)
        redirect_view = request.values.get("view")
        data_ref = request.values.get("data_ref")
        turma_filtro = request.values.get("turma_filtro", type=int)

        modulos = garantir_modulos_para_turma(turma)
        if not modulos:
            flash("Cria módulos com carga horária antes de editar linhas.", "error")
            return redirect(url_for("turma_calendario", turma_id=turma.id))

        if request.method == "POST":
            data = _parse_date_form(request.form.get("data"))
            modulo_id = request.form.get("modulo_id", type=int)
            numero_modulo = request.form.get("numero_modulo", type=int)
            total_geral = request.form.get("total_geral", type=int)
            sumarios_txt = (request.form.get("sumarios") or "").strip()
            sumario_txt = (request.form.get("sumario") or "").strip()
            previsao_txt = _normalizar_texto_opcional(request.form.get("previsao")) or ""
            tipo = request.form.get("tipo") or "normal"
            tempos_sem_aula = request.form.get("tempos_sem_aula", type=int)

            sumarios_originais = [s.strip() for s in sumarios_txt.split(",") if s.strip()]
            total_previsto = _total_previsto_ui(sumarios_txt, tempos_sem_aula if tempos_sem_aula is not None else aula.tempos_sem_aula)
            if tempos_sem_aula is None:
                if tipo in DEFAULT_TIPOS_SEM_AULA:
                    tempos_sem_aula = (
                        aula.tempos_sem_aula
                        if aula.tempos_sem_aula is not None
                        else total_previsto
                    )
                else:
                    tempos_sem_aula = 0
            tempos_sem_aula = max(0, min(tempos_sem_aula, total_previsto))

            if not data or not modulo_id:
                flash("Data e Módulo são obrigatórios.", "error")
                return render_template(
                    "turmas/calendario_form.html",
                    titulo="Editar linha de calendário",
                    turma=turma,
                    periodo=periodo,
                    modulos=modulos,
                    aula=aula,
                    redirect_view=redirect_view,
                    data_ref=data_ref,
                    tipos_aula=TIPOS_AULA,
                    tipos_sem_aula=DEFAULT_TIPOS_SEM_AULA,
                    sumario_anterior=sumario_anterior,
                )

            aula.data = data
            aula.modulo_id = modulo_id
            aula.numero_modulo = numero_modulo
            aula.total_geral = total_geral
            aula.sumarios = sumarios_txt
            aula.sumario = sumario_txt
            aula.previsao = previsao_txt
            aula.tipo = tipo
            aula.tempos_sem_aula = tempos_sem_aula if tipo in DEFAULT_TIPOS_SEM_AULA else 0

            db.session.commit()
            renumerar_calendario_turma(turma.id)
            novas = completar_modulos_profissionais(
                turma.id,
                data_removida=data,
                modulo_removido_id=modulo_id,
            )
            if novas:
                renumerar_calendario_turma(turma.id)
                flash(
                    "Linha de calendário atualizada e "
                    f"{novas} aula(s) adicionadas para cumprir o total do módulo.",
                    "success",
                )
            else:
                flash("Linha de calendário atualizada.", "success")
            if redirect_view == "dia" and data_ref:
                destino = {"data": data_ref}
                if periodo and periodo.id:
                    destino["periodo_id"] = periodo.id
                if turma_filtro:
                    return redirect(
                        url_for("turma_calendario_dia", turma_id=turma_filtro, **destino)
                    )
                return redirect(url_for("turma_calendario_dia", **destino))
            if redirect_view == "semana":
                filtros = {}
                if data_ref:
                    filtros["data"] = data_ref
                turma_filtro = request.form.get("turma_id", type=int)
                if turma_filtro:
                    filtros["turma_id"] = turma_filtro
                return redirect(url_for("calendario_semana", **filtros))
            return redirect(
                url_for(
                    "turma_calendario",
                    turma_id=turma.id,
                    periodo_id=periodo.id,
                )
            )

        return render_template(
            "turmas/calendario_form.html",
            titulo="Editar linha de calendário",
            turma=turma,
            periodo=periodo,
            modulos=modulos,
            aula=aula,
            redirect_view=redirect_view,
            data_ref=data_ref,
            tipos_aula=TIPOS_AULA,
            tipos_sem_aula=DEFAULT_TIPOS_SEM_AULA,
            sumario_anterior=sumario_anterior,
        )

    @app.route("/turmas/<int:turma_id>/calendario/<int:aula_id>/delete", methods=["POST"])
    def calendario_delete(turma_id, aula_id):
        turma = Turma.query.get_or_404(turma_id)
        ano = turma.ano_letivo
        if ano and ano.fechado:
            flash("Ano letivo fechado: não é possível editar o calendário.", "error")
            return redirect(url_for("turma_calendario", turma_id=turma.id))

        aula = (
            CalendarioAula.query.filter_by(id=aula_id, apagado=False)
            .first_or_404()
        )
        if aula.turma_id != turma.id:
            flash("Linha de calendário não pertence a esta turma.", "error")
            return redirect(url_for("turma_calendario", turma_id=turma.id))

        data_removida = aula.data
        aula.apagado = True
        db.session.commit()
        renumerar_calendario_turma(turma.id)

        novas = completar_modulos_profissionais(
            turma.id, data_removida=data_removida, modulo_removido_id=aula.modulo_id
        )
        if novas:
            renumerar_calendario_turma(turma.id)
            flash(
                f"Linha de calendário apagada e {novas} aula(s) adicionadas para cumprir o total do módulo.",
                "success",
            )
        else:
            flash("Linha de calendário apagada.", "success")
        view = request.form.get("view")
        data_ref = request.form.get("data_ref")
        if view == "dia" and data_ref:
            return redirect(url_for("turma_calendario_dia", turma_id=turma.id, data=data_ref))
        if view == "semana":
            filtros = {}
            if data_ref:
                filtros["data"] = data_ref
            turma_filtro = request.form.get("turma_id", type=int)
            if turma_filtro:
                filtros["turma_id"] = turma_filtro
            return redirect(url_for("calendario_semana", **filtros))

        return redirect(url_for("turma_calendario", turma_id=turma.id))

    # ----------------------------------------
    # CALENDÁRIO – SUMÁRIOS EM LINHA
    # ----------------------------------------
    @app.route(
        "/turmas/<int:turma_id>/calendario/<int:aula_id>/alunos",
        methods=["GET", "POST"],
    )
    def calendario_aula_alunos(turma_id, aula_id):
        turma = Turma.query.options(joinedload(Turma.ano_letivo)).get_or_404(turma_id)
        aula = (
            CalendarioAula.query.options(joinedload(CalendarioAula.modulo))
            .filter_by(id=aula_id, apagado=False)
            .first_or_404()
        )

        if aula.turma_id != turma.id:
            flash("Linha de calendário não pertence a esta turma.", "error")
            return redirect(url_for("turma_calendario", turma_id=turma.id))

        ano = turma.ano_letivo
        ano_fechado = bool(ano and ano.fechado)

        return_url = request.args.get("return_url") or request.form.get("return_url")
        if return_url and not return_url.startswith("/"):
            return_url = None

        alunos = (
            Aluno.query.filter_by(turma_id=turma.id)
            .order_by(Aluno.numero.is_(None), Aluno.numero, Aluno.nome)
            .all()
        )
        avaliacoes = {
            avaliacao.aluno_id: avaliacao
            for avaliacao in AulaAluno.query.filter_by(aula_id=aula.id).all()
        }

        if request.method == "POST":
            if ano_fechado:
                flash("Ano letivo fechado: apenas leitura.", "error")
                destino = return_url or url_for("turma_calendario", turma_id=turma.id)
                return redirect(destino)

            aula.atividade = bool(request.form.get("atividade_flag"))
            aula.atividade_nome = (
                request.form.get("atividade_nome") if aula.atividade else None
            )

            payloads = _build_payloads_from_form(aula, alunos)
            sessions = get_db_sessions("remote")
            if sessions["mode"] != "remote":
                app.logger.warning("Write de calendário em modo não-remoto: %s", sessions["mode"])
            try:
                _apply_payloads(payloads)
                db.session.commit()
                flash("Avaliações de alunos guardadas.", "success")
            except Exception as exc:
                db.session.rollback()
                app.logger.exception("Falha ao gravar avaliações na BD principal: %s", exc)
                if g.is_offline:
                    _enqueue_payloads(payloads)
                    flash("Registo guardado localmente; sincronizará quando houver rede.", "warning")
                else:
                    flash("Falha ao guardar na BD remota. Tente novamente.", "error")

            destino = return_url or url_for("turma_calendario", turma_id=turma.id)
            return redirect(destino)

        return render_template(
            "turmas/calendario_aula_alunos.html",
            turma=turma,
            aula=aula,
            alunos=alunos,
            avaliacoes=avaliacoes,
            ano_fechado=ano_fechado,
            return_url=return_url,
            pending_offline=pending_count(app.instance_path),
        )

    @app.route("/aulas/<int:aula_id>/aulas_alunos/save", methods=["POST"])
    def aulas_alunos_save(aula_id):
        aula = CalendarioAula.query.filter_by(id=aula_id, apagado=False).first_or_404()
        turma = Turma.query.options(joinedload(Turma.ano_letivo)).get_or_404(aula.turma_id)
        ano = turma.ano_letivo
        if ano and ano.fechado:
            return jsonify({"ok": False, "error": "Ano letivo fechado."}), 400

        items = request.get_json(silent=True) or {}
        payloads = items.get("items") or []
        if not isinstance(payloads, list):
            return jsonify({"ok": False, "error": "Payload inválido."}), 400

        normalized_payloads = []
        for item in payloads:
            aluno_id = int(item.get("aluno_id"))
            payload = normalize_aulas_alunos_payload(item.get("payload") or {})
            payload["client_ts"] = item.get("client_ts") or datetime.utcnow().isoformat(timespec="seconds")
            normalized_payloads.append({"aula_id": aula.id, "aluno_id": aluno_id, "payload": payload})

        sessions = get_db_sessions("remote")
        if sessions["mode"] != "remote":
            app.logger.warning("/aulas_alunos/save em modo não-remoto: %s", sessions["mode"])

        try:
            _apply_payloads(normalized_payloads)
            db.session.commit()
            return jsonify({"ok": True, "offline": False, "pending": pending_count(app.instance_path)})
        except Exception as exc:
            db.session.rollback()
            app.logger.exception("Falha no save de aulas_alunos: %s", exc)
            if g.is_offline:
                _enqueue_payloads(normalized_payloads)
                return jsonify({"ok": True, "offline": True, "pending": pending_count(app.instance_path)})
            return jsonify({"ok": False, "error": "Falha ao guardar na BD remota."}), 503

    @app.route("/aulas/<int:aula_id>/aulas_alunos/import_tsv", methods=["POST"])
    def aulas_alunos_import_tsv(aula_id):
        aula = CalendarioAula.query.filter_by(id=aula_id, apagado=False).first_or_404()
        turma = Turma.query.options(joinedload(Turma.ano_letivo)).get_or_404(aula.turma_id)
        ano = turma.ano_letivo
        if ano and ano.fechado:
            return jsonify({"ok": False, "error": "Ano letivo fechado."}), 400

        content_type = (request.content_type or "").lower()
        if "application/json" in content_type:
            payload = request.get_json(silent=True) or {}
            raw_tsv = payload.get("tsv") or ""
        else:
            raw_tsv = request.get_data(as_text=True) or ""

        try:
            rows = parse_aulas_alunos_tsv(raw_tsv, aula_id_default=aula.id)
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        sessions = get_db_sessions("remote")
        if sessions["mode"] != "remote":
            app.logger.warning("/import_tsv em modo não-remoto: %s", sessions["mode"])

        try:
            _apply_payloads(rows)
            db.session.commit()
            return jsonify({"ok": True, "offline": False, "imported": len(rows), "pending": pending_count(app.instance_path)})
        except Exception as exc:
            db.session.rollback()
            app.logger.exception("Falha ao importar TSV para BD principal: %s", exc)
            if g.is_offline:
                _enqueue_payloads(rows)
                return jsonify({"ok": True, "offline": True, "imported": len(rows), "pending": pending_count(app.instance_path)})
            return jsonify({"ok": False, "error": "Falha ao importar para BD remota."}), 503

    @app.route("/api/sync/apply", methods=["POST"])
    def api_sync_apply():
        data = request.get_json(silent=True) or {}
        items = data.get("items")
        if not isinstance(items, list):
            return jsonify({"ok": False, "error": "items inválido"}), 400

        applied = 0
        try:
            with db.session.begin():
                for item in items:
                    if item.get("entity") != "aulas_alunos" or item.get("action") != "upsert":
                        continue
                    aula_id = int(item.get("aula_id"))
                    aluno_id = int(item.get("aluno_id"))
                    payload = item.get("payload") or {}
                    apply_upsert_aulas_alunos(db.session, aula_id, aluno_id, payload)
                    applied += 1
        except Exception as exc:
            db.session.rollback()
            app.logger.exception("/api/sync/apply falhou: %s", exc)
            return jsonify({"ok": False, "error": "Falha ao aplicar sincronização."}), 500

        return jsonify({"ok": True, "applied": applied})

    @app.route("/api/sync/status", methods=["GET"])
    def api_sync_status():
        return jsonify(
            {
                "ok": True,
                "pending": pending_count(app.instance_path),
                "last_error": get_last_error(app.instance_path),
            }
        )

    @app.route("/sync/flush", methods=["POST"])
    def sync_flush():
        result = try_flush_outbox(limit=200)
        return jsonify(
            {
                "ok": bool(result.get("ok", True)),
                "applied": result.get("applied", 0),
                "errors": result.get("errors", 0),
                "pending": result.get("remaining", pending_count(app.instance_path)),
                "last_error": get_last_error(app.instance_path),
            }
        )

    @app.route(
        "/turmas/<int:turma_id>/calendario/<int:aula_id>/sumario",
        methods=["POST"],
    )
    def calendario_update_sumario(turma_id, aula_id):
        aceita_json = (
            request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or request.accept_mimetypes.best == "application/json"
        )

        def _json_error(message, status=500):
            if aceita_json:
                return jsonify({"ok": False, "error": message}), status
            flash(message, "error")
            return redirect(url_for("turma_calendario", turma_id=turma_id))

        try:
            turma = Turma.query.get_or_404(turma_id)
            ano = turma.ano_letivo
            if ano and ano.fechado:
                return _json_error("Ano letivo fechado: não é possível editar o calendário.", 400)

            aula = (
                CalendarioAula.query.filter_by(id=aula_id, apagado=False)
                .first_or_404()
            )
            if aula.turma_id != turma.id:
                return _json_error("Linha de calendário não pertence a esta turma.", 400)

            historico_pendente = None
            sumario_txt = request.form.get("sumario")
            if sumario_txt is not None:
                sumario_atual = aula.sumario or ""
                sumario_novo = sumario_txt.strip()
                if sumario_novo != sumario_atual:
                    historico_pendente = {
                        "acao": "edicao_manual",
                        "anterior": sumario_atual,
                        "novo": sumario_novo,
                    }
                aula.sumario = sumario_novo

            previsao_txt = request.form.get("previsao")
            if previsao_txt is not None:
                aula.previsao = _normalizar_texto_opcional(previsao_txt) or ""

            observacoes_txt = request.form.get("observacoes")
            if observacoes_txt is not None:
                aula.observacoes = observacoes_txt.strip()

            tipo_original = aula.tipo
            tempos_originais = aula.tempos_sem_aula or 0
            novo_tipo_raw = request.form.get("tipo")
            novo_tipo = (novo_tipo_raw if novo_tipo_raw is not None else aula.tipo) or "normal"
            if isinstance(novo_tipo, str):
                novo_tipo = novo_tipo.strip()
            aula.tipo = novo_tipo

            tempos_sem_aula = request.form.get("tempos_sem_aula", type=int)
            total_previsto = _total_previsto_ui(
                aula.sumarios,
                tempos_sem_aula if tempos_sem_aula is not None else aula.tempos_sem_aula,
            )
            if tempos_sem_aula is None:
                if novo_tipo in DEFAULT_TIPOS_SEM_AULA:
                    tempos_sem_aula = (
                        aula.tempos_sem_aula
                        if aula.tempos_sem_aula is not None
                        else total_previsto
                    )
                else:
                    tempos_sem_aula = 0
            tempos_sem_aula = max(0, min(tempos_sem_aula, total_previsto))
            aula.tempos_sem_aula = (
                tempos_sem_aula if novo_tipo in DEFAULT_TIPOS_SEM_AULA else 0
            )

            mudou_tempos = aula.tempos_sem_aula != tempos_originais

            db.session.commit()
            app.logger.info(
                "SAVE OK | turma_id=%s | aula_id=%s | endpoint=calendario_update_sumario",
                turma_id,
                aula_id,
            )
            if historico_pendente:
                _registar_sumario_historico_isolado(
                    aula_id=aula.id,
                    acao=historico_pendente["acao"],
                    anterior=historico_pendente["anterior"],
                    novo=historico_pendente["novo"],
                )

            mensagem = "Sumário atualizado."

            if novo_tipo != tipo_original or mudou_tempos:
                try:
                    renumerar_calendario_turma(turma.id)
                    novas = completar_modulos_profissionais(
                        turma.id,
                        data_removida=aula.data,
                        modulo_removido_id=aula.modulo_id,
                    )
                    if novas:
                        renumerar_calendario_turma(turma.id)
                        mensagem = (
                            "Tipo de aula atualizado e "
                            f"{novas} aula(s) adicionadas para cumprir o total do módulo."
                        )
                    else:
                        mensagem = "Sumário e contagens atualizados."
                except Exception as pos_exc:
                    app.logger.exception(
                        "Falha pós-gravação ao renumerar/completar módulo (turma_id=%s aula_id=%s): %s",
                        turma_id,
                        aula_id,
                        pos_exc,
                    )

            if aceita_json:
                return jsonify(
                    {
                        "status": "ok",
                        "ok": True,
                        "sumario": aula.sumario or "",
                        "previsao": aula.previsao or "",
                        "tipo": aula.tipo,
                        "tempos_sem_aula": aula.tempos_sem_aula or 0,
                        "last_save": _formatar_data_hora(_load_last_save()),
                    }
                )

            flash(mensagem, "success")

            periodo_id = request.form.get("periodo_id", type=int)
            redirect_view = request.form.get("view")
            data_ref = request.form.get("data_ref")
            turma_filtro = request.form.get("turma_filtro", type=int)

            if redirect_view == "pendentes":
                filtros = {}
                turma_filtro = request.form.get("turma_filtro", type=int)
                if turma_filtro:
                    filtros["turma_id"] = turma_filtro
                return redirect(url_for("calendario_sumarios_pendentes", **filtros))

            if redirect_view == "outras_datas":
                filtros = {
                    "tipo": request.form.get("tipo_filtro") or None,
                    "turma_id": request.form.get("turma_filtro", type=int),
                    "data_inicio": request.form.get("data_inicio") or None,
                    "data_fim": request.form.get("data_fim") or None,
                }
                filtros_limpos = {k: v for k, v in filtros.items() if v}
                return redirect(url_for("calendario_outras_datas", **filtros_limpos))

            if redirect_view == "dia" and data_ref:
                destino = {"data": data_ref}
                if periodo_id:
                    destino["periodo_id"] = periodo_id
                if turma_filtro:
                    return redirect(
                        url_for(
                            "turma_calendario_dia",
                            turma_id=turma_filtro,
                            **destino,
                        )
                    )
                return redirect(url_for("turma_calendario_dia", **destino))
            if redirect_view == "semana":
                filtros = {}
                if data_ref:
                    filtros["data"] = data_ref
                turma_filtro = request.form.get("turma_id", type=int)
                if turma_filtro:
                    filtros["turma_id"] = turma_filtro
                if periodo_id:
                    filtros["periodo_id"] = periodo_id
                return redirect(url_for("calendario_semana", **filtros))
            if redirect_view == "semana_previsao":
                filtros = {}
                if data_ref:
                    filtros["data"] = data_ref
                turma_filtro = request.form.get("turma_id", type=int)
                if turma_filtro:
                    filtros["turma_id"] = turma_filtro
                if periodo_id:
                    filtros["periodo_id"] = periodo_id
                return redirect(url_for("calendario_semana_previsao", **filtros))

            return redirect(
                url_for("turma_calendario", turma_id=turma.id, periodo_id=periodo_id)
            )
        except Exception as exc:
            db.session.rollback()
            app.logger.exception(
                "Erro ao guardar sumário (turma_id=%s aula_id=%s): %s",
                turma_id,
                aula_id,
                exc,
            )
            return _json_error("Falha ao guardar sumário.", 500)

    # ----------------------------------------
    # ANOS LETIVOS – CRUD
    # ----------------------------------------
    @app.route("/anos-letivos")
    def anos_letivos_list():
        anos = AnoLetivo.query.order_by(AnoLetivo.data_inicio_ano.desc()).all()
        return render_template("anos_letivos/list.html", anos=anos)

    @app.route("/anos-letivos/add", methods=["GET", "POST"])
    def anos_letivos_add():
        if request.method == "POST":
            nome = request.form.get("nome") or ""
            data_inicio_ano = _parse_date_form(request.form.get("data_inicio_ano"))
            data_fim_ano = _parse_date_form(request.form.get("data_fim_ano"))
            data_fim_semestre1 = _parse_date_form(request.form.get("data_fim_semestre1"))
            data_inicio_semestre2 = _parse_date_form(request.form.get("data_inicio_semestre2"))
            descricao = request.form.get("descricao") or None

            if not nome:
                flash("O nome do ano letivo é obrigatório.", "error")
                return redirect(url_for("anos_letivos_add"))

            al = AnoLetivo(
                nome=nome,
                data_inicio_ano=data_inicio_ano,
                data_fim_ano=data_fim_ano,
                data_fim_semestre1=data_fim_semestre1,
                data_inicio_semestre2=data_inicio_semestre2,
                descricao=descricao,
                ativo=False,
                fechado=False,
            )
            db.session.add(al)
            db.session.commit()
            flash("Ano letivo criado.", "success")
            return redirect(url_for("anos_letivos_list"))

        return render_template("anos_letivos/form.html", ano=None)

    @app.route("/anos-letivos/<int:ano_id>/edit", methods=["GET", "POST"])
    def anos_letivos_edit(ano_id):
        ano = AnoLetivo.query.get_or_404(ano_id)

        if request.method == "POST":
            nome = request.form.get("nome") or ""
            data_inicio_ano = _parse_date_form(request.form.get("data_inicio_ano"))
            data_fim_ano = _parse_date_form(request.form.get("data_fim_ano"))
            data_fim_semestre1 = _parse_date_form(request.form.get("data_fim_semestre1"))
            data_inicio_semestre2 = _parse_date_form(request.form.get("data_inicio_semestre2"))
            descricao = request.form.get("descricao") or None

            if not nome:
                flash("O nome do ano letivo é obrigatório.", "error")
                return redirect(url_for("anos_letivos_edit", ano_id=ano.id))

            ano.nome = nome
            ano.data_inicio_ano = data_inicio_ano
            ano.data_fim_ano = data_fim_ano
            ano.data_fim_semestre1 = data_fim_semestre1
            ano.data_inicio_semestre2 = data_inicio_semestre2
            ano.descricao = descricao

            db.session.commit()
            flash("Ano letivo atualizado.", "success")
            return redirect(url_for("anos_letivos_list"))

        return render_template("anos_letivos/form.html", ano=ano)

    @app.route("/anos-letivos/<int:ano_id>/delete", methods=["POST"])
    def anos_letivos_delete(ano_id):
        ano = AnoLetivo.query.get_or_404(ano_id)
        db.session.delete(ano)
        db.session.commit()
        flash("Ano letivo apagado.", "success")
        return redirect(url_for("anos_letivos_list"))

    @app.route("/anos-letivos/<int:ano_id>/set-ativo", methods=["POST"])
    def anos_letivos_set_ativo(ano_id):
        ano = AnoLetivo.query.get_or_404(ano_id)

        AnoLetivo.query.update({AnoLetivo.ativo: False})
        ano.ativo = True
        db.session.commit()

        flash(f"Ano letivo {ano.nome} marcado como ativo.", "success")
        return redirect(url_for("anos_letivos_list"))

    @app.route("/anos-letivos/<int:ano_id>/fechar", methods=["POST"])
    def anos_letivos_fechar(ano_id):
        ano = AnoLetivo.query.get_or_404(ano_id)
        ano.fechado = True
        db.session.commit()
        flash(f"Ano letivo {ano.nome} foi fechado (apenas consulta).", "success")
        return redirect(url_for("anos_letivos_list"))

    @app.route("/anos-letivos/<int:ano_id>/abrir", methods=["POST"])
    def anos_letivos_abrir(ano_id):
        ano = AnoLetivo.query.get_or_404(ano_id)
        ano.fechado = False
        db.session.commit()
        flash(f"Ano letivo {ano.nome} reaberto para edição.", "success")
        return redirect(url_for("anos_letivos_list"))

    # ----------------------------------------
    # CALENDÁRIO ESCOLAR – VISUALIZAÇÃO
    # ----------------------------------------
    @app.route("/calendario-escolar/importar", methods=["GET", "POST"])
    def calendario_escolar_importar():
        anos = (
            AnoLetivo.query
            .order_by(AnoLetivo.data_inicio_ano.desc().nullslast(), AnoLetivo.nome)
            .all()
        )
        ano_atual = get_ano_letivo_atual()

        if request.method == "POST":
            ano_destino_id = request.form.get("ano_id", type=int)
            ficheiro = request.files.get("ficheiro")
            conteudo = request.form.get("conteudo") or ""

            bruto: str | None = None
            if ficheiro and ficheiro.filename:
                bruto = ficheiro.read().decode("utf-8", errors="ignore")
            elif conteudo.strip():
                bruto = conteudo

            if not bruto:
                flash("Seleciona um ficheiro ou cola o JSON do calendário escolar.", "error")
                return redirect(url_for("calendario_escolar_importar"))

            try:
                payload = json.loads(bruto)
            except ValueError:
                flash("Ficheiro JSON inválido.", "error")
                return redirect(url_for("calendario_escolar_importar"))

            try:
                ano_resultado, contadores = importar_calendario_escolar_json(
                    payload, ano_destino_id=ano_destino_id
                )
            except ValueError as exc:
                flash(str(exc), "error")
                return redirect(url_for("calendario_escolar_importar"))

            flash(
                "Calendário escolar importado com sucesso: "
                f"{contadores['interrupcoes']} interrupções e "
                f"{contadores['feriados']} feriados.",
                "success",
            )
            return redirect(url_for("calendario_escolar_gestao", ano_id=ano_resultado.id))

        return render_template(
            "calendario/importar_escolar.html",
            anos=anos,
            ano_atual=ano_atual,
        )

    @app.route("/calendario-escolar")
    def calendario_escolar():
        ano = get_ano_letivo_atual()
        if not ano:
            flash("Ainda não existe Ano Letivo definido.", "error")
            return redirect(url_for("calendario_escolar_importar"))

        interrupcoes = (
            InterrupcaoLetiva.query
            .filter_by(ano_letivo_id=ano.id)
            .order_by(InterrupcaoLetiva.tipo)
            .all()
        )
        feriados = (
            Feriado.query
            .filter_by(ano_letivo_id=ano.id)
            .order_by(Feriado.data)
            .all()
        )

        return render_template(
            "calendario/escolar.html",
            ano=ano,
            interrupcoes=interrupcoes,
            feriados=feriados,
        )

    # ----------------------------------------
    # CALENDÁRIO ESCOLAR – GESTÃO (CRUD)
    # ----------------------------------------
    @app.route("/calendario-escolar/gestao")
    def calendario_escolar_gestao():
        ano = get_ano_letivo_atual()
        if not ano:
            flash("Ainda não existe Ano Letivo definido.", "error")
            return redirect(url_for("calendario_escolar_importar"))

        interrupcoes = (
            InterrupcaoLetiva.query
            .filter_by(ano_letivo_id=ano.id)
            .order_by(InterrupcaoLetiva.tipo)
            .all()
        )
        feriados = (
            Feriado.query
            .filter_by(ano_letivo_id=ano.id)
            .order_by(Feriado.data)
            .all()
        )

        anos = (
            AnoLetivo.query
            .order_by(AnoLetivo.data_inicio_ano.desc().nullslast(), AnoLetivo.nome)
            .all()
        )

        return render_template(
            "calendario/gestao.html",
            ano=ano,
            anos=anos,
            interrupcoes=interrupcoes,
            feriados=feriados,
        )

    # ---- Interrupções ----
    @app.route("/calendario-escolar/interrupcoes/add", methods=["POST"])
    def interrupcao_add():
        ano = get_ano_letivo_atual()
        if not ano or ano.fechado:
            flash("Ano letivo fechado ou inexistente: não é possível adicionar interrupções.", "error")
            return redirect(url_for("calendario_escolar_gestao"))

        tipo = request.form.get("tipo") or "outros"
        data_inicio = _parse_date_form(request.form.get("data_inicio"))
        data_fim = _parse_date_form(request.form.get("data_fim"))
        data_text = request.form.get("data_text") or None
        descricao = request.form.get("descricao") or None

        intr = InterrupcaoLetiva(
            ano_letivo_id=ano.id,
            tipo=tipo,
            data_inicio=data_inicio,
            data_fim=data_fim,
            data_text=data_text,
            descricao=descricao,
        )
        db.session.add(intr)
        db.session.commit()
        flash("Interrupção registada.", "success")
        return redirect(url_for("calendario_escolar_gestao", ano_id=ano.id))

    @app.route("/calendario-escolar/interrupcoes/<int:intr_id>/edit", methods=["GET", "POST"])
    def interrupcao_edit(intr_id):
        intr = InterrupcaoLetiva.query.get_or_404(intr_id)
        ano = intr.ano_letivo if hasattr(intr, "ano_letivo") else None

        if request.method == "POST":
            if ano and ano.fechado:
                flash("Ano letivo fechado: não é possível editar esta interrupção.", "error")
                return redirect(url_for("calendario_escolar_gestao", ano_id=ano.id))

            intr.tipo = request.form.get("tipo") or intr.tipo
            intr.data_inicio = _parse_date_form(request.form.get("data_inicio"))
            intr.data_fim = _parse_date_form(request.form.get("data_fim"))
            intr.data_text = request.form.get("data_text") or None
            intr.descricao = request.form.get("descricao") or None
            db.session.commit()
            flash("Interrupção atualizada.", "success")
            return redirect(url_for("calendario_escolar_gestao", ano_id=intr.ano_letivo_id))

        return render_template("calendario/editar_interrupcao.html", interrupcao=intr)

    @app.route("/calendario-escolar/interrupcoes/<int:intr_id>/delete", methods=["POST"])
    def interrupcao_delete(intr_id):
        intr = InterrupcaoLetiva.query.get_or_404(intr_id)
        ano = intr.ano_letivo if hasattr(intr, "ano_letivo") else None

        if ano and ano.fechado:
            flash("Ano letivo fechado: não é possível apagar esta interrupção.", "error")
            return redirect(url_for("calendario_escolar_gestao", ano_id=ano.id))

        ano_id = intr.ano_letivo_id
        db.session.delete(intr)
        db.session.commit()
        flash("Interrupção apagada.", "success")
        return redirect(url_for("calendario_escolar_gestao", ano_id=ano_id))

    # ---- Feriados ----
    @app.route("/calendario-escolar/feriados/add", methods=["POST"])
    def feriado_add():
        ano = get_ano_letivo_atual()
        if not ano or ano.fechado:
            flash("Ano letivo fechado ou inexistente: não é possível adicionar feriados.", "error")
            return redirect(url_for("calendario_escolar_gestao"))

        nome = request.form.get("nome") or "Feriado"
        data = _parse_date_form(request.form.get("data"))
        data_text = request.form.get("data_text") or None

        fer = Feriado(
            ano_letivo_id=ano.id,
            nome=nome,
            data=data,
            data_text=data_text,
        )
        db.session.add(fer)
        db.session.commit()
        flash("Feriado registado.", "success")
        return redirect(url_for("calendario_escolar_gestao", ano_id=ano.id))

    @app.route("/calendario-escolar/feriados/<int:fer_id>/edit", methods=["GET", "POST"])
    def feriado_edit(fer_id):
        fer = Feriado.query.get_or_404(fer_id)
        ano = fer.ano_letivo if hasattr(fer, "ano_letivo") else None

        if request.method == "POST":
            if ano and ano.fechado:
                flash("Ano letivo fechado: não é possível editar este feriado.", "error")
                return redirect(url_for("calendario_escolar_gestao", ano_id=ano.id))

            fer.nome = request.form.get("nome") or fer.nome
            fer.data = _parse_date_form(request.form.get("data"))
            fer.data_text = request.form.get("data_text") or None
            db.session.commit()
            flash("Feriado atualizado.", "success")
            return redirect(url_for("calendario_escolar_gestao", ano_id=fer.ano_letivo_id))

        return render_template("calendario/editar_feriado.html", feriado=fer)

    @app.route("/calendario-escolar/feriados/<int:fer_id>/delete", methods=["POST"])
    def feriado_delete(fer_id):
        fer = Feriado.query.get_or_404(fer_id)
        ano = fer.ano_letivo if hasattr(fer, "ano_letivo") else None

        if ano and ano.fechado:
            flash("Ano letivo fechado: não é possível apagar este feriado.", "error")
            return redirect(url_for("calendario_escolar_gestao", ano_id=ano.id))

        ano_id = fer.ano_letivo_id
        db.session.delete(fer)
        db.session.commit()
        flash("Feriado apagado.", "success")
        return redirect(url_for("calendario_escolar_gestao", ano_id=ano_id))

    @app.route("/calendario-escolar/feriados/add-nacionais", methods=["POST"])
    def feriados_add_nacionais():
        ano = get_ano_letivo_atual()
        if not ano or ano.fechado:
            flash("Ano letivo fechado ou inexistente: não é possível adicionar feriados nacionais.", "error")
            return redirect(url_for("calendario_escolar_gestao"))

        if not (ano.data_inicio_ano and ano.data_fim_ano):
            flash("O Ano Letivo precisa de ter datas de início e fim definidas.", "error")
            return redirect(url_for("calendario_escolar_gestao", ano_id=ano.id))

        anos_abrangidos = {ano.data_inicio_ano.year, ano.data_fim_ano.year}

        existentes = {
            (f.nome, f.data)
            for f in Feriado.query.filter_by(ano_letivo_id=ano.id).all()
            if f.data is not None
        }

        novos = []

        for y in anos_abrangidos:
            pascoa = _easter_sunday(y)
            carnaval = pascoa - timedelta(days=47)
            sexta_santa = pascoa - timedelta(days=2)
            corpo_deus = pascoa + timedelta(days=60)

            candidatos = [
                ("Ano Novo", date(y, 1, 1)),
                ("Carnaval", carnaval),
                ("Sexta-feira Santa", sexta_santa),
                ("Dia da Liberdade", date(y, 4, 25)),
                ("Dia do Trabalhador", date(y, 5, 1)),
                ("Corpo de Deus", corpo_deus),
                ("Dia de Portugal", date(y, 6, 10)),
                ("Assunção de Nossa Senhora", date(y, 8, 15)),
                ("Implantação da República", date(y, 10, 5)),
                ("Todos os Santos", date(y, 11, 1)),
                ("Restauração da Independência", date(y, 12, 1)),
                ("Imaculada Conceição", date(y, 12, 8)),
                ("Natal", date(y, 12, 25)),
            ]

            for nome, d in candidatos:
                if not (ano.data_inicio_ano <= d <= ano.data_fim_ano):
                    continue
                chave = (nome, d)
                if chave in existentes:
                    continue
                novos.append(Feriado(
                    ano_letivo_id=ano.id,
                    nome=nome,
                    data=d,
                ))
                existentes.add(chave)

        if not novos:
            flash("Não há novos feriados nacionais para adicionar.", "info")
        else:
            db.session.add_all(novos)
            db.session.commit()
            flash(f"Foram adicionados {len(novos)} feriados nacionais.", "success")

        return redirect(url_for("calendario_escolar_gestao", ano_id=ano.id))

    # ----------------------------------------
    # EXPORTAR CALENDÁRIO ESCOLAR EM JSON
    # ----------------------------------------
    @app.route("/api/calendario-escolar.json")
    def calendario_escolar_json():
        ano = get_ano_letivo_atual()
        if not ano:
            payload = {"erro": "Ano letivo não encontrado."}
            json_str = json.dumps(payload, ensure_ascii=False, indent=2)
            return Response(json_str, mimetype="application/json", status=404)

        ano_data = {
            "id": ano.id,
            "nome": ano.nome,
            "data_inicio_ano": ano.data_inicio_ano.isoformat() if ano.data_inicio_ano else None,
            "data_fim_ano": ano.data_fim_ano.isoformat() if ano.data_fim_ano else None,
            "data_fim_semestre1": ano.data_fim_semestre1.isoformat() if ano.data_fim_semestre1 else None,
            "data_inicio_semestre2": ano.data_inicio_semestre2.isoformat() if ano.data_inicio_semestre2 else None,
            "descricao": ano.descricao,
            "ativo": ano.ativo,
            "fechado": ano.fechado,
        }

        interrupcoes = []
        for intr in InterrupcaoLetiva.query.filter_by(ano_letivo_id=ano.id).all():
            dias_expandido = [
                d.isoformat()
                for d in expand_dates(intr.data_inicio, intr.data_text)
            ]
            interrupcoes.append({
                "id": intr.id,
                "tipo": intr.tipo,
                "data_inicio": intr.data_inicio.isoformat() if intr.data_inicio else None,
                "data_fim": intr.data_fim.isoformat() if intr.data_fim else None,
                "data_text": intr.data_text,
                "descricao": intr.descricao,
                "dias_expandido": dias_expandido,
            })

        feriados = []
        for fer in Feriado.query.filter_by(ano_letivo_id=ano.id).all():
            dias_expandido = [
                d.isoformat()
                for d in expand_dates(fer.data, fer.data_text)
            ]
            feriados.append({
                "id": fer.id,
                "nome": fer.nome,
                "data": fer.data.isoformat() if fer.data else None,
                "data_text": fer.data_text,
                "dias_expandido": dias_expandido,
            })

        payload = {
            "ano_letivo": ano_data,
            "interrupcoes": interrupcoes,
            "feriados": feriados,
        }

        json_str = json.dumps(payload, ensure_ascii=False, indent=2)

        if request.args.get("download") == "1":
            filename = f"calendario_escolar_{ano.nome}.json"
            return Response(
                json_str,
                mimetype="application/json",
                headers={"Content-Disposition": f'attachment; filename=\"{filename}\"'},
            )

        return Response(json_str, mimetype="application/json")

    return app


if __name__ == "__main__":
    app = create_app()
    debug_enabled = os.environ.get("FLASK_DEBUG", "0") == "1"
    use_reloader = os.environ.get("FLASK_USE_RELOADER", "1") == "1"
    app.run(debug=debug_enabled, use_reloader=use_reloader)
