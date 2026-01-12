from __future__ import annotations

import re
from datetime import date, timedelta, datetime
from typing import List, Dict, Set, Tuple, Optional
from collections import defaultdict
from uuid import uuid4

from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload

from models import (
    db,
    Turma,
    Periodo,
    Modulo,
    CalendarioAula,
    AulaAluno,
    AnoLetivo,
    InterrupcaoLetiva,
    Feriado,
    Horario,
    TurmaDisciplina,
    Disciplina,
    Aluno,
    Exclusao,
    Extra,
    Livro,
)


# ----------------------------------------
# Helpers de datas em PT
# ----------------------------------------

MESES_PT = {
    "janeiro": 1,
    "fevereiro": 2,
    "março": 3,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}

PERIODOS_TURMA_VALIDOS = {"anual", "semestre1", "semestre2"}


def tipos_periodo_para_turma(turma: Turma) -> Set[str]:
    tipo_principal = getattr(turma, "periodo_tipo", None) or "anual"

    permitidos = {"modular"}
    if tipo_principal in PERIODOS_TURMA_VALIDOS:
        permitidos.add(tipo_principal)
    else:
        permitidos.add("anual")

    return permitidos


def filtrar_periodos_para_turma(turma: Turma, periodos: List[Periodo]) -> List[Periodo]:
    permitidos = tipos_periodo_para_turma(turma)
    return [p for p in periodos if p.tipo in permitidos]


def garantir_periodos_basicos_para_turma(turma: Turma) -> None:
    """
    Garante que a turma tem os períodos:
      - Anual
      - 1.º semestre
      - 2.º semestre
    com base nas datas definidas no Ano Letivo.

    NÃO mexe nos períodos 'modular' (esses serão definidos para pros).
    """
    ano: AnoLetivo | None = turma.ano_letivo
    if not ano:
        return

    # Helper interno
    def _get_periodo(tipo: str) -> Periodo | None:
        return (
            Periodo.query
            .filter_by(turma_id=turma.id, tipo=tipo)
            .first()
        )

    # --- Anual ---
    if ano.data_inicio_ano and ano.data_fim_ano:
        p_anual = _get_periodo("anual")
        if not p_anual:
            p_anual = Periodo(
                turma_id=turma.id,
                nome="Anual",
                tipo="anual",
                data_inicio=ano.data_inicio_ano,
                data_fim=ano.data_fim_ano,
            )
            db.session.add(p_anual)
        else:
            # atualizar datas se for preciso
            p_anual.data_inicio = ano.data_inicio_ano
            p_anual.data_fim = ano.data_fim_ano

    # --- 1.º semestre ---
    inicio_s1 = ano.data_inicio_ano
    fim_s1 = getattr(ano, "data_fim_semestre1", None)

    if inicio_s1 and fim_s1:
        p_s1 = _get_periodo("semestre1")
        if not p_s1:
            p_s1 = Periodo(
                turma_id=turma.id,
                nome="1.º semestre",
                tipo="semestre1",
                data_inicio=inicio_s1,
                data_fim=fim_s1,
            )
            db.session.add(p_s1)
        else:
            p_s1.data_inicio = inicio_s1
            p_s1.data_fim = fim_s1

    # --- 2.º semestre ---
    inicio_s2 = getattr(ano, "data_inicio_semestre2", None)
    fim_s2 = ano.data_fim_ano

    if inicio_s2 and fim_s2:
        p_s2 = _get_periodo("semestre2")
        if not p_s2:
            p_s2 = Periodo(
                turma_id=turma.id,
                nome="2.º semestre",
                tipo="semestre2",
                data_inicio=inicio_s2,
                data_fim=fim_s2,
            )
            db.session.add(p_s2)
        else:
            p_s2.data_inicio = inicio_s2
            p_s2.data_fim = fim_s2

    db.session.commit()


def garantir_modulos_para_turma(turma: Turma) -> List[Modulo]:
    """
    Garante que a turma tem pelo menos um módulo configurado.

    - Para turmas do ensino regular, cria automaticamente um módulo
      "Geral" (não editável) se não existir nenhum.
    - Para turmas profissionais mantém-se a exigência de módulos
      explícitos, devolvendo a lista vazia quando não existirem.
    """

    modulos: List[Modulo] = (
        Modulo.query.filter_by(turma_id=turma.id).order_by(Modulo.id).all()
    )
    if modulos:
        return modulos

    if turma.tipo != "regular":
        return []

    modulo_geral = Modulo(
        turma_id=turma.id,
        nome="Geral",
        total_aulas=0,
        tolerancia=0,
    )
    db.session.add(modulo_geral)
    db.session.commit()
    return [modulo_geral]


def _parse_pt_date(texto: str, fallback_year: int | None = None) -> date:
    """
    Converte texto tipo '22 de dezembro de 2025' numa date.
    Aceita também '22 de dezembro' se for fornecido fallback_year.

    Lança ValueError se não conseguir.
    """
    t = texto.strip().lower()
    # Ex.: "22 de dezembro de 2025" ou "22 de dezembro"
    m = re.match(
        r"^(\d{1,2})\s+de\s+([a-zçãéô]+)(?:\s+de\s+(\d{4}))?$",
        t,
        flags=re.IGNORECASE,
    )
    if not m:
        raise ValueError(f"Formato de data PT não reconhecido: {texto!r}")

    dia = int(m.group(1))
    mes_nome = m.group(2)
    ano_str = m.group(3)
    ano = int(ano_str) if ano_str else fallback_year
    if not ano:
        raise ValueError(f"Formato de data PT não reconhecido: {texto!r}")
    mes = MESES_PT.get(mes_nome)
    if not mes:
        raise ValueError(f"Mês PT não reconhecido: {mes_nome!r}")
    return date(ano, mes, dia)


def expand_dates(data_inicial: Optional[date], data_text: Optional[str]) -> List[date]:
    """
    Expande uma descrição textual PT em lista de datas.

    Suporta:
      - data_inicial sem data_text → [data_inicial]
      - "22 de dezembro de 2025 a 2 de janeiro de 2026"
      - "16 e 17 de fevereiro de 2026"
      - "22 de dezembro de 2025"
    """
    if data_text and data_text.strip():
        t = data_text.strip().lower()

        # Caso "16 e 17 de fevereiro de 2026"
        m_duas = re.match(
            r"^\s*(\d{1,2})\s+e\s+(\d{1,2})\s+de\s+([a-zçãéô]+)\s+de\s+(\d{4})\s*$",
            t,
            flags=re.IGNORECASE,
        )
        if m_duas:
            d1 = int(m_duas.group(1))
            d2 = int(m_duas.group(2))
            mes_nome = m_duas.group(3)
            ano = int(m_duas.group(4))
            mes = MESES_PT.get(mes_nome)
            if not mes:
                raise ValueError(f"Mês PT não reconhecido: {mes_nome!r}")
            return [date(ano, mes, d1), date(ano, mes, d2)]

        # Caso intervalo "22 de dezembro de 2025 a 2 de janeiro de 2026"
        if " a " in t:
            esquerda, direita = t.split(" a ", 1)
            d2 = _parse_pt_date(direita)
            try:
                d1 = _parse_pt_date(esquerda, fallback_year=d2.year)
            except ValueError:
                # Caso "22 a 28 de janeiro de 2026" ou "10 a 11 de novembro de 2025"
                # em que o mês/ano só aparecem à direita, reutilizamos os de d2.
                apenas_dia = re.match(r"^\s*(\d{1,2})\s*$", esquerda)
                if not apenas_dia:
                    raise
                d1 = date(d2.year, d2.month, int(apenas_dia.group(1)))
            if d2 < d1:
                d1, d2 = d2, d1
            dias = []
            atual = d1
            while atual <= d2:
                dias.append(atual)
                atual += timedelta(days=1)
            return dias

        # Caso uma única data textual (pode não trazer o ano)
        fallback_year = None
        if data_inicial:
            fallback_year = data_inicial.year
        else:
            fallback_year = date.today().year
        return [_parse_pt_date(t, fallback_year=fallback_year)]

    # Sem data_text → usa só data_inicial, se existir
    if data_inicial:
        return [data_inicial]

    return []


# ----------------------------------------
# Helpers de calendário escolar
# ----------------------------------------

def _build_dias_nao_letivos(ano: AnoLetivo) -> Tuple[Set[date], Set[date]]:
    """
    A partir das Interrupções e Feriados do ano letivo,
    devolve dois conjuntos:
      - dias_interrupcao
      - dias_feriados
    """
    dias_interrupcao: Set[date] = set()
    dias_feriados: Set[date] = set()

    interrupcoes = InterrupcaoLetiva.query.filter_by(ano_letivo_id=ano.id).all()
    for intr in interrupcoes:
        if intr.data_text:
            dias = expand_dates(intr.data_inicio, intr.data_text)
        elif intr.data_inicio and intr.data_fim:
            atual = intr.data_inicio
            while atual <= intr.data_fim:
                dias_interrupcao.add(atual)
                atual += timedelta(days=1)
            continue
        elif intr.data_inicio:
            dias = [intr.data_inicio]
        else:
            dias = []
        dias_interrupcao.update(dias)

    feriados = Feriado.query.filter_by(ano_letivo_id=ano.id).all()
    for fer in feriados:
        if fer.data:
            dias_feriados.add(fer.data)
        elif fer.data_text:
            dias = expand_dates(None, fer.data_text)
            dias_feriados.update(dias)

    return dias_interrupcao, dias_feriados


def importar_calendario_escolar_json(payload: dict, ano_destino_id: int | None = None):
    """
    Importa um calendário escolar (interrupções e feriados) a partir de JSON.

    - Se ``ano_destino_id`` for fornecido, aplica ao ano escolhido;
    - Caso contrário tenta corresponder por id/nome no JSON;
    - Se não existir, cria um novo ano letivo com os dados do ficheiro.
    """

    if not isinstance(payload, dict):
        raise ValueError("Formato inválido: esperado um objeto JSON.")

    ano_info = payload.get("ano_letivo") or {}
    interrupcoes_payload = payload.get("interrupcoes") or []
    feriados_payload = payload.get("feriados") or []

    ano: AnoLetivo | None = None

    if ano_destino_id:
        ano = AnoLetivo.query.get(ano_destino_id)
        if not ano:
            raise ValueError("Ano letivo selecionado não encontrado.")

    if not ano and ano_info.get("id"):
        ano = AnoLetivo.query.get(ano_info.get("id"))

    nome_ano = (ano_info.get("nome") or "").strip()
    if not ano and nome_ano:
        ano = AnoLetivo.query.filter(func.lower(AnoLetivo.nome) == nome_ano.lower()).first()

    if not ano:
        if not ano_info:
            raise ValueError("O ficheiro JSON precisa do bloco 'ano_letivo' para criar um novo ano.")

        ano = AnoLetivo(
            nome=nome_ano or "Ano letivo importado",
            descricao=ano_info.get("descricao"),
            ativo=bool(ano_info.get("ativo")) if "ativo" in ano_info else False,
            fechado=bool(ano_info.get("fechado")) if "fechado" in ano_info else False,
        )
        db.session.add(ano)
        db.session.flush()

    if ano.fechado:
        raise ValueError("Ano letivo fechado: não é possível importar o calendário escolar.")

    campos_data = {
        "data_inicio_ano": "data_inicio_ano",
        "data_fim_ano": "data_fim_ano",
        "data_fim_semestre1": "data_fim_semestre1",
        "data_inicio_semestre2": "data_inicio_semestre2",
    }

    for attr, chave in campos_data.items():
        valor = _parse_iso_date(ano_info.get(chave)) if ano_info else None
        if valor:
            setattr(ano, attr, valor)

    if "descricao" in ano_info:
        ano.descricao = ano_info.get("descricao")
    if "ativo" in ano_info:
        ano.ativo = bool(ano_info.get("ativo"))
    if "fechado" in ano_info:
        ano.fechado = bool(ano_info.get("fechado"))

    InterrupcaoLetiva.query.filter_by(ano_letivo_id=ano.id).delete()
    Feriado.query.filter_by(ano_letivo_id=ano.id).delete()

    novas_interrupcoes = 0
    novas_feriados = 0

    for intr in interrupcoes_payload:
        if not isinstance(intr, dict):
            continue
        registo = InterrupcaoLetiva(
            ano_letivo_id=ano.id,
            tipo=intr.get("tipo") or "outros",
            data_inicio=_parse_iso_date(intr.get("data_inicio")),
            data_fim=_parse_iso_date(intr.get("data_fim")),
            data_text=intr.get("data_text") or None,
            descricao=intr.get("descricao") or None,
        )
        db.session.add(registo)
        novas_interrupcoes += 1

    for fer in feriados_payload:
        if not isinstance(fer, dict):
            continue
        registo = Feriado(
            ano_letivo_id=ano.id,
            nome=fer.get("nome") or "Feriado",
            data=_parse_iso_date(fer.get("data")),
            data_text=fer.get("data_text") or None,
        )
        db.session.add(registo)
        novas_feriados += 1

    db.session.commit()

    return ano, {"interrupcoes": novas_interrupcoes, "feriados": novas_feriados}


def _parse_iso_date(valor) -> Optional[date]:
    """Converte valores ISO (YYYY-MM-DD) em date, ignorando entradas inválidas."""

    if not valor:
        return None

    try:
        return date.fromisoformat(str(valor))
    except ValueError:
        return None


def _e_dia_letivo(d: date, ano: AnoLetivo, dias_interrupcao: Set[date], dias_feriados: Set[date]) -> bool:
    """
    Verifica se é dia letivo:
      - dentro dos limites do ano letivo;
      - dia da semana entre segunda e sexta;
      - não estar em interrupções nem feriados.
    """
    if d < ano.data_inicio_ano or d > ano.data_fim_ano:
        return False
    if d.weekday() > 4:  # 0=segunda, ..., 6=domingo
        return False
    if d in dias_interrupcao:
        return False
    if d in dias_feriados:
        return False
    return True


# ----------------------------------------
# Helpers de carga horária da Turma
# ----------------------------------------

def _mapa_carga_semana(turma: Turma) -> Dict[int, float]:
    """
    Devolve um mapa weekday->carga horária.

    1) Se a turma tiver as colunas de carga diária preenchidas, usa-as.
    2) Caso contrário, cai para o somatório dos horários existentes.
    3) Fora de segunda-sexta, devolve 0.
    """
    carga_por_coluna = {
        0: turma.carga_segunda,
        1: turma.carga_terca,
        2: turma.carga_quarta,
        3: turma.carga_quinta,
        4: turma.carga_sexta,
    }

    if any(v is not None for v in carga_por_coluna.values()):
        # Já existe carga específica: normaliza para float e devolve
        return {k: float(v or 0.0) for k, v in carga_por_coluna.items()}

    # Fallback: usar a tabela Horario
    acumulado = {i: 0.0 for i in range(5)}
    for h in Horario.query.filter_by(turma_id=turma.id).all():
        if 0 <= h.weekday <= 4:
            acumulado[h.weekday] += float(h.horas or 0)

    return acumulado


DIAS_PT = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"]


# ----------------------------------------
# Motor principal
# ----------------------------------------

def gerar_calendario_turma(turma_id: int, recalcular_tudo: bool = True) -> int:
    """
    Gera o calendário de aulas para uma turma com base no calendário escolar
    e na configuração de períodos/módulos dessa turma.
    """

    turma: Optional[Turma] = Turma.query.get(turma_id)
    if not turma:
        raise ValueError(f"Turma com id={turma_id} não encontrada.")

    ano: Optional[AnoLetivo] = turma.ano_letivo
    if not ano:
        # Sem ano letivo não há calendário escolar para cruzar
        return 0

    dias_interrupcao, dias_feriados = _build_dias_nao_letivos(ano)

    periodos: List[Periodo] = filtrar_periodos_para_turma(
        turma,
        (
            Periodo.query.filter_by(turma_id=turma.id)
            .order_by(Periodo.data_inicio)
            .all()
        ),
    )
    if not periodos:
        return 0

    modulos: List[Modulo] = garantir_modulos_para_turma(turma)
    if not modulos:
        return 0

    progresso_modulos: Dict[int, int] = {m.id: 0 for m in modulos}
    total_por_modulo: Dict[int, int] = {
        m.id: int(getattr(m, "total_aulas", 0) or 0) for m in modulos
    }
    carga_por_dia: Dict[int, float] = _mapa_carga_semana(turma)

    datas_existentes: Set[date] = set()

    if recalcular_tudo:
        CalendarioAula.query.filter_by(turma_id=turma.id).delete()
        db.session.commit()
    else:
        datas_existentes = {
            a.data
            for a in CalendarioAula.query.filter_by(turma_id=turma.id, apagado=False).all()
            if a.data
        }

    contador_sumario_global = 0
    idx_modulo = 0
    total_criadas = 0

    if not any(carga_por_dia.values()):
        # Sem carga (nem na turma, nem via horários): não há aulas para gerar.
        return 0

    for periodo in periodos:
        if not periodo.data_inicio or not periodo.data_fim:
            continue

        data_atual: date = periodo.data_inicio
        while data_atual <= periodo.data_fim:
            if data_atual in datas_existentes:
                data_atual += timedelta(days=1)
                continue

            if not _e_dia_letivo(data_atual, ano, dias_interrupcao, dias_feriados):
                data_atual += timedelta(days=1)
                continue

            carga_dia = carga_por_dia.get(data_atual.weekday(), 0.0)
            if carga_dia <= 0:
                data_atual += timedelta(days=1)
                continue

            aulas_hoje = int(carga_dia)
            if aulas_hoje <= 0:
                data_atual += timedelta(days=1)
                continue

            sumarios_por_modulo: List[Tuple[Modulo, List[int], int]] = []
            modulo_corrente: Optional[Modulo] = None
            sumarios_correntes: List[int] = []
            numero_final_corrente: Optional[int] = None

            # Seleciona o módulo ativo: se o período tiver módulo dedicado, usa-o;
            # caso contrário, segue a ordem natural dos módulos.
            while aulas_hoje > 0:
                modulo_atual: Optional[Modulo]
                if periodo.modulo_id:
                    modulo_atual = next(
                        (m for m in modulos if m.id == periodo.modulo_id), None
                    )
                    idx_para_avancar = None
                else:
                    if idx_modulo >= len(modulos):
                        break
                    modulo_atual = modulos[idx_modulo]
                    idx_para_avancar = idx_modulo

                if modulo_atual is None:
                    break

                mod_id = modulo_atual.id
                total_modulo = total_por_modulo.get(mod_id, 0)
                dadas = progresso_modulos.get(mod_id, 0)

                # No cálculo inicial do calendário respeitamos sempre o total
                # configurado do módulo. A tolerância, quando existir em turmas
                # profissionais, só deve ser considerada em acréscimos manuais,
                # não durante a geração automática.
                limite = None if total_modulo <= 0 else total_modulo

                if limite is not None and dadas >= limite:
                    if idx_para_avancar is not None:
                        idx_modulo += 1
                        continue
                    break

                dadas += 1
                progresso_modulos[mod_id] = dadas
                contador_sumario_global += 1
                aulas_hoje -= 1

                # Se o módulo mudou, guardar a sequência anterior.
                if modulo_corrente and modulo_corrente.id != modulo_atual.id:
                    sumarios_por_modulo.append(
                        (modulo_corrente, sumarios_correntes, numero_final_corrente or 0)
                    )
                    sumarios_correntes = []
                    numero_final_corrente = None

                modulo_corrente = modulo_atual
                sumarios_correntes.append(contador_sumario_global)
                numero_final_corrente = dadas

                if limite is not None and idx_para_avancar is not None and dadas >= limite:
                    idx_modulo += 1

            if modulo_corrente and sumarios_correntes:
                sumarios_por_modulo.append(
                    (modulo_corrente, sumarios_correntes, numero_final_corrente or 0)
                )

            for modulo_usado, sumarios_hoje, numero_modulo_no_fim in sumarios_por_modulo:
                aula = CalendarioAula(
                    turma_id=turma.id,
                    periodo_id=periodo.id,
                    data=data_atual,
                    weekday=data_atual.weekday(),
                    modulo_id=modulo_usado.id,
                    numero_modulo=numero_modulo_no_fim,
                    total_geral=sumarios_hoje[-1],
                    sumarios=",".join(str(n) for n in sumarios_hoje),
                    tipo="normal",
                )
                db.session.add(aula)
                total_criadas += 1

                datas_existentes.add(data_atual)

            data_atual += timedelta(days=1)

    db.session.commit()

    # Garante que não ficam duplicados antigos e que a numeração se mantém contínua.
    renumerar_calendario_turma(turma.id)

    return total_criadas


DEFAULT_TIPOS_SEM_AULA: Set[str] = {"greve", "servico_oficial", "faltei", "outros"}
TIPOS_ESPECIAIS: Set[str] = {"greve", "servico_oficial", "outros", "extra", "faltei"}


# ----------------------------------------
# Export / import de sumários
# ----------------------------------------


def _periodo_para_data(turma: Turma, data: date) -> Periodo | None:
    """Encontra um período que abrange a data dada para a turma."""

    tipos_permitidos = tipos_periodo_para_turma(turma)

    return (
        Periodo.query.filter(
            Periodo.turma_id == turma.id,
            Periodo.data_inicio <= data,
            Periodo.data_fim >= data,
            Periodo.tipo.in_(tipos_permitidos),
        )
        .order_by(Periodo.data_inicio)
        .first()
    )


def _periodo_padrao_import(turma: Turma, datas: List[date]) -> Periodo | None:
    """
    Garante um período para associar linhas importadas.

    Se existirem períodos, devolve o primeiro; caso contrário cria um período
    "Importado" que cobre o intervalo mínimo/máximo das datas fornecidas.
    """

    existentes = (
        Periodo.query.filter_by(turma_id=turma.id)
        .order_by(Periodo.data_inicio)
        .all()
    )
    filtrados = filtrar_periodos_para_turma(turma, existentes)
    if filtrados:
        return filtrados[0]

    if not datas:
        return None

    inicio = min(datas)
    fim = max(datas)
    tipo_padrao = turma.periodo_tipo if getattr(turma, "periodo_tipo", None) in PERIODOS_TURMA_VALIDOS else "anual"
    periodo = Periodo(
        turma_id=turma.id,
        nome="Importado",
        tipo=tipo_padrao,
        data_inicio=inicio,
        data_fim=fim,
    )
    db.session.add(periodo)
    db.session.commit()
    return periodo


def criar_aula_extra(
    turma: Turma,
    data: date,
    *,
    numero_aulas: int = 1,
    sumario: str | None = None,
    previsao: str | None = None,
    observacoes: str | None = None,
) -> CalendarioAula:
    """Cria uma aula do tipo "extra" para a turma e data indicadas.

    Garante um período e um módulo associados (criando se necessário) para que a
    linha possa ser renumerada posteriormente sem perder dados existentes.
    """

    periodo = _periodo_para_data(turma, data)
    if not periodo:
        periodo = _periodo_padrao_import(turma, [data])

    if not periodo:
        raise ValueError("Não foi possível determinar um período para a data.")

    modulos = garantir_modulos_para_turma(turma)
    modulo_id = modulos[0].id if modulos else None

    quantidade = int(numero_aulas) if numero_aulas else 1
    if quantidade < 1:
        raise ValueError("Indica um número de aulas válido (mínimo 1).")

    sumarios_placeholder = ",".join(str(n) for n in range(1, quantidade + 1))

    aula = CalendarioAula(
        turma_id=turma.id,
        periodo_id=periodo.id,
        data=data,
        weekday=data.weekday(),
        modulo_id=modulo_id,
        tipo="extra",
        sumarios=sumarios_placeholder,
        sumario=(sumario or "").strip() or None,
        previsao=(previsao or "").strip() or None,
        tempos_sem_aula=0,
        observacoes=(observacoes or "").strip() or None,
    )
    db.session.add(aula)
    db.session.commit()

    return aula


def exportar_sumarios_json(
    turma_id: int, periodo_id: int | None = None
) -> List[Dict[str, object]]:
    """Devolve um backup dos sumários da turma (opcionalmente filtrado por período)."""

    query = CalendarioAula.query.filter_by(turma_id=turma_id, apagado=False)
    if periodo_id:
        query = query.filter_by(periodo_id=periodo_id)

    aulas = query.order_by(CalendarioAula.data).all()

    resultado: List[Dict[str, object]] = []
    for aula in aulas:
        resultado.append(
            {
                "data": aula.data.isoformat() if aula.data else None,
                "weekday": aula.weekday,
                "modulo_id": aula.modulo_id,
                "modulo_nome": aula.modulo.nome if aula.modulo else None,
                "numero_modulo": aula.numero_modulo,
                "total_geral": aula.total_geral,
                "sumarios": aula.sumarios,
                "sumario": aula.sumario,
                "previsao": aula.previsao,
                "observacoes": aula.observacoes,
                "tipo": aula.tipo,
                "periodo_id": aula.periodo_id,
                "tempos_sem_aula": aula.tempos_sem_aula,
            }
        )

    return resultado


BACKUP_VERSAO = 1


def _parse_iso_date(data_txt: str | None):
    if not data_txt:
        return None
    try:
        return date.fromisoformat(data_txt)
    except (TypeError, ValueError):
        return None


def _limpar_ano_existente(ano: AnoLetivo):
    """Remove dados ligados ao ano letivo indicado para permitir reposição."""

    turmas = Turma.query.filter_by(ano_letivo_id=ano.id).all()
    for turma in turmas:
        for aula in CalendarioAula.query.filter_by(turma_id=turma.id).all():
            db.session.delete(aula)

        Horario.query.filter_by(turma_id=turma.id).delete(synchronize_session=False)
        Exclusao.query.filter_by(turma_id=turma.id).delete(synchronize_session=False)
        Extra.query.filter_by(turma_id=turma.id).delete(synchronize_session=False)
        Periodo.query.filter_by(turma_id=turma.id).delete(synchronize_session=False)
        Modulo.query.filter_by(turma_id=turma.id).delete(synchronize_session=False)

        db.session.delete(turma)

    Feriado.query.filter_by(ano_letivo_id=ano.id).delete(synchronize_session=False)
    InterrupcaoLetiva.query.filter_by(ano_letivo_id=ano.id).delete(
        synchronize_session=False
    )
    Disciplina.query.filter_by(ano_letivo_id=ano.id).delete(synchronize_session=False)

    db.session.delete(ano)
    db.session.flush()


def exportar_backup_ano(ano: AnoLetivo) -> Dict[str, object]:
    """Cria um backup completo do ano letivo fornecido."""

    if not ano:
        raise ValueError("Ano letivo inválido para exportação.")

    uid_map: dict[tuple[str, int], str] = {}

    def uid(tipo: str, pk: int | None) -> str | None:
        if pk is None:
            return None
        chave = (tipo, pk)
        if chave not in uid_map:
            uid_map[chave] = str(uuid4())
        return uid_map[chave]

    ano_uuid = uid("ano", ano.id)

    disciplinas = (
        Disciplina.query.filter_by(ano_letivo_id=ano.id)
        .order_by(Disciplina.nome)
        .all()
    )

    turmas = (
        Turma.query.options(
            joinedload(Turma.livros),
            joinedload(Turma.turmas_disciplinas).joinedload(TurmaDisciplina.disciplina),
        )
        .filter_by(ano_letivo_id=ano.id)
        .order_by(Turma.nome)
        .all()
    )

    livros_set = {}
    for turma in turmas:
        for livro in turma.livros:
            livros_set[livro.id] = livro

    livros = list(livros_set.values())

    resultado = {
        "versao": BACKUP_VERSAO,
        "gerado_em": datetime.now().isoformat(),
        "ano_letivo": {
            "uuid": ano_uuid,
            "nome": ano.nome,
            "descricao": ano.descricao,
            "data_inicio_ano": ano.data_inicio_ano.isoformat()
            if ano.data_inicio_ano
            else None,
            "data_fim_ano": ano.data_fim_ano.isoformat() if ano.data_fim_ano else None,
            "data_fim_semestre1": ano.data_fim_semestre1.isoformat()
            if ano.data_fim_semestre1
            else None,
            "data_inicio_semestre2": ano.data_inicio_semestre2.isoformat()
            if ano.data_inicio_semestre2
            else None,
            "ativo": bool(ano.ativo),
            "fechado": bool(ano.fechado),
        },
        "disciplinas": [
            {
                "uuid": uid("disciplina", disc.id),
                "nome": disc.nome,
                "sigla": disc.sigla,
            }
            for disc in disciplinas
        ],
        "livros": [
            {
                "uuid": uid("livro", livro.id),
                "nome": livro.nome,
            }
            for livro in livros
        ],
        "turmas": [],
        "feriados": [
            {
                "uuid": uid("feriado", feriado.id),
                "nome": feriado.nome,
                "data": feriado.data.isoformat() if feriado.data else None,
                "data_text": feriado.data_text,
            }
            for feriado in Feriado.query.filter_by(ano_letivo_id=ano.id)
            .order_by(Feriado.data)
            .all()
        ],
        "interrupcoes": [
            {
                "uuid": uid("interrupcao", intr.id),
                "tipo": intr.tipo,
                "data_inicio": intr.data_inicio.isoformat() if intr.data_inicio else None,
                "data_fim": intr.data_fim.isoformat() if intr.data_fim else None,
                "data_text": intr.data_text,
                "descricao": intr.descricao,
            }
            for intr in InterrupcaoLetiva.query.filter_by(ano_letivo_id=ano.id)
            .order_by(InterrupcaoLetiva.data_inicio)
            .all()
        ],
    }

    disciplina_uuid_map = {disc.id: uid("disciplina", disc.id) for disc in disciplinas}
    livro_uuid_map = {livro.id: uid("livro", livro.id) for livro in livros}

    for turma in turmas:
        turma_uuid = uid("turma", turma.id)

        modulos = (
            Modulo.query.filter_by(turma_id=turma.id).order_by(Modulo.id).all()
        )
        mod_uuid_map = {mod.id: uid("modulo", mod.id) for mod in modulos}

        periodos = (
            Periodo.query.filter_by(turma_id=turma.id).order_by(Periodo.data_inicio).all()
        )
        periodo_uuid_map = {p.id: uid("periodo", p.id) for p in periodos}

        alunos = (
            Aluno.query.filter_by(turma_id=turma.id)
            .order_by(Aluno.numero.is_(None), Aluno.numero, Aluno.nome)
            .all()
        )
        aluno_uuid_map = {aluno.id: uid("aluno", aluno.id) for aluno in alunos}

        turma_dict = {
            "uuid": turma_uuid,
            "ano_letivo_uuid": ano_uuid,
            "nome": turma.nome,
            "tipo": turma.tipo,
            "periodo_tipo": turma.periodo_tipo,
            "carga_segunda": turma.carga_segunda,
            "carga_terca": turma.carga_terca,
            "carga_quarta": turma.carga_quarta,
            "carga_quinta": turma.carga_quinta,
            "carga_sexta": turma.carga_sexta,
            "tempo_segunda": turma.tempo_segunda,
            "tempo_terca": turma.tempo_terca,
            "tempo_quarta": turma.tempo_quarta,
            "tempo_quinta": turma.tempo_quinta,
            "tempo_sexta": turma.tempo_sexta,
            "livros": [
                {"livro_uuid": livro_uuid_map.get(livro.id)} for livro in turma.livros
            ],
            "disciplinas": [
                {
                    "uuid": uid("turma_disciplina", rel.id),
                    "disciplina_uuid": disciplina_uuid_map.get(rel.disciplina_id),
                    "horas_semanais": rel.horas_semanais,
                }
                for rel in turma.turmas_disciplinas
                if rel.disciplina_id in disciplina_uuid_map
            ],
            "modulos": [
                {
                    "uuid": mod_uuid_map.get(mod.id),
                    "nome": mod.nome,
                    "total_aulas": mod.total_aulas,
                    "tolerancia": mod.tolerancia,
                }
                for mod in modulos
            ],
            "periodos": [
                {
                    "uuid": periodo_uuid_map.get(per.id),
                    "nome": per.nome,
                    "tipo": per.tipo,
                    "data_inicio": per.data_inicio.isoformat()
                    if per.data_inicio
                    else None,
                    "data_fim": per.data_fim.isoformat() if per.data_fim else None,
                    "modulo_uuid": mod_uuid_map.get(per.modulo_id),
                }
                for per in periodos
            ],
            "horarios": [
                {"weekday": h.weekday, "horas": h.horas}
                for h in Horario.query.filter_by(turma_id=turma.id)
                .order_by(Horario.weekday)
                .all()
            ],
            "exclusoes": [
                {
                    "data": exc.data.isoformat() if exc.data else None,
                    "data_text": exc.data_text,
                    "motivo": exc.motivo,
                    "tipo": exc.tipo,
                }
                for exc in Exclusao.query.filter_by(turma_id=turma.id)
                .order_by(Exclusao.data)
                .all()
            ],
            "extras": [
                {
                    "data": ext.data.isoformat() if ext.data else None,
                    "data_text": ext.data_text,
                    "motivo": ext.motivo,
                    "aulas": ext.aulas,
                    "modulo_nome": ext.modulo_nome,
                    "tipo": ext.tipo,
                }
                for ext in Extra.query.filter_by(turma_id=turma.id)
                .order_by(Extra.data)
                .all()
            ],
            "alunos": [
                {
                    "uuid": aluno_uuid_map.get(aluno.id),
                    "processo": aluno.processo,
                    "numero": aluno.numero,
                    "nome": aluno.nome,
                    "nome_curto": aluno.nome_curto,
                    "nee": aluno.nee,
                    "observacoes": aluno.observacoes,
                }
                for aluno in alunos
            ],
            "calendario": [],
        }

        aulas = (
            CalendarioAula.query.options(
                joinedload(CalendarioAula.avaliacoes).joinedload(AulaAluno.aluno)
            )
            .filter_by(turma_id=turma.id)
            .order_by(CalendarioAula.data, CalendarioAula.id)
            .all()
        )

        for aula in aulas:
            turma_dict["calendario"].append(
                {
                    "uuid": uid("aula", aula.id),
                    "data": aula.data.isoformat() if aula.data else None,
                    "weekday": aula.weekday,
                    "modulo_uuid": mod_uuid_map.get(aula.modulo_id),
                    "numero_modulo": aula.numero_modulo,
                    "total_geral": aula.total_geral,
                    "sumarios": aula.sumarios,
                    "sumario": aula.sumario,
                    "previsao": aula.previsao,
                    "observacoes": aula.observacoes,
                    "tipo": aula.tipo,
                    "apagado": aula.apagado,
                    "periodo_uuid": periodo_uuid_map.get(aula.periodo_id),
                    "tempos_sem_aula": aula.tempos_sem_aula,
                    "atividade": aula.atividade,
                    "atividade_nome": aula.atividade_nome,
                    "avaliacoes": [
                        {
                            "uuid": uid("avaliacao", avaliacao.id),
                            "aluno_uuid": aluno_uuid_map.get(avaliacao.aluno_id),
                            "atraso": avaliacao.atraso,
                            "faltas": avaliacao.faltas,
                            "responsabilidade": avaliacao.responsabilidade,
                            "comportamento": avaliacao.comportamento,
                            "participacao": avaliacao.participacao,
                            "trabalho_autonomo": avaliacao.trabalho_autonomo,
                            "portatil_material": avaliacao.portatil_material,
                            "atividade": avaliacao.atividade,
                            "falta_disciplinar": avaliacao.falta_disciplinar,
                        }
                        for avaliacao in aula.avaliacoes
                        if avaliacao.aluno_id in aluno_uuid_map
                    ],
                }
            )

        resultado["turmas"].append(turma_dict)

    return resultado


def importar_backup_ano(payload: dict, substituir: bool = False) -> Dict[str, int]:
    """Reconstroi um ano letivo completo a partir de um backup JSON."""

    if not isinstance(payload, dict):
        raise ValueError("Formato de backup desconhecido.")

    versao = payload.get("versao", 1)
    if versao > BACKUP_VERSAO:
        raise ValueError("Versão de backup incompatível com esta aplicação.")

    ano_info = payload.get("ano_letivo")
    if not isinstance(ano_info, dict):
        raise ValueError("Secção 'ano_letivo' em falta no backup.")

    nome_ano = (ano_info.get("nome") or "").strip()
    if not nome_ano:
        raise ValueError("Nome do ano letivo em falta no backup.")

    ano_existente = AnoLetivo.query.filter_by(nome=nome_ano).first()
    if ano_existente:
        if not substituir:
            raise ValueError(
                "Já existe um ano letivo com esse nome. Ativa a opção de substituir para continuar."
            )
        _limpar_ano_existente(ano_existente)

    novo_ano = AnoLetivo(
        nome=nome_ano,
        descricao=ano_info.get("descricao"),
        data_inicio_ano=_parse_iso_date(ano_info.get("data_inicio_ano")),
        data_fim_ano=_parse_iso_date(ano_info.get("data_fim_ano")),
        data_fim_semestre1=_parse_iso_date(ano_info.get("data_fim_semestre1")),
        data_inicio_semestre2=_parse_iso_date(ano_info.get("data_inicio_semestre2")),
        ativo=bool(ano_info.get("ativo")),
        fechado=bool(ano_info.get("fechado")),
    )
    db.session.add(novo_ano)
    db.session.flush()

    livros_map: dict[str, Livro] = {}
    for entrada in payload.get("livros", []) or []:
        if not isinstance(entrada, dict):
            continue
        nome = (entrada.get("nome") or "").strip()
        if not nome:
            continue
        uuid_val = entrada.get("uuid")
        existente = Livro.query.filter_by(nome=nome).first()
        livro = existente or Livro(nome=nome)
        db.session.add(livro)
        db.session.flush()
        if uuid_val:
            livros_map[str(uuid_val)] = livro

    disciplinas_map: dict[str, Disciplina] = {}
    for entrada in payload.get("disciplinas", []) or []:
        if not isinstance(entrada, dict):
            continue
        nome = (entrada.get("nome") or "").strip()
        if not nome:
            continue
        disc = Disciplina(
            nome=nome,
            sigla=entrada.get("sigla"),
            ano_letivo_id=novo_ano.id,
        )
        db.session.add(disc)
        db.session.flush()
        uuid_val = entrada.get("uuid")
        if uuid_val:
            disciplinas_map[str(uuid_val)] = disc

    feriados = payload.get("feriados", []) or []
    for entrada in feriados:
        if not isinstance(entrada, dict):
            continue
        feriado = Feriado(
            ano_letivo_id=novo_ano.id,
            nome=entrada.get("nome"),
            data=_parse_iso_date(entrada.get("data")),
            data_text=entrada.get("data_text"),
        )
        db.session.add(feriado)

    interrupcoes = payload.get("interrupcoes", []) or []
    for entrada in interrupcoes:
        if not isinstance(entrada, dict):
            continue
        interrupcao = InterrupcaoLetiva(
            ano_letivo_id=novo_ano.id,
            tipo=entrada.get("tipo") or "outros",
            data_inicio=_parse_iso_date(entrada.get("data_inicio")),
            data_fim=_parse_iso_date(entrada.get("data_fim")),
            data_text=entrada.get("data_text"),
            descricao=entrada.get("descricao"),
        )
        db.session.add(interrupcao)

    db.session.flush()

    aluno_uuid_map: dict[str, Aluno] = {}

    turmas_payload = payload.get("turmas", []) or []
    for turma_data in turmas_payload:
        if not isinstance(turma_data, dict):
            continue

        turma = Turma(
            nome=turma_data.get("nome") or "Turma",
            tipo=turma_data.get("tipo") or "regular",
            periodo_tipo=turma_data.get("periodo_tipo") or "anual",
            ano_letivo_id=novo_ano.id,
            carga_segunda=turma_data.get("carga_segunda"),
            carga_terca=turma_data.get("carga_terca"),
            carga_quarta=turma_data.get("carga_quarta"),
            carga_quinta=turma_data.get("carga_quinta"),
            carga_sexta=turma_data.get("carga_sexta"),
            tempo_segunda=turma_data.get("tempo_segunda"),
            tempo_terca=turma_data.get("tempo_terca"),
            tempo_quarta=turma_data.get("tempo_quarta"),
            tempo_quinta=turma_data.get("tempo_quinta"),
            tempo_sexta=turma_data.get("tempo_sexta"),
        )
        db.session.add(turma)
        db.session.flush()

        for livro_ref in turma_data.get("livros", []) or []:
            if not isinstance(livro_ref, dict):
                continue
            livro_uuid = livro_ref.get("livro_uuid")
            if livro_uuid and livro_uuid in livros_map:
                if livros_map[livro_uuid] not in turma.livros:
                    turma.livros.append(livros_map[livro_uuid])

        for disc_ref in turma_data.get("disciplinas", []) or []:
            if not isinstance(disc_ref, dict):
                continue
            disciplina_uuid = disc_ref.get("disciplina_uuid")
            disciplina = disciplinas_map.get(disciplina_uuid)
            if not disciplina:
                continue
            rel = TurmaDisciplina(
                turma_id=turma.id,
                disciplina_id=disciplina.id,
                horas_semanais=disc_ref.get("horas_semanais"),
            )
            db.session.add(rel)

        alunos_payload = turma_data.get("alunos", []) or []
        for aluno_data in alunos_payload:
            if not isinstance(aluno_data, dict):
                continue
            aluno = Aluno(
                turma_id=turma.id,
                processo=aluno_data.get("processo"),
                numero=aluno_data.get("numero"),
                nome=aluno_data.get("nome") or "Aluno",
                nome_curto=aluno_data.get("nome_curto"),
                nee=aluno_data.get("nee"),
                observacoes=aluno_data.get("observacoes"),
            )
            db.session.add(aluno)
            db.session.flush()

            aluno_uuid = aluno_data.get("uuid")
            if aluno_uuid:
                aluno_uuid_map[str(aluno_uuid)] = aluno

        mod_uuid_map: dict[str, Modulo] = {}
        for mod_data in turma_data.get("modulos", []) or []:
            if not isinstance(mod_data, dict):
                continue
            mod = Modulo(
                turma_id=turma.id,
                nome=mod_data.get("nome") or "Módulo",
                total_aulas=mod_data.get("total_aulas") or 0,
                tolerancia=mod_data.get("tolerancia") or 0,
            )
            db.session.add(mod)
            db.session.flush()
            if mod_data.get("uuid"):
                mod_uuid_map[str(mod_data.get("uuid"))] = mod

        periodo_uuid_map: dict[str, Periodo] = {}
        for per_data in turma_data.get("periodos", []) or []:
            if not isinstance(per_data, dict):
                continue
            periodo = Periodo(
                turma_id=turma.id,
                nome=per_data.get("nome") or "Período",
                tipo=per_data.get("tipo") or "anual",
                data_inicio=_parse_iso_date(per_data.get("data_inicio")),
                data_fim=_parse_iso_date(per_data.get("data_fim")),
                modulo_id=(
                    mod_uuid_map[per_data.get("modulo_uuid")].id
                    if per_data.get("modulo_uuid") in mod_uuid_map
                    else None
                ),
            )
            db.session.add(periodo)
            db.session.flush()
            if per_data.get("uuid"):
                periodo_uuid_map[str(per_data.get("uuid"))] = periodo

        for horario in turma_data.get("horarios", []) or []:
            if not isinstance(horario, dict):
                continue
            db.session.add(
                Horario(
                    turma_id=turma.id,
                    weekday=horario.get("weekday") or 0,
                    horas=horario.get("horas") or 0,
                )
            )

        for exc in turma_data.get("exclusoes", []) or []:
            if not isinstance(exc, dict):
                continue
            db.session.add(
                Exclusao(
                    turma_id=turma.id,
                    data=_parse_iso_date(exc.get("data")),
                    data_text=exc.get("data_text"),
                    motivo=exc.get("motivo"),
                    tipo=exc.get("tipo"),
                )
            )

        for ext in turma_data.get("extras", []) or []:
            if not isinstance(ext, dict):
                continue
            db.session.add(
                Extra(
                    turma_id=turma.id,
                    data=_parse_iso_date(ext.get("data")),
                    data_text=ext.get("data_text"),
                    motivo=ext.get("motivo"),
                    aulas=ext.get("aulas") or 0,
                    modulo_nome=ext.get("modulo_nome"),
                    tipo=ext.get("tipo"),
                )
            )

        aulas_payload = turma_data.get("calendario", []) or []
        for aula_data in aulas_payload:
            if not isinstance(aula_data, dict):
                continue

            aula = CalendarioAula(
                turma_id=turma.id,
                periodo_id=(
                    periodo_uuid_map[aula_data.get("periodo_uuid")].id
                    if aula_data.get("periodo_uuid") in periodo_uuid_map
                    else None
                ),
                data=_parse_iso_date(aula_data.get("data")) or date.today(),
                weekday=aula_data.get("weekday") or 0,
                modulo_id=(
                    mod_uuid_map[aula_data.get("modulo_uuid")].id
                    if aula_data.get("modulo_uuid") in mod_uuid_map
                    else None
                ),
                numero_modulo=aula_data.get("numero_modulo"),
                total_geral=aula_data.get("total_geral"),
                sumarios=aula_data.get("sumarios"),
                sumario=aula_data.get("sumario"),
                previsao=aula_data.get("previsao"),
                observacoes=aula_data.get("observacoes"),
                tipo=aula_data.get("tipo") or "normal",
                apagado=bool(aula_data.get("apagado")),
                tempos_sem_aula=aula_data.get("tempos_sem_aula") or 0,
                atividade=bool(aula_data.get("atividade")),
                atividade_nome=aula_data.get("atividade_nome"),
            )
            db.session.add(aula)
            db.session.flush()

            for avaliacao_data in aula_data.get("avaliacoes", []) or []:
                if not isinstance(avaliacao_data, dict):
                    continue
                aluno_uuid = avaliacao_data.get("aluno_uuid")
                aluno = aluno_uuid_map.get(aluno_uuid)
                if not aluno:
                    continue
                avaliacao = AulaAluno(
                    aula_id=aula.id,
                    aluno_id=aluno.id,
                    atraso=bool(avaliacao_data.get("atraso")),
                    faltas=avaliacao_data.get("faltas") or 0,
                    responsabilidade=avaliacao_data.get("responsabilidade") or 0,
                    comportamento=avaliacao_data.get("comportamento") or 0,
                    participacao=avaliacao_data.get("participacao") or 0,
                    trabalho_autonomo=avaliacao_data.get("trabalho_autonomo") or 0,
                    portatil_material=avaliacao_data.get("portatil_material") or 0,
                    atividade=avaliacao_data.get("atividade") or 0,
                    falta_disciplinar=avaliacao_data.get("falta_disciplinar") or 0,
                )
                db.session.add(avaliacao)

    db.session.flush()

    return {
        "ano": novo_ano.nome,
        "turmas": len(turmas_payload),
        "alunos": len(aluno_uuid_map),
        "disciplinas": len(disciplinas_map),
    }


def listar_aulas_especiais(
    turma_id: int | None = None,
    tipo: str | None = None,
    data_inicio: date | None = None,
    data_fim: date | None = None,
):
    tipos_validos = set(TIPOS_ESPECIAIS)
    query = (
        CalendarioAula.query.options(
            joinedload(CalendarioAula.turma),
            joinedload(CalendarioAula.modulo),
        )
        .filter(CalendarioAula.apagado == False)  # noqa: E712
        .filter(CalendarioAula.tipo.in_(TIPOS_ESPECIAIS))
    )

    if turma_id:
        query = query.filter(CalendarioAula.turma_id == turma_id)
    if tipo in tipos_validos:
        query = query.filter(CalendarioAula.tipo == tipo)
    if data_inicio:
        query = query.filter(CalendarioAula.data >= data_inicio)
    if data_fim:
        query = query.filter(CalendarioAula.data <= data_fim)

    return (
        query.order_by(
            CalendarioAula.data.desc(),
            Turma.nome.asc(),
            CalendarioAula.id.desc(),
        )
        .join(Turma)
        .all()
    )


def listar_sumarios_pendentes(data_limite: date, turma_id: int | None = None) -> List[CalendarioAula]:
    """Devolve aulas anteriores à data_limite cujo sumário ainda não foi preenchido."""

    if data_limite is None:
        data_limite = date.today()

    query = (
        CalendarioAula.query.options(
            joinedload(CalendarioAula.turma),
            joinedload(CalendarioAula.modulo),
        )
        .filter(CalendarioAula.apagado.is_(False))
        .filter(CalendarioAula.tipo == "normal")
        .filter(CalendarioAula.data < data_limite)
        .filter(
            or_(
                CalendarioAula.sumario.is_(None),
                func.trim(CalendarioAula.sumario) == "",
                func.lower(func.trim(CalendarioAula.sumario)) == "none",
            )
        )
    )

    if turma_id:
        query = query.filter(CalendarioAula.turma_id == turma_id)

    return query.order_by(CalendarioAula.data, CalendarioAula.turma_id, CalendarioAula.id).all()




def importar_sumarios_json(turma: Turma, linhas: List[Dict[str, object]]) -> Dict[str, int]:
    """
    Importa ou atualiza linhas do calendário a partir de um backup.

    - Cria módulos em falta (por nome) se necessário.
    - Cria um período "Importado" se a turma não tiver períodos definidos.
    """

    datas: List[date] = []
    for linha in linhas:
        data_txt = linha.get("data")
        if data_txt:
            try:
                datas.append(date.fromisoformat(str(data_txt)))
            except ValueError:
                continue

    periodo_padrao = _periodo_padrao_import(turma, datas)

    modulos_existentes: Dict[int, Modulo] = {
        m.id: m for m in Modulo.query.filter_by(turma_id=turma.id).all()
    }
    modulos_por_nome = {
        (m.nome or "").strip().lower(): m for m in modulos_existentes.values()
    }

    contadores = {"criados": 0, "atualizados": 0, "ignorados": 0}

    for linha in linhas:
        data_txt = linha.get("data")
        try:
            data_linha = date.fromisoformat(str(data_txt)) if data_txt else None
        except ValueError:
            contadores["ignorados"] += 1
            continue

        modulo_id = linha.get("modulo_id")
        modulo_nome = (linha.get("modulo_nome") or "").strip()
        modulo: Modulo | None = None

        if modulo_id and modulo_id in modulos_existentes:
            modulo = modulos_existentes[modulo_id]
        elif modulo_nome:
            modulo = modulos_por_nome.get(modulo_nome.lower())
            if not modulo:
                modulo = Modulo(
                    turma_id=turma.id,
                    nome=modulo_nome,
                    total_aulas=linha.get("total_geral") or 0,
                )
                db.session.add(modulo)
                db.session.flush()
                modulos_existentes[modulo.id] = modulo
                modulos_por_nome[modulo_nome.lower()] = modulo

        periodo: Periodo | None = None
        periodo_id = linha.get("periodo_id")
        if periodo_id:
            periodo = Periodo.query.filter_by(id=periodo_id, turma_id=turma.id).first()

        if not periodo and data_linha:
            periodo = _periodo_para_data(turma, data_linha)

        if not periodo:
            periodo = periodo_padrao

        if not periodo or not data_linha:
            contadores["ignorados"] += 1
            continue

        existente = (
            CalendarioAula.query.filter_by(
                turma_id=turma.id, data=data_linha, apagado=False
            )
            .order_by(CalendarioAula.id)
            .first()
        )

        campos = {
            "periodo_id": periodo.id,
            "data": data_linha,
            "weekday": data_linha.weekday(),
            "modulo_id": modulo.id if modulo else None,
            "numero_modulo": linha.get("numero_modulo"),
            "total_geral": linha.get("total_geral"),
            "sumarios": linha.get("sumarios"),
            "sumario": linha.get("sumario"),
            "previsao": linha.get("previsao"),
            "observacoes": linha.get("observacoes"),
            "tipo": linha.get("tipo") or "normal",
            "tempos_sem_aula": linha.get("tempos_sem_aula"),
        }

        if existente:
            for k, v in campos.items():
                setattr(existente, k, v)
            contadores["atualizados"] += 1
        else:
            nova = CalendarioAula(
                turma_id=turma.id,
                **campos,
            )
            db.session.add(nova)
            contadores["criados"] += 1

    db.session.commit()
    return contadores


def renumerar_calendario_turma(
    turma_id: int, tipos_sem_aula: Optional[Set[str]] | None = None
) -> int:
    """Reatribui a numeração global e por módulo após edições/remoções.

    Retorna o total de linhas processadas. Cada linha tem o seu conjunto de
    sumários refeito para uma sequência contínua e os contadores globais e do
    módulo são atualizados de acordo com a ordem cronológica. Permite
    parametrizar os tipos de aula que não devem contar para o total (ex. greve,
    falta, serviço oficial).
    """

    tipos_sem_aula = set(tipos_sem_aula) if tipos_sem_aula is not None else DEFAULT_TIPOS_SEM_AULA

    deduplicar_calendario_turma(turma_id)

    aulas = (
        CalendarioAula.query.filter_by(turma_id=turma_id, apagado=False)
        .order_by(CalendarioAula.data.asc(), CalendarioAula.id.asc())
        .all()
    )

    total_global = 0
    progresso_modulo: Dict[int, int] = defaultdict(int)

    for aula in aulas:
        total_previsto = _total_previsto_para_aula(aula)
        sem_aula = aula.tipo in tipos_sem_aula

        if sem_aula:
            faltas = aula.tempos_sem_aula if aula.tempos_sem_aula is not None else total_previsto
        else:
            faltas = aula.tempos_sem_aula if aula.tempos_sem_aula is not None else 0

        faltas = max(0, min(faltas, total_previsto))
        aula.tempos_sem_aula = faltas if sem_aula else 0

        quantidade = 0 if sem_aula else total_previsto - faltas

        if quantidade > 0:
            novos_sumarios = list(range(total_global + 1, total_global + quantidade + 1))
            total_global += quantidade
            aula.sumarios = ",".join(str(n) for n in novos_sumarios)
        else:
            # Mantém o sumário preenchido nesse dia, mas sem contar para os totais.
            aula.sumarios = ""

        aula.total_geral = total_global

        if aula.modulo_id:
            progresso_modulo[aula.modulo_id] += quantidade
            aula.numero_modulo = progresso_modulo[aula.modulo_id]
        else:
            aula.numero_modulo = None

    db.session.commit()
    return len(aulas)


def deduplicar_calendario_turma(turma_id: int, commit: bool = True) -> int:
    """Marca como apagadas as linhas duplicadas por data dentro da mesma turma."""

    aulas = (
        CalendarioAula.query.filter_by(turma_id=turma_id, apagado=False)
        .order_by(CalendarioAula.data.asc(), CalendarioAula.id.asc())
        .all()
    )

    vistos: Dict[date, CalendarioAula] = {}
    duplicados: List[CalendarioAula] = []

    for aula in aulas:
        if not aula.data:
            continue

        existente = vistos.get(aula.data)
        if not existente:
            vistos[aula.data] = aula
            continue

        # Preferir manter a linha com mais conteúdo de sumário
        atual_tem_sumario = bool((aula.sumario or "").strip())
        existente_tem_sumario = bool((existente.sumario or "").strip())
        if atual_tem_sumario and not existente_tem_sumario:
            duplicados.append(existente)
            vistos[aula.data] = aula
        else:
            duplicados.append(aula)

    for dup in duplicados:
        dup.apagado = True

    if commit:
        db.session.commit()

    return len(duplicados)


def _periodo_para_data_periodos(periodos: List[Periodo], data: date) -> Optional[Periodo]:
    for periodo in periodos:
        if periodo.data_inicio and periodo.data_fim and periodo.data_inicio <= data <= periodo.data_fim:
            return periodo
    return None


def _contar_aulas(aula: CalendarioAula) -> int:
    total_previsto = _total_previsto_para_aula(aula)

    if aula.tipo in DEFAULT_TIPOS_SEM_AULA:
        return 0

    faltas = aula.tempos_sem_aula if aula.tempos_sem_aula is not None else 0
    faltas = max(0, min(faltas, total_previsto))
    return max(total_previsto - faltas, 0)


def _total_previsto_para_aula(aula: CalendarioAula) -> int:
    sumarios = [s.strip() for s in (aula.sumarios or "").split(",") if s.strip()]
    base = len(sumarios) if sumarios else 1
    tempos = aula.tempos_sem_aula if aula.tempos_sem_aula is not None else 0
    base = max(base, tempos)
    return max(base, 1)


def calcular_mapa_avaliacao_diaria(
    turma: Turma,
    alunos: List,
    data_inicio: Optional[date] = None,
    data_fim: Optional[date] = None,
    periodo_id: Optional[int] = None,
    modulo_id: Optional[int] = None,
) -> Dict[str, List[Dict]]:
    """Devolve mapas de avaliação diária e de atividades para cada aluno.

    """

    query = (
        CalendarioAula.query.filter_by(turma_id=turma.id, apagado=False)
        .filter(~CalendarioAula.tipo.in_(DEFAULT_TIPOS_SEM_AULA))
    )
    if periodo_id:
        query = query.filter(CalendarioAula.periodo_id == periodo_id)
    if modulo_id:
        query = query.filter(CalendarioAula.modulo_id == modulo_id)
    if data_inicio:
        query = query.filter(CalendarioAula.data >= data_inicio)
    if data_fim:
        query = query.filter(CalendarioAula.data <= data_fim)

    aulas = (
        query.options(joinedload(CalendarioAula.avaliacoes))
        .order_by(CalendarioAula.data, CalendarioAula.id)
        .all()
    )

    aulas_por_data: Dict[date, List[CalendarioAula]] = defaultdict(list)
    for aula in aulas:
        aulas_por_data[aula.data].append(aula)

    def _media_para_aluno(
        aluno_id: int, aulas_dia: List[CalendarioAula]
    ) -> tuple[Optional[float], bool]:
        total_previsto = 0
        faltas_total = 0
        soma_notas = 0
        total_campos = 0
        teve_avaliacao = False
        tem_falta_disciplinar = False

        for aula in aulas_dia:
            avaliacao = next((av for av in aula.avaliacoes if av.aluno_id == aluno_id), None)
            if not avaliacao:
                continue

            teve_avaliacao = True
            tempos_aula = _total_previsto_para_aula(aula)
            total_previsto += tempos_aula
            if avaliacao.falta_disciplinar:
                tem_falta_disciplinar = True

            faltas = max(0, min(avaliacao.faltas or 0, tempos_aula))
            if faltas >= tempos_aula:
                faltas_total += faltas
                continue

            notas = [
                avaliacao.responsabilidade or 3,
                avaliacao.comportamento or 3,
                avaliacao.participacao or 3,
                avaliacao.trabalho_autonomo or 3,
                avaliacao.portatil_material or 3,
            ]
            soma_notas += sum(notas)
            total_campos += len(notas)

        if tem_falta_disciplinar:
            return 1.0, True

        if total_campos:
            return round(soma_notas / total_campos, 2), False

        if teve_avaliacao and total_previsto and faltas_total >= total_previsto:
            return 0.0, False

        return None, False

    dias = []
    for data_ref in sorted(aulas_por_data.keys()):
        aulas_dia = aulas_por_data[data_ref]
        medias = {}
        falta_disciplinar_por_aluno = {}
        for aluno in alunos:
            media, falta_disc = _media_para_aluno(aluno.id, aulas_dia)
            medias[aluno.id] = media
            falta_disciplinar_por_aluno[aluno.id] = falta_disc
        faltas = {}
        sumarios_dia: List[str] = []
        tem_falta_disciplinar = False

        for aula in aulas_dia:
            sumarios_aula = [
                s.strip() for s in (aula.sumarios or "").split(",") if s.strip()
            ]
            if sumarios_aula:
                sumarios_dia.extend(sumarios_aula)

        for aluno in alunos:
            faltas_aluno = 0
            for aula in aulas_dia:
                avaliacao = next(
                    (av for av in aula.avaliacoes if av.aluno_id == aluno.id), None
                )
                if not avaliacao:
                    continue

                tempos_aula = _total_previsto_para_aula(aula)
                faltas_aluno += max(0, min(avaliacao.faltas or 0, tempos_aula))
                if avaliacao.falta_disciplinar:
                    tem_falta_disciplinar = True

            faltas[aluno.id] = faltas_aluno

        dias.append(
            {
                "data": data_ref,
                "medias": medias,
                "falta_disciplinar_por_aluno": falta_disciplinar_por_aluno,
                "faltas": faltas,
                "sumarios": ", ".join(sumarios_dia),
                "tem_falta_disciplinar": tem_falta_disciplinar,
            }
        )

    atividades = []
    for aula in aulas:
        if not getattr(aula, "atividade", False):
            continue

        notas = {}
        for aluno in alunos:
            avaliacao = next(
                (av for av in aula.avaliacoes if av.aluno_id == aluno.id), None
            )
            if not avaliacao:
                notas[aluno.id] = None
                continue

            tempos_aula = _total_previsto_para_aula(aula)
            faltas = max(0, min(avaliacao.faltas or 0, tempos_aula))
            if faltas >= tempos_aula:
                notas[aluno.id] = 0.0
            else:
                nota = avaliacao.atividade if avaliacao.atividade is not None else 3
                notas[aluno.id] = float(nota)

        atividades.append(
            {
                "data": aula.data,
                "titulo": aula.atividade_nome or "Atividade",
                "notas": notas,
            }
        )

    return {"dias": dias, "atividades": atividades}


def completar_modulos_profissionais(
    turma_id: int,
    data_removida: Optional[date] = None,
    modulo_removido_id: Optional[int] = None,
) -> int:
    """Acrescenta aulas em turmas profissionais até cumprir o total de cada módulo.

    Deve ser usado após remoções manuais de linhas, para evitar que os módulos
    fiquem com menos aulas do que o total configurado.
    """

    turma = Turma.query.get(turma_id)
    if not turma or turma.tipo != "profissional":
        return 0

    ano = turma.ano_letivo
    if not ano:
        return 0

    periodos: List[Periodo] = filtrar_periodos_para_turma(
        turma,
        (
            Periodo.query.filter_by(turma_id=turma.id)
            .order_by(Periodo.data_inicio)
            .all()
        ),
    )
    periodos_validos = [p for p in periodos if p.data_inicio and p.data_fim]
    if not periodos_validos:
        return 0

    modulos = garantir_modulos_para_turma(turma)
    if not modulos:
        return 0

    carga_por_dia = _mapa_carga_semana(turma)
    if not any(carga_por_dia.values()):
        return 0

    totais_por_modulo: Dict[int, int] = {
        m.id: max(int(m.total_aulas or 0), 0) for m in modulos
    }

    progresso_atual: Dict[int, int] = defaultdict(int)
    aulas_existentes: List[CalendarioAula] = (
        CalendarioAula.query.filter_by(turma_id=turma.id, apagado=False)
        .order_by(CalendarioAula.data.asc(), CalendarioAula.id.asc())
        .all()
    )
    for aula in aulas_existentes:
        if aula.modulo_id:
            progresso_atual[aula.modulo_id] += _contar_aulas(aula)

    deficit_por_modulo: Dict[int, int] = {}
    for mod_id, total in totais_por_modulo.items():
        if total <= 0:
            continue
        atuais = progresso_atual.get(mod_id, 0)
        if atuais < total:
            deficit_por_modulo[mod_id] = total - atuais

    if not deficit_por_modulo:
        return 0

    dias_interrupcao, dias_feriados = _build_dias_nao_letivos(ano)
    data_limite = max(p.data_fim for p in periodos_validos if p.data_fim)
    if data_limite is None:
        return 0

    total_adicionados = 0

    # Processa os módulos em ordem, inserindo as aulas em falta logo após o
    # último dia do módulo e reajustando o que vem a seguir.
    for modulo in modulos:
        deficit = deficit_por_modulo.get(modulo.id, 0)
        if deficit <= 0:
            continue

        aulas_existentes = (
            CalendarioAula.query.filter_by(turma_id=turma.id, apagado=False)
            .order_by(CalendarioAula.data.asc(), CalendarioAula.id.asc())
            .all()
        )
        dias_sem_aula = {
            a.data for a in aulas_existentes if a.tipo in DEFAULT_TIPOS_SEM_AULA and a.data
        }
        aulas_reagendar = [
            a for a in aulas_existentes if a.tipo not in DEFAULT_TIPOS_SEM_AULA
        ]

        ultima_aula_modulo: Optional[CalendarioAula] = None
        for a in reversed(aulas_existentes):
            if a.modulo_id == modulo.id and a.data:
                ultima_aula_modulo = a
                break

        data_inicio = periodos_validos[0].data_inicio
        if ultima_aula_modulo and ultima_aula_modulo.data:
            data_inicio = ultima_aula_modulo.data + timedelta(days=1)

        data_corte = None
        if data_removida and modulo_removido_id and modulo.id == modulo_removido_id:
            data_corte = data_removida
            data_inicio = max(
                (data_corte + timedelta(days=1)) if data_corte else data_inicio,
                periodos_validos[0].data_inicio or data_inicio,
            )

        if not data_inicio:
            continue

        # Tudo o que vem depois da última aula (ou da data removida, se for
        # deste módulo) será empurrado para a frente, após inserirmos as aulas
        # em falta.
        fila_trabalho: List[CalendarioAula | str] = []

        if data_corte:
            fila_trabalho.extend(
                [a for a in aulas_reagendar if a.data and a.data >= data_corte]
            )
        elif ultima_aula_modulo:
            fila_trabalho.extend(
                [
                    a
                    for a in aulas_reagendar
                    if a.data
                    and (
                        a.data > ultima_aula_modulo.data
                        or (
                            a.data == ultima_aula_modulo.data
                            and a.id > ultima_aula_modulo.id
                        )
                    )
                ]
            )
        else:
            fila_trabalho.extend(aulas_reagendar)

        placeholders = [f"novo-{i}" for i in range(deficit)]
        fila_trabalho = placeholders + fila_trabalho

        data_atual = data_inicio
        while data_atual <= data_limite and fila_trabalho:
            if data_atual in dias_sem_aula:
                data_atual += timedelta(days=1)
                continue

            if not _e_dia_letivo(data_atual, ano, dias_interrupcao, dias_feriados):
                data_atual += timedelta(days=1)
                continue

            carga_dia = int(carga_por_dia.get(data_atual.weekday(), 0) or 0)
            if carga_dia <= 0:
                data_atual += timedelta(days=1)
                continue

            periodo = _periodo_para_data_periodos(periodos_validos, data_atual)
            if not periodo:
                data_atual += timedelta(days=1)
                continue

            aulas_agendadas = 0
            while aulas_agendadas < carga_dia and fila_trabalho:
                capacidade_restante = carga_dia - aulas_agendadas
                item = fila_trabalho[0]

                if isinstance(item, CalendarioAula):
                    consumo = max(1, _contar_aulas(item))
                    if consumo > capacidade_restante:
                        break

                    fila_trabalho.pop(0)
                    item.data = data_atual
                    item.periodo_id = periodo.id
                    item.weekday = data_atual.weekday()
                    aulas_agendadas += consumo
                else:
                    placeholders_no_dia = 0
                    while (
                        placeholders_no_dia < capacidade_restante
                        and fila_trabalho
                        and not isinstance(fila_trabalho[0], CalendarioAula)
                    ):
                        fila_trabalho.pop(0)
                        placeholders_no_dia += 1

                    nova = CalendarioAula(
                        turma_id=turma.id,
                        periodo_id=periodo.id,
                        data=data_atual,
                        weekday=data_atual.weekday(),
                        modulo_id=modulo.id,
                        sumarios=",".join("?" for _ in range(placeholders_no_dia)),
                        tipo="normal",
                    )
                    db.session.add(nova)
                    total_adicionados += placeholders_no_dia
                    aulas_agendadas += placeholders_no_dia

            data_atual += timedelta(days=1)

        db.session.commit()

    return total_adicionados
