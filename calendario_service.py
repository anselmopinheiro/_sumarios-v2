from __future__ import annotations

import re
from datetime import date, timedelta
from typing import List, Dict, Set, Tuple, Optional
from collections import defaultdict

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
            d1 = _parse_pt_date(esquerda, fallback_year=d2.year)
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

    if recalcular_tudo:
        CalendarioAula.query.filter_by(turma_id=turma.id).delete()
        db.session.commit()

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

            data_atual += timedelta(days=1)

    db.session.commit()
    return total_criadas


def renumerar_calendario_turma(turma_id: int) -> int:
    """Reatribui a numeração global e por módulo após edições/remoções.

    Retorna o total de linhas processadas. Cada linha tem o seu conjunto de
    sumários refeito para uma sequência contínua e os contadores globais e do
    módulo são atualizados de acordo com a ordem cronológica.
    """

    aulas = (
        CalendarioAula.query.filter_by(turma_id=turma_id)
        .order_by(CalendarioAula.data.asc(), CalendarioAula.id.asc())
        .all()
    )

    total_global = 0
    progresso_modulo: Dict[int, int] = defaultdict(int)

    for aula in aulas:
        sumarios_originais = [s.strip() for s in (aula.sumarios or "").split(",") if s.strip()]
        quantidade = len(sumarios_originais) if sumarios_originais else 1

        novos_sumarios = list(range(total_global + 1, total_global + quantidade + 1))
        total_global += quantidade

        aula.sumarios = ",".join(str(n) for n in novos_sumarios)
        aula.total_geral = total_global

        if aula.modulo_id:
            progresso_modulo[aula.modulo_id] += quantidade
            aula.numero_modulo = progresso_modulo[aula.modulo_id]
        else:
            aula.numero_modulo = None

    db.session.commit()
    return len(aulas)


def _periodo_para_data(periodos: List[Periodo], data: date) -> Optional[Periodo]:
    for periodo in periodos:
        if periodo.data_inicio and periodo.data_fim and periodo.data_inicio <= data <= periodo.data_fim:
            return periodo
    return None


def _contar_aulas(aula: CalendarioAula) -> int:
    sumarios = [s.strip() for s in (aula.sumarios or "").split(",") if s.strip()]
    return len(sumarios) if sumarios else 1


def completar_modulos_profissionais(turma_id: int) -> int:
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
        CalendarioAula.query.filter_by(turma_id=turma.id)
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

    last_aula = aulas_existentes[-1] if aulas_existentes else None
    data_inicio = (
        (last_aula.data + timedelta(days=1))
        if last_aula and last_aula.data
        else periodos_validos[0].data_inicio
    )
    data_limite = max(p.data_fim for p in periodos_validos if p.data_fim)

    if data_inicio is None or data_limite is None:
        return 0

    modulos_em_ordem = [m for m in modulos if m.id in deficit_por_modulo]
    # Se já houve aulas, tenta continuar a partir do último módulo usado;
    # caso contrário começa pelo primeiro com défice.
    ultimo_modulo_id = last_aula.modulo_id if last_aula else None
    idx_corrente = 0
    if ultimo_modulo_id:
        for idx, mod in enumerate(modulos_em_ordem):
            if mod.id == ultimo_modulo_id:
                idx_corrente = idx
                break

    total_adicionados = 0
    data_atual = data_inicio
    while data_atual <= data_limite and any(v > 0 for v in deficit_por_modulo.values()):
        if not _e_dia_letivo(data_atual, ano, dias_interrupcao, dias_feriados):
            data_atual += timedelta(days=1)
            continue

        carga_dia = int(carga_por_dia.get(data_atual.weekday(), 0) or 0)
        if carga_dia <= 0:
            data_atual += timedelta(days=1)
            continue

        periodo = _periodo_para_data(periodos_validos, data_atual)
        if not periodo:
            data_atual += timedelta(days=1)
            continue

        aulas_hoje = carga_dia
        while aulas_hoje > 0 and any(v > 0 for v in deficit_por_modulo.values()):
            modulo = None
            for offset in range(len(modulos_em_ordem)):
                candidato = modulos_em_ordem[(idx_corrente + offset) % len(modulos_em_ordem)]
                if deficit_por_modulo.get(candidato.id, 0) > 0:
                    modulo = candidato
                    idx_corrente = (idx_corrente + offset) % len(modulos_em_ordem)
                    break

            if modulo is None:
                break

            aula = CalendarioAula(
                turma_id=turma.id,
                periodo_id=periodo.id,
                data=data_atual,
                weekday=data_atual.weekday(),
                modulo_id=modulo.id,
                tipo="normal",
            )
            db.session.add(aula)
            deficit_por_modulo[modulo.id] -= 1
            total_adicionados += 1
            aulas_hoje -= 1

            if deficit_por_modulo[modulo.id] <= 0 and idx_corrente < len(modulos_em_ordem) - 1:
                idx_corrente += 1

        data_atual += timedelta(days=1)

    db.session.commit()
    return total_adicionados
