import csv
import io
import json
from datetime import datetime, date, timedelta

from flask import (
    Flask,
    render_template,
    redirect,
    url_for,
    request,
    flash,
    Response,   # se ainda estiveres a usar o JSON
)

from flask_migrate import Migrate
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from config import Config
from models import (
    db,
    Turma,
    Livro,
    Periodo,
    CalendarioAula,
    Modulo,
    AnoLetivo,
    InterrupcaoLetiva,
    Feriado,
    Horario,
    Exclusao,
    Extra,
    LivroTurma,
    TurmaDisciplina,
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
    exportar_sumarios_json,
    importar_sumarios_json,
)


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


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    Migrate(app, db)

    # ----------------------------------------
    # Helpers internos à app
    # ----------------------------------------
    def _parse_date_form(value):
        """Lê <input type='date'> em formato YYYY-MM-DD."""
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None

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

    # ----------------------------------------
    # DASHBOARD
    # ----------------------------------------
    @app.route("/")
    def dashboard():
        turmas = Turma.query.order_by(Turma.nome).all()
        ano_atual = get_ano_letivo_atual()
        return render_template(
            "dashboard.html",
            turmas=turmas,
            ano_atual=ano_atual,
        )

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

        for turma in livro.turmas:
            garantir_periodos_basicos_para_turma(turma)
            gerar_calendario_turma(turma.id, recalcular_tudo=recalcular_tudo)

        flash("Calendários gerados/atualizados com sucesso.", "success")
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
    @app.route("/turmas")
    def turmas_list():
        turmas = Turma.query.order_by(Turma.nome).all()
        return render_template("turmas/list.html", turmas=turmas)

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
            ano_id = request.form.get("ano_letivo_id", type=int)
            carga_seg = request.form.get("carga_segunda", type=float)
            carga_ter = request.form.get("carga_terca", type=float)
            carga_qua = request.form.get("carga_quarta", type=float)
            carga_qui = request.form.get("carga_quinta", type=float)
            carga_sex = request.form.get("carga_sexta", type=float)
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

            turma.nome = nome
            turma.tipo = tipo
            turma.ano_letivo_id = ano_escolhido.id
            turma.carga_segunda = carga_seg
            turma.carga_terca = carga_ter
            turma.carga_quarta = carga_qua
            turma.carga_quinta = carga_qui
            turma.carga_sexta = carga_sex

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
            ano_id = request.form.get("ano_letivo_id", type=int)
            carga_seg = request.form.get("carga_segunda", type=float)
            carga_ter = request.form.get("carga_terca", type=float)
            carga_qua = request.form.get("carga_quarta", type=float)
            carga_qui = request.form.get("carga_quinta", type=float)
            carga_sex = request.form.get("carga_sexta", type=float)
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

            turma = Turma(
                nome=nome,
                tipo=tipo,
                ano_letivo_id=ano_escolhido.id,
                carga_segunda=carga_seg,
                carga_terca=carga_ter,
                carga_quarta=carga_qua,
                carga_quinta=carga_qui,
                carga_sexta=carga_sex,
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

    @app.route("/turmas/<int:turma_id>/calendario")
    def turma_calendario(turma_id):
        turma = Turma.query.get_or_404(turma_id)
        ano = turma.ano_letivo
        ano_fechado = bool(ano and ano.fechado)

        periodos_disponiveis = (
            Periodo.query
            .filter_by(turma_id=turma.id)
            .order_by(Periodo.data_inicio)
            .all()
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

        return render_template(
            "turmas/calendario.html",
            turma=turma,
            ano=ano,
            ano_fechado=ano_fechado,
            aulas=aulas,
            periodo_atual=periodo_atual,
            periodos_disponiveis=periodos_disponiveis,
            tipos_sem_aula=DEFAULT_TIPOS_SEM_AULA,
            tipos_aula=TIPOS_AULA,
        )

    @app.route("/calendario/dia")
    @app.route("/turmas/<int:turma_id>/calendario/dia")
    def turma_calendario_dia(turma_id=None):
        todas_turmas = Turma.query.order_by(Turma.nome).all()

        turma_id_param = request.args.get("turma_id", type=int)
        turma_selecionada = None
        if turma_id_param:
            turma_selecionada = Turma.query.get(turma_id_param)
        elif turma_id:
            turma_selecionada = Turma.query.get_or_404(turma_id)

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

        anos_fechados = {
            a.turma_id: bool(a.turma and a.turma.ano_letivo and a.turma.ano_letivo.fechado)
            for a in aulas
            if a.turma_id
        }

        return render_template(
            "turmas/calendario_diario.html",
            turma=turma_selecionada,
            aulas=aulas,
            data_atual=data_atual,
            dia_anterior=data_atual - timedelta(days=1),
            dia_seguinte=data_atual + timedelta(days=1),
            tipos_sem_aula=DEFAULT_TIPOS_SEM_AULA,
            tipos_aula=TIPOS_AULA,
            turmas=todas_turmas,
            anos_fechados=anos_fechados,
        )

    @app.route("/calendario/outras-datas")
    def calendario_outras_datas():
        tipo_filtro = request.args.get("tipo") or None
        turma_filtro = request.args.get("turma_id", type=int)
        data_inicio = _parse_date_form(request.args.get("data_inicio"))
        data_fim = _parse_date_form(request.args.get("data_fim"))

        tipos_validos = set(TIPOS_ESPECIAIS)
        if tipo_filtro not in tipos_validos:
            tipo_filtro = None

        turmas = Turma.query.order_by(Turma.nome).all()

        query = (
            CalendarioAula.query.options(
                joinedload(CalendarioAula.turma),
                joinedload(CalendarioAula.modulo),
            )
            .filter(CalendarioAula.apagado == False)  # noqa: E712
            .filter(CalendarioAula.tipo.in_(TIPOS_ESPECIAIS))
            .join(Turma)
        )

        if turma_filtro:
            query = query.filter(CalendarioAula.turma_id == turma_filtro)
        if tipo_filtro:
            query = query.filter(CalendarioAula.tipo == tipo_filtro)
        if data_inicio:
            query = query.filter(CalendarioAula.data >= data_inicio)
        if data_fim:
            query = query.filter(CalendarioAula.data <= data_fim)

        aulas = (
            query.order_by(
                CalendarioAula.data.desc(),
                Turma.nome.asc(),
                CalendarioAula.id.desc(),
            )
            .all()
        )

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
        )

    @app.route("/calendario/outras-datas/add", methods=["POST"])
    def calendario_outras_datas_add():
        turma_id = request.form.get("turma_id", type=int)
        data_txt = request.form.get("data")
        data_aula = _parse_date_form(data_txt)
        numero_aulas = request.form.get("numero_aulas", type=int) or 1
        sumario_txt = request.form.get("sumario")
        observacoes_txt = request.form.get("observacoes")

        filtros = {
            "tipo": request.form.get("tipo_filtro") or None,
            "turma_id": request.form.get("turma_filtro", type=int) or turma_id,
            "data_inicio": request.form.get("data_inicio") or None,
            "data_fim": request.form.get("data_fim") or None,
        }
        filtros_limpos = {k: v for k, v in filtros.items() if v}

        if not turma_id:
            flash("Seleciona a turma para adicionar a aula extra.", "error")
            return redirect(url_for("calendario_outras_datas", **filtros_limpos))

        turma = Turma.query.get_or_404(turma_id)
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
                observacoes=observacoes_txt,
            )
            renumerar_calendario_turma(turma.id)
            flash("Aula extra adicionada e numeração recalculada.", "success")
        except ValueError as exc:
            flash(str(exc), "error")

        return redirect(url_for("calendario_outras_datas", **filtros_limpos))

    @app.route("/calendario/outras-datas/mudar-tipo", methods=["POST"])
    def calendario_outras_datas_mudar_tipo():
        data_txt = request.form.get("data")
        novo_tipo = request.form.get("novo_tipo")

        filtros = {
            "tipo": request.form.get("tipo_filtro") or None,
            "turma_id": request.form.get("turma_filtro", type=int) or None,
            "data_inicio": request.form.get("data_inicio") or None,
            "data_fim": request.form.get("data_fim") or None,
        }
        filtros_limpos = {k: v for k, v in filtros.items() if v}

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

    @app.route("/turmas/<int:turma_id>/calendario/export/json")
    def turma_calendario_export_json(turma_id):
        turma = Turma.query.get_or_404(turma_id)
        periodo_id = request.args.get("periodo_id", type=int)

        dados = exportar_sumarios_json(turma.id, periodo_id=periodo_id)
        payload = json.dumps(
            {
                "turma": {"id": turma.id, "nome": turma.nome},
                "aulas": dados,
            },
            ensure_ascii=False,
            indent=2,
        )

        data_export = date.today().isoformat()
        filename = f"calendario_{turma.nome}_sumarios_{data_export}.json"
        response = Response(payload, mimetype="application/json; charset=utf-8")
        response.headers["Content-Disposition"] = f"attachment; filename={filename}"
        return response

    @app.route("/turmas/<int:turma_id>/calendario/export/csv")
    def turma_calendario_export_csv(turma_id):
        turma = Turma.query.get_or_404(turma_id)
        periodo_id = request.args.get("periodo_id", type=int)

        dados = exportar_sumarios_json(turma.id, periodo_id=periodo_id)
        linhas_validas = [
            linha for linha in dados if (linha.get("tipo") or "").lower() in {"normal", "extra"}
        ]

        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=";")
        writer.writerow(["DATA", "MÓDULO", "N.º Sumário", "Sumário"])
        for linha in linhas_validas:
            data_txt = linha.get("data")
            data_legivel = ""
            try:
                data_legivel = datetime.fromisoformat(data_txt).strftime("%d/%m/%Y") if data_txt else ""
            except ValueError:
                data_legivel = data_txt or ""

            writer.writerow(
                [
                    data_legivel,
                    linha.get("modulo_nome") or "",
                    linha.get("sumarios") or "",
                    linha.get("sumario") or "",
                ]
            )

        payload = "\ufeff" + buf.getvalue()
        data_export = date.today().isoformat()
        filename = f"calendario_{turma.nome}_sumarios_{data_export}.csv"
        response = Response(payload, mimetype="text/csv; charset=utf-8")
        response.headers["Content-Disposition"] = f"attachment; filename={filename}"
        return response

    @app.route("/turmas/<int:turma_id>/calendario/import/json", methods=["POST"])
    def turma_calendario_import_json(turma_id):
        turma = Turma.query.get_or_404(turma_id)
        ano = turma.ano_letivo
        if ano and ano.fechado:
            flash("Ano letivo fechado: não é possível editar o calendário.", "error")
            return redirect(url_for("turma_calendario", turma_id=turma.id))

        ficheiro = request.files.get("ficheiro")
        conteudo = request.form.get("conteudo")
        bruto: str | None = None

        if ficheiro and ficheiro.filename:
            bruto = ficheiro.read().decode("utf-8", errors="ignore")
        elif conteudo:
            bruto = conteudo

        if not bruto:
            flash("Seleciona um ficheiro JSON para importar.", "error")
            return redirect(url_for("turma_calendario", turma_id=turma.id))

        try:
            payload = json.loads(bruto)
        except ValueError:
            flash("Ficheiro JSON inválido.", "error")
            return redirect(url_for("turma_calendario", turma_id=turma.id))

        if isinstance(payload, dict) and "aulas" in payload:
            linhas = payload.get("aulas") or []
        elif isinstance(payload, list):
            linhas = payload
        else:
            flash("Formato de backup desconhecido: esperado array JSON de aulas.", "error")
            return redirect(url_for("turma_calendario", turma_id=turma.id))

        contadores = importar_sumarios_json(turma, linhas)
        renumerar_calendario_turma(turma.id)

        flash(
            "Importação concluída: "
            f"{contadores['criados']} criadas, "
            f"{contadores['atualizados']} atualizadas, "
            f"{contadores['ignorados']} ignoradas.",
            "success",
        )

        return redirect(url_for("turma_calendario", turma_id=turma.id))

    @app.route("/turmas/<int:turma_id>/calendario/gerar", methods=["POST"])
    def turma_calendario_gerar(turma_id):
        turma = Turma.query.get_or_404(turma_id)
        ano = turma.ano_letivo
        if ano and ano.fechado:
            flash("Ano letivo fechado: não é possível gerar calendário.", "error")
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

    @app.route("/turmas/<int:turma_id>/calendario/add", methods=["GET", "POST"])
    def calendario_add(turma_id):
        turma = Turma.query.get_or_404(turma_id)
        ano = turma.ano_letivo
        if ano and ano.fechado:
            flash("Ano letivo fechado: não é possível editar o calendário.", "error")
            return redirect(url_for("turma_calendario", turma_id=turma.id))

        periodo_id = request.args.get("periodo_id", type=int)

        if not periodo_id:
            flash("É necessário escolher um período para adicionar linhas.", "error")
            return redirect(url_for("turma_calendario", turma_id=turma.id))

        periodo = Periodo.query.get_or_404(periodo_id)

        # módulos disponíveis para esta turma
        modulos = garantir_modulos_para_turma(turma)
        if not modulos:
            flash("Cria módulos com carga horária antes de adicionar linhas.", "error")
            return redirect(url_for("turma_calendario", turma_id=turma.id))

        if request.method == "POST":
            data = _parse_date_form(request.form.get("data"))
            modulo_id = request.form.get("modulo_id", type=int)
            numero_modulo = request.form.get("numero_modulo", type=int)
            total_geral = request.form.get("total_geral", type=int)
            sumarios_txt = (request.form.get("sumarios") or "").strip()
            sumario_txt = (request.form.get("sumario") or "").strip()
            tipo = request.form.get("tipo") or "normal"

            if not data or not modulo_id:
                flash("Data e Módulo são obrigatórios.", "error")
                return render_template(
                    "turmas/calendario_form.html",
                    titulo="Nova linha de calendário",
                    turma=turma,
                    periodo=periodo,
                    modulos=modulos,
                    aula=None,
                    tipos_aula=TIPOS_AULA,
                )

            aula = CalendarioAula(
                turma_id=turma.id,
                periodo_id=periodo.id,
                data=data,
                modulo_id=modulo_id,
                numero_modulo=numero_modulo,
                total_geral=total_geral,
                sumarios=sumarios_txt,
                sumario=sumario_txt,
                tipo=tipo,
            )
            db.session.add(aula)
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
                    "Linha de calendário criada e "
                    f"{novas} aula(s) adicionadas para cumprir o total do módulo.",
                    "success",
                )
            else:
                flash("Linha de calendário criada.", "success")
            return redirect(
                url_for(
                    "turma_calendario",
                    turma_id=turma.id,
                    periodo_id=periodo.id,
                )
            )

        return render_template(
            "turmas/calendario_form.html",
            titulo="Nova linha de calendário",
            turma=turma,
            periodo=periodo,
            modulos=modulos,
            aula=None,
            tipos_aula=TIPOS_AULA,
        )


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

        periodo = Periodo.query.get_or_404(aula.periodo_id)
        redirect_view = request.values.get("view")
        data_ref = request.values.get("data_ref")

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
            tipo = request.form.get("tipo") or "normal"

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
                )

            aula.data = data
            aula.modulo_id = modulo_id
            aula.numero_modulo = numero_modulo
            aula.total_geral = total_geral
            aula.sumarios = sumarios_txt
            aula.sumario = sumario_txt
            aula.tipo = tipo

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
                return redirect(
                    url_for("turma_calendario_dia", turma_id=turma.id, data=data_ref)
                )
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

        return redirect(url_for("turma_calendario", turma_id=turma.id))

    # ----------------------------------------
    # CALENDÁRIO – SUMÁRIOS EM LINHA
    # ----------------------------------------
    @app.route(
        "/turmas/<int:turma_id>/calendario/<int:aula_id>/sumario",
        methods=["POST"],
    )
    def calendario_update_sumario(turma_id, aula_id):
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

        sumario_txt = request.form.get("sumario")
        if sumario_txt is not None:
            aula.sumario = sumario_txt.strip()

        observacoes_txt = request.form.get("observacoes")
        if observacoes_txt is not None:
            aula.observacoes = observacoes_txt.strip()

        tipo_original = aula.tipo
        novo_tipo_raw = request.form.get("tipo")
        novo_tipo = (novo_tipo_raw if novo_tipo_raw is not None else aula.tipo) or "normal"
        if isinstance(novo_tipo, str):
            novo_tipo = novo_tipo.strip()
        aula.tipo = novo_tipo

        db.session.commit()

        if novo_tipo != tipo_original:
            renumerar_calendario_turma(turma.id)
            novas = completar_modulos_profissionais(
                turma.id,
                data_removida=aula.data,
                modulo_removido_id=aula.modulo_id,
            )
            if novas:
                renumerar_calendario_turma(turma.id)
                flash(
                    "Tipo de aula atualizado e "
                    f"{novas} aula(s) adicionadas para cumprir o total do módulo.",
                    "success",
                )
            else:
                flash("Sumário e tipo atualizados.", "success")
        else:
            flash("Sumário atualizado.", "success")

        periodo_id = request.form.get("periodo_id", type=int)
        redirect_view = request.form.get("view")
        data_ref = request.form.get("data_ref")

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
            return redirect(
                url_for("turma_calendario_dia", turma_id=turma.id, data=data_ref)
            )

        return redirect(
            url_for("turma_calendario", turma_id=turma.id, periodo_id=periodo_id)
        )

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
    @app.route("/calendario-escolar")
    def calendario_escolar():
        ano = get_ano_letivo_atual()
        if not ano:
            flash("Ainda não existe Ano Letivo definido.", "error")
            return redirect(url_for("dashboard"))

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
            return redirect(url_for("dashboard"))

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
            "calendario/gestao.html",
            ano=ano,
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
    app.run(debug=True)
