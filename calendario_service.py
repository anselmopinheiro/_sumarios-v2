from __future__ import annotations

import re
from datetime import date, timedelta
from typing import List, Dict, Set, Tuple, Optional
from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from models import (
    db,
    Turma,
    Periodo,
    Modulo,
    CalendarioAula,
    AnoLetivo,
    InterrupcaoLetiva,
    Feriado,
    Horario,
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

    periodos: List[Periodo] = (
        Periodo.query.filter_by(turma_id=turma.id)
        .order_by(Periodo.data_inicio)
        .all()
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

    return (
        Periodo.query.filter(
            Periodo.turma_id == turma.id,
            Periodo.data_inicio <= data,
            Periodo.data_fim >= data,
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

    existente = (
        Periodo.query.filter_by(turma_id=turma.id)
        .order_by(Periodo.data_inicio)
        .first()
    )
    if existente:
        return existente

    if not datas:
        return None

    inicio = min(datas)
    fim = max(datas)
    periodo = Periodo(
        turma_id=turma.id,
        nome="Importado",
        tipo="anual",
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


def exportar_outras_datas_json(
    turma_id: int | None = None,
    tipo: str | None = None,
    data_inicio: date | None = None,
    data_fim: date | None = None,
) -> List[Dict[str, object]]:
    aulas = listar_aulas_especiais(turma_id, tipo, data_inicio, data_fim)

    resultado: List[Dict[str, object]] = []
    for aula in aulas:
        resultado.append(
            {
                "turma_id": aula.turma_id,
                "turma_nome": aula.turma.nome if aula.turma else None,
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


def importar_outras_datas_json(
    linhas: List[Dict[str, object]],
) -> tuple[Dict[str, int], list[str], list[str], set[int]]:
    contadores = {"criados": 0, "atualizados": 0, "ignorados": 0}
    turmas_fechadas: list[str] = []
    turmas_inexistentes: list[str] = []
    turmas_para_renumerar: set[int] = set()

    linhas_por_turma: Dict[int, List[Dict[str, object]]] = defaultdict(list)

    for linha in linhas:
        tipo = (linha.get("tipo") or "").strip() or "normal"
        if tipo not in TIPOS_ESPECIAIS:
            contadores["ignorados"] += 1
            continue

        turma_id = linha.get("turma_id") or None
        turma_nome = None
        turma_payload = linha.get("turma") if isinstance(linha.get("turma"), dict) else None
        if turma_payload:
            turma_nome = turma_payload.get("nome")
            turma_id = turma_id or turma_payload.get("id")
        if not turma_id:
            turma_nome = turma_nome or linha.get("turma_nome")

        turma: Turma | None = None
        if turma_id:
            turma = Turma.query.get(turma_id)
        if not turma and turma_nome:
            turma = Turma.query.filter(func.lower(Turma.nome) == str(turma_nome).lower()).first()

        if not turma:
            contadores["ignorados"] += 1
            if turma_nome:
                turmas_inexistentes.append(str(turma_nome))
            continue

        ano = turma.ano_letivo
        if ano and ano.fechado:
            contadores["ignorados"] += 1
            turmas_fechadas.append(turma.nome)
            continue

        linha = dict(linha)
        linha["tipo"] = tipo
        linhas_por_turma[turma.id].append(linha)

    for turma_id, linhas_turma in linhas_por_turma.items():
        turma = Turma.query.get(turma_id)
        if not turma:
            continue

        resultado = importar_sumarios_json(turma, linhas_turma)
        contadores["criados"] += resultado.get("criados", 0)
        contadores["atualizados"] += resultado.get("atualizados", 0)
        contadores["ignorados"] += resultado.get("ignorados", 0)
        turmas_para_renumerar.add(turma_id)

    for turma_id in turmas_para_renumerar:
        renumerar_calendario_turma(turma_id)

    return contadores, turmas_fechadas, turmas_inexistentes, turmas_para_renumerar


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
        faltas = aula.tempos_sem_aula if aula.tempos_sem_aula is not None else (
            total_previsto if sem_aula else 0
        )
        faltas = max(0, min(faltas, total_previsto))
        aula.tempos_sem_aula = faltas if sem_aula else 0

        quantidade = total_previsto - faltas if sem_aula else total_previsto

        if quantidade > 0:
            novos_sumarios = list(range(total_global + 1, total_global + quantidade + 1))
            total_global += quantidade
            aula.sumarios = ",".join(str(n) for n in novos_sumarios)
        else:
            # Mantém o sumário preenchido nesse dia, mas sem contar para os totais.
            aula.sumarios = aula.sumarios or ""

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
        faltas = aula.tempos_sem_aula if aula.tempos_sem_aula is not None else total_previsto
        faltas = max(0, min(faltas, total_previsto))
        return max(total_previsto - faltas, 0)

    return total_previsto


def _total_previsto_para_aula(aula: CalendarioAula) -> int:
    sumarios = [s.strip() for s in (aula.sumarios or "").split(",") if s.strip()]
    return len(sumarios) if sumarios else 1


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

    periodos: List[Periodo] = (
        Periodo.query.filter_by(turma_id=turma.id)
        .order_by(Periodo.data_inicio)
        .all()
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
