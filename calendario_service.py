from __future__ import annotations

import re
from datetime import date, timedelta
from typing import List, Dict, Set, Tuple, Optional

from models import (
    db,
    Livro,
    Turma,
    Periodo,
    Modulo,
    CalendarioAula,
    AnoLetivo,
    InterrupcaoLetiva,
    Feriado,
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

from models import db, Turma, Periodo, AnoLetivo


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
    if ano.data_inicio_1_semestre and ano.data_fim_1_semestre:
        p_s1 = _get_periodo("semestre1")
        if not p_s1:
            p_s1 = Periodo(
                turma_id=turma.id,
                nome="1.º semestre",
                tipo="semestre1",
                data_inicio=ano.data_inicio_1_semestre,
                data_fim=ano.data_fim_1_semestre,
            )
            db.session.add(p_s1)
        else:
            p_s1.data_inicio = ano.data_inicio_1_semestre
            p_s1.data_fim = ano.data_fim_1_semestre

    # --- 2.º semestre ---
    if ano.data_inicio_2_semestre and ano.data_fim_2_semestre:
        p_s2 = _get_periodo("semestre2")
        if not p_s2:
            p_s2 = Periodo(
                turma_id=turma.id,
                nome="2.º semestre",
                tipo="semestre2",
                data_inicio=ano.data_inicio_2_semestre,
                data_fim=ano.data_fim_2_semestre,
            )
            db.session.add(p_s2)
        else:
            p_s2.data_inicio = ano.data_inicio_2_semestre
            p_s2.data_fim = ano.data_fim_2_semestre

    db.session.commit()


def _parse_pt_date(texto: str) -> date:
    """
    Converte texto tipo '22 de dezembro de 2025' numa date.
    Lança ValueError se não conseguir.
    """
    t = texto.strip().lower()
    # Ex.: "22 de dezembro de 2025"
    m = re.match(
        r"^(\d{1,2})\s+de\s+([a-zçãéô]+)\s+de\s+(\d{4})$",
        t,
        flags=re.IGNORECASE,
    )
    if not m:
        raise ValueError(f"Formato de data PT não reconhecido: {texto!r}")

    dia = int(m.group(1))
    mes_nome = m.group(2)
    ano = int(m.group(3))
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
            d1 = _parse_pt_date(esquerda)
            d2 = _parse_pt_date(direita)
            if d2 < d1:
                d1, d2 = d2, d1
            dias = []
            atual = d1
            while atual <= d2:
                dias.append(atual)
                atual += timedelta(days=1)
            return dias

        # Caso uma única data textual
        return [_parse_pt_date(t)]

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

def _carga_para_dia_semana(turma: Turma, weekday: int) -> float:
    """
    Devolve a carga horária da turma para o dia da semana dado
    (0=segunda ... 4=sexta). Fora disso devolve 0.
    """
    if weekday == 0:
        return turma.carga_segunda or 0.0
    if weekday == 1:
        return turma.carga_terca or 0.0
    if weekday == 2:
        return turma.carga_quarta or 0.0
    if weekday == 3:
        return turma.carga_quinta or 0.0
    if weekday == 4:
        return turma.carga_sexta or 0.0
    return 0.0


DIAS_PT = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"]


# ----------------------------------------
# Motor principal
# ----------------------------------------

def gerar_calendarios(livro_id: int, recalcular_tudo: bool = True) -> None:
    """
    Gera o calendário de aulas para todas as turmas associadas a um Livro.

    Integra:
      - Ano Letivo (datas início/fim);
      - Interrupções e Feriados (calendário escolar);
      - Carga horária semanal da turma (Seg–Sex);
      - Módulos com número total de aulas (permitindo +2 de margem);
      - Numeração global de sumários.

    Neste momento o parâmetro `recalcular_tudo` é usado apenas para eventual
    lógica futura; para já, sempre que é chamado, apaga e recria o calendário
    das turmas desse livro.
    """
    livro: Optional[Livro] = Livro.query.get(livro_id)
    if not livro:
        raise ValueError(f"Livro com id={livro_id} não encontrado.")

    # Para cada turma associada ao livro
    for turma in livro.turmas:
        ano: Optional[AnoLetivo] = turma.ano_letivo
        if not ano:
            # Sem ano letivo, não podemos cruzar com calendário escolar
            continue

        dias_interrupcao, dias_feriados = _build_dias_nao_letivos(ano)

        # Obter períodos da turma
        periodos: List[Periodo] = (
            Periodo.query
            .filter_by(turma_id=turma.id)
            .order_by(Periodo.data_inicio)
            .all()
        )
        if not periodos:
            # Sem períodos, nada para gerar
            continue

        # Obter módulos da turma neste livro
        # Ajusta os filtros se, no teu modelo, a relação for diferente.
        modulos: List[Modulo] = (
            Modulo.query
            .filter_by(turma_id=turma.id, livro_id=livro.id)
            .order_by(Modulo.id)
            .all()
        )
        if not modulos:
            continue

        # Progresso em memória: quantas aulas já foram dadas por módulo
        # (não mexemos nos valores persistidos do modelo).
        progresso_modulos: Dict[int, int] = {m.id: 0 for m in modulos}

        # TOTAL previsto por módulo (ajusta o nome do campo se for diferente)
        total_por_modulo: Dict[int, int] = {
            m.id: int(getattr(m, "total_aulas", 0) or 0)  # <--- ajusta se necessário
            for m in modulos
        }

        # Antes de gerar, limpamos o calendário existente desta turma + livro
        CalendarioAula.query.filter_by(livro_id=livro.id, turma_id=turma.id).delete()
        db.session.commit()

        # Numeração global de sumários (continua ao longo do ano)
        contador_sumario_global = 0

        # Índice do módulo atual
        idx_modulo = 0

        for periodo in periodos:
            if not periodo.data_inicio or not periodo.data_fim:
                continue

            data_atual: date = periodo.data_inicio
            while data_atual <= periodo.data_fim:
                # Verificar se é dia letivo e se a turma tem carga nesse dia
                if not _e_dia_letivo(data_atual, ano, dias_interrupcao, dias_feriados):
                    data_atual += timedelta(days=1)
                    continue

                carga_dia = _carga_para_dia_semana(turma, data_atual.weekday())
                if carga_dia <= 0:
                    data_atual += timedelta(days=1)
                    continue

                aulas_hoje = int(carga_dia)  # assumimos que a carga são "nº de aulas"
                if aulas_hoje <= 0 or idx_modulo >= len(modulos):
                    data_atual += timedelta(days=1)
                    continue

                sumarios_hoje: List[int] = []
                numero_modulo_no_fim: Optional[int] = None
                modulo_usado: Optional[Modulo] = None

                while aulas_hoje > 0 and idx_modulo < len(modulos):
                    modulo_atual = modulos[idx_modulo]
                    mod_id = modulo_atual.id
                    total_modulo = total_por_modulo.get(mod_id, 0)
                    dadas = progresso_modulos.get(mod_id, 0)

                    # Limite com pequena tolerância (+2 aulas) para casos práticos
                    limite = total_modulo + 2

                    if dadas >= limite:
                        idx_modulo += 1
                        continue

                    # Regista uma aula nova neste módulo
                    dadas += 1
                    progresso_modulos[mod_id] = dadas
                    contador_sumario_global += 1
                    aulas_hoje -= 1

                    sumarios_hoje.append(contador_sumario_global)
                    numero_modulo_no_fim = dadas
                    modulo_usado = modulo_atual

                if sumarios_hoje and modulo_usado is not None:
                    # Cria uma linha de calendário para este dia
                    # Ajusta nomes de campos se o modelo CalendarioAula for diferente.
                    aula = CalendarioAula(
                        livro_id=livro.id,
                        turma_id=turma.id,
                        periodo_id=periodo.id,
                        data=data_atual,
                        modulo_id=modulo_usado.id,
                        numero_modulo=numero_modulo_no_fim,
                        total_geral=contador_sumario_global,
                        sumarios=",".join(str(n) for n in sumarios_hoje),
                        tipo="normal",
                    )
                    db.session.add(aula)

                data_atual += timedelta(days=1)

        db.session.commit()
