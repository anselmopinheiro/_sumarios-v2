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
    TurmaDisciplina,
    LivroTurma,
)

from calendario_service import gerar_calendarios, expand_dates
from calendario_service import garantir_periodos_basicos_para_turma


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
        livros = Livro.query.order_by(Livro.nome).all()
        turmas = Turma.query.order_by(Turma.nome).all()
        ano_atual = get_ano_letivo_atual()
        return render_template(
            "dashboard.html",
            livros=livros,
            turmas=turmas,
            ano_atual=ano_atual,
        )

    # ----------------------------------------
    # LIVROS
    # ----------------------------------------
    @app.route("/livros")
    def livros_list():
        # Se quiseres filtrar por ano letivo ativo:
        ano_atual = AnoLetivo.query.filter_by(ativo=True).first()
        if ano_atual:
            livros = Livro.query.filter(
                (Livro.ano_letivo_id == None) | (Livro.ano_letivo_id == ano_atual.id)
            ).order_by(Livro.nome).all()
        else:
            livros = Livro.query.order_by(Livro.nome).all()

        return render_template("livros/list.html", livros=livros, ano_atual=ano_atual)

    @app.route("/livros/add", methods=["GET", "POST"])
    def livros_add():
        ano_atual = AnoLetivo.query.filter_by(ativo=True).first()

        if request.method == "POST":
            nome = (request.form.get("nome") or "").strip()
            sigla = (request.form.get("sigla") or "").strip()

            if not nome:
                flash("O nome da disciplina é obrigatório.", "error")
                return render_template("livros/form.html", titulo="Novo livro (disciplina)", ano_atual=ano_atual)

            livro = Livro(
                nome=nome,
                sigla=sigla or None,
                ano_letivo_id=ano_atual.id if ano_atual else None,
            )
            db.session.add(livro)
            db.session.commit()

            flash("Livro (disciplina) criado com sucesso.", "success")
            return redirect(url_for("livros_list"))

        return render_template("livros/form.html", titulo="Novo livro (disciplina)", ano_atual=ano_atual)

    @app.route("/livros/<int:livro_id>")
    def livros_detail(livro_id):
        livro = Livro.query.get_or_404(livro_id)
        return render_template("livros/detail.html", livro=livro)

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

        gerar_calendarios(livro.id, recalcular_tudo=recalcular_tudo)
        flash("Calendários gerados/atualizados com sucesso.", "success")
        return redirect(url_for("livros_detail", livro_id=livro.id))
    @app.route("/livros/<int:livro_id>/edit", methods=["GET", "POST"])
    def livros_edit(livro_id):
        livro = Livro.query.get_or_404(livro_id)
        ano_atual = AnoLetivo.query.filter_by(ativo=True).first()

        # Turmas disponíveis para associação (por ano letivo atual, se existir)
        if ano_atual:
            turmas_disponiveis = Turma.query.filter_by(ano_letivo_id=ano_atual.id).order_by(Turma.nome).all()
        else:
            turmas_disponiveis = Turma.query.order_by(Turma.nome).all()

        if request.method == "POST":
            nome = (request.form.get("nome") or "").strip()
            sigla = (request.form.get("sigla") or "").strip()
            turmas_ids = request.form.getlist("turmas")  # lista de ids em string

            if not nome:
                flash("O nome da disciplina é obrigatório.", "error")
                return render_template(
                    "livros/form.html",
                    titulo="Editar livro (disciplina)",
                    livro=livro,
                    ano_atual=ano_atual,
                    turmas_disponiveis=turmas_disponiveis,
                )

            livro.nome = nome
            livro.sigla = sigla or None
            if ano_atual:
                livro.ano_letivo_id = ano_atual.id

            # atualizar associação às turmas
            novas_turmas = []
            for tid in turmas_ids:
                t = Turma.query.get(int(tid))
                if t:
                    novas_turmas.append(t)
            livro.turmas = novas_turmas

            db.session.commit()
            flash("Livro (disciplina) atualizado com sucesso.", "success")
            return redirect(url_for("livros_list"))

        return render_template(
            "livros/form.html",
            titulo="Editar livro (disciplina)",
            livro=livro,
            ano_atual=ano_atual,
            turmas_disponiveis=turmas_disponiveis,
        )
    @app.route("/livros/<int:livro_id>/delete", methods=["POST"])
    def livros_delete(livro_id):
        livro = Livro.query.get_or_404(livro_id)

        # Opcional: impedir apagamento se já tiver calendários gerados
        calendarios = CalendarioAula.query.filter_by(livro_id=livro.id).first()
        if calendarios:
            flash("Não é possível apagar este livro: já existem calendários associados.", "error")
            return redirect(url_for("livros_list"))

        db.session.delete(livro)
        db.session.commit()
        flash("Livro (disciplina) apagado.", "success")
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

        if request.method == "POST":
            nome = (request.form.get("nome") or "").strip()
            tipo = request.form.get("tipo") or turma.tipo
            carga_seg = request.form.get("carga_segunda", type=float)
            carga_ter = request.form.get("carga_terca", type=float)
            carga_qua = request.form.get("carga_quarta", type=float)
            carga_qui = request.form.get("carga_quinta", type=float)
            carga_sex = request.form.get("carga_sexta", type=float)

            if not nome:
                flash("O nome da turma é obrigatório.", "error")
                return render_template(
                    "turmas/form.html",
                    titulo="Editar Turma",
                    turma=turma,
                    ano_atual=ano_atual,
                )

            turma.nome = nome
            turma.tipo = tipo
            turma.carga_segunda = carga_seg
            turma.carga_terca = carga_ter
            turma.carga_quarta = carga_qua
            turma.carga_quinta = carga_qui
            turma.carga_sexta = carga_sex

            db.session.commit()
            garantir_periodos_basicos_para_turma(turma)
            flash("Turma atualizada.", "success")
            return redirect(url_for("turmas_list"))

        return render_template(
            "turmas/form.html",
            titulo="Editar Turma",
            turma=turma,
            ano_atual=ano_atual,
        )

    @app.route("/turmas/add", methods=["GET", "POST"])
    def turmas_add():
        # usar sempre o ano letivo atual
        ano_atual = get_ano_letivo_atual()
        if not ano_atual or ano_atual.fechado:
            flash("Não há Ano Letivo ativo e aberto para criar turmas.", "error")
            return redirect(url_for("anos_letivos_list"))

        if request.method == "POST":
            nome = (request.form.get("nome") or "").strip()
            tipo = request.form.get("tipo") or "regular"
            carga_seg = request.form.get("carga_segunda", type=float)
            carga_ter = request.form.get("carga_terca", type=float)
            carga_qua = request.form.get("carga_quarta", type=float)
            carga_qui = request.form.get("carga_quinta", type=float)
            carga_sex = request.form.get("carga_sexta", type=float)

            if not nome:
                flash("O nome da turma é obrigatório.", "error")
                return render_template(
                    "turmas/form.html",
                    titulo="Nova Turma",
                    turma=None,
                    ano_atual=ano_atual,
                )

            turma = Turma(
                nome=nome,
                tipo=tipo,
                ano_letivo_id=ano_atual.id,
                carga_segunda=carga_seg,
                carga_terca=carga_ter,
                carga_quarta=carga_qua,
                carga_quinta=carga_qui,
                carga_sexta=carga_sex,
            )

            db.session.add(turma)
            db.session.commit()
            
            # Gera automaticamente Anual / 1.º / 2.º semestre para esta turma
            garantir_periodos_basicos_para_turma(turma)
            flash(f"Turma criada no ano letivo {ano_atual.nome}.", "success")
            return redirect(url_for("turmas_list"))

        return render_template(
            "turmas/form.html",
            titulo="Nova Turma",
            turma=None,
            ano_atual=ano_atual,
        )

    @app.route("/turmas/<int:turma_id>/calendario")
    def turma_calendario(turma_id):
        turma = Turma.query.get_or_404(turma_id)
        ano = turma.ano_letivo
        ano_fechado = bool(ano and ano.fechado)

        livros_disponiveis = turma.livros
        livro_id = request.args.get("livro_id", type=int)
        periodo_id = request.args.get("periodo_id", type=int)

        livro_atual = None
        if livro_id:
            livro_atual = Livro.query.get(livro_id)
        elif livros_disponiveis:
            livro_atual = livros_disponiveis[0]

        periodos_disponiveis = (
            Periodo.query
            .filter_by(turma_id=turma.id)
            .order_by(Periodo.data_inicio)
            .all()      
        )

        periodo_atual = None
        if periodo_id:
            periodo_atual = Periodo.query.get(periodo_id)
        elif periodos_disponiveis:
            periodo_atual = periodos_disponiveis[0]

        aulas = []
        if livro_atual and periodo_atual:
            aulas = (
                CalendarioAula.query
                .filter_by(
                    livro_id=livro_atual.id,
                    turma_id=turma.id,
                    periodo_id=periodo_atual.id,
                )
                .order_by(CalendarioAula.data)
                .all()
            )

        return render_template(
            "turmas/calendario.html",
            turma=turma,
            ano=ano,
            ano_fechado=ano_fechado,
            aulas=aulas,
            livro_atual=livro_atual,
            periodo_atual=periodo_atual,
            livros_disponiveis=livros_disponiveis,
            periodos_disponiveis=periodos_disponiveis,
        )

        turma = Turma.query.get_or_404(turma_id)
        ano = turma.ano_letivo
        ano_fechado = bool(ano and ano.fechado)

        # Livros associados à turma
        livros_disponiveis = turma.livros  # relação many-to-many ou similar
        livro_id = request.args.get("livro_id", type=int)
        periodo_id = request.args.get("periodo_id", type=int)

        # Escolher livro atual
        livro_atual = None
        if livro_id:
            livro_atual = Livro.query.get(livro_id)
        elif livros_disponiveis:
            livro_atual = livros_disponiveis[0]

        # Periodos da turma
        periodos_disponiveis = (
            Periodo.query
            .filter_by(turma_id=turma.id)
            .order_by(Periodo.data_inicio)
            .all()
        )

        periodo_atual = None
        if periodo_id:
            periodo_atual = Periodo.query.get(periodo_id)
        elif periodos_disponiveis:
            periodo_atual = periodos_disponiveis[0]

        aulas = []
        if livro_atual and periodo_atual:
            aulas = (
                CalendarioAula.query
                .filter_by(
                    livro_id=livro_atual.id,
                    turma_id=turma.id,
                    periodo_id=periodo_atual.id,
                )
                .order_by(CalendarioAula.data)
                .all()
            )

        return render_template(
            "turmas/calendario.html",
            turma=turma,
            ano=ano,
            ano_fechado=ano_fechado,
            aulas=aulas,
            livro_atual=livro_atual,
            periodo_atual=periodo_atual,
            livros_disponiveis=livros_disponiveis,
            periodos_disponiveis=periodos_disponiveis,
        )

    @app.route("/turmas/<int:turma_id>/calendario/add", methods=["GET", "POST"])
    def calendario_add(turma_id):
        turma = Turma.query.get_or_404(turma_id)
        ano = turma.ano_letivo
        if ano and ano.fechado:
            flash("Ano letivo fechado: não é possível editar o calendário.", "error")
            return redirect(url_for("turma_calendario", turma_id=turma.id))

        livro_id = request.args.get("livro_id", type=int)
        periodo_id = request.args.get("periodo_id", type=int)

        if not livro_id or not periodo_id:
            flash("É necessário escolher Livro e Período para adicionar linhas.", "error")
            return redirect(url_for("turma_calendario", turma_id=turma.id))

        livro = Livro.query.get_or_404(livro_id)
        periodo = Periodo.query.get_or_404(periodo_id)

        # módulos disponíveis para esta turma + livro
        modulos = (
            Modulo.query
            .filter_by(turma_id=turma.id, livro_id=livro.id)
            .order_by(Modulo.id)
            .all()
        )

        if request.method == "POST":
            data = _parse_date_form(request.form.get("data"))
            modulo_id = request.form.get("modulo_id", type=int)
            numero_modulo = request.form.get("numero_modulo", type=int)
            total_geral = request.form.get("total_geral", type=int)
            sumarios_txt = (request.form.get("sumarios") or "").strip()
            tipo = request.form.get("tipo") or "normal"

            if not data or not modulo_id:
                flash("Data e Módulo são obrigatórios.", "error")
                return render_template(
                    "turmas/calendario_form.html",
                    titulo="Nova linha de calendário",
                    turma=turma,
                    livro=livro,
                    periodo=periodo,
                    modulos=modulos,
                    aula=None,
                )

            aula = CalendarioAula(
                livro_id=livro.id,
                turma_id=turma.id,
                periodo_id=periodo.id,
                data=data,
                modulo_id=modulo_id,
                numero_modulo=numero_modulo,
                total_geral=total_geral,
                sumarios=sumarios_txt,
                tipo=tipo,
            )
            db.session.add(aula)
            db.session.commit()
            flash("Linha de calendário criada.", "success")
            return redirect(
                url_for(
                    "turma_calendario",
                    turma_id=turma.id,
                    livro_id=livro.id,
                    periodo_id=periodo.id,
                )
            )

        return render_template(
            "turmas/calendario_form.html",
            titulo="Nova linha de calendário",
            turma=turma,
            livro=livro,
            periodo=periodo,
            modulos=modulos,
            aula=None,
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



        turma = Turma.query.get_or_404(turma_id)

        livro_id = request.args.get("livro_id", type=int)
        periodo_id = request.args.get("periodo_id", type=int)

        if not livro_id:
            livro = turma.livros[0] if turma.livros else None
            if not livro:
                flash("Esta turma não tem nenhum livro associado.", "error")
                return redirect(url_for("turmas_list"))
            livro_id = livro.id

        if not periodo_id:
            periodo = (
                Periodo.query
                .filter_by(turma_id=turma.id)
                .order_by(Periodo.data_inicio)
                .first()
            )
            if not periodo:
                flash("Esta turma não tem períodos configurados.", "error")
                return redirect(url_for("turmas_list"))
            periodo_id = periodo.id

        aulas = (
            CalendarioAula.query
            .filter_by(livro_id=livro_id, turma_id=turma.id, periodo_id=periodo_id)
            .order_by(CalendarioAula.data)
            .all()
        )

        return render_template(
            "turmas/calendario.html",
            turma=turma,
            aulas=aulas,
            livro_id=livro_id,
            periodo_id=periodo_id,
        )
    @app.route("/turmas/<int:turma_id>/calendario/<int:aula_id>/edit", methods=["GET", "POST"])
    def calendario_edit(turma_id, aula_id):
        turma = Turma.query.get_or_404(turma_id)
        ano = turma.ano_letivo
        if ano and ano.fechado:
            flash("Ano letivo fechado: não é possível editar o calendário.", "error")
            return redirect(url_for("turma_calendario", turma_id=turma.id))

        aula = CalendarioAula.query.get_or_404(aula_id)
        if aula.turma_id != turma.id:
            flash("Linha de calendário não pertence a esta turma.", "error")
            return redirect(url_for("turma_calendario", turma_id=turma.id))

        livro = Livro.query.get_or_404(aula.livro_id)
        periodo = Periodo.query.get_or_404(aula.periodo_id)

        modulos = (
            Modulo.query
            .filter_by(turma_id=turma.id, livro_id=livro.id)
            .order_by(Modulo.id)
            .all()
        )

        if request.method == "POST":
            data = _parse_date_form(request.form.get("data"))
            modulo_id = request.form.get("modulo_id", type=int)
            numero_modulo = request.form.get("numero_modulo", type=int)
            total_geral = request.form.get("total_geral", type=int)
            sumarios_txt = (request.form.get("sumarios") or "").strip()
            tipo = request.form.get("tipo") or "normal"

            if not data or not modulo_id:
                flash("Data e Módulo são obrigatórios.", "error")
                return render_template(
                    "turmas/calendario_form.html",
                    titulo="Editar linha de calendário",
                    turma=turma,
                    livro=livro,
                    periodo=periodo,
                    modulos=modulos,
                    aula=aula,
                )

            aula.data = data
            aula.modulo_id = modulo_id
            aula.numero_modulo = numero_modulo
            aula.total_geral = total_geral
            aula.sumarios = sumarios_txt
            aula.tipo = tipo

            db.session.commit()
            flash("Linha de calendário atualizada.", "success")
            return redirect(
                url_for(
                    "turma_calendario",
                    turma_id=turma.id,
                    livro_id=livro.id,
                    periodo_id=periodo.id,
                )
            )

        return render_template(
            "turmas/calendario_form.html",
            titulo="Editar linha de calendário",
            turma=turma,
            livro=livro,
            periodo=periodo,
            modulos=modulos,
            aula=aula,
        )

    @app.route("/turmas/<int:turma_id>/calendario/<int:aula_id>/delete", methods=["POST"])
    def calendario_delete(turma_id, aula_id):
        turma = Turma.query.get_or_404(turma_id)
        ano = turma.ano_letivo
        if ano and ano.fechado:
            flash("Ano letivo fechado: não é possível editar o calendário.", "error")
            return redirect(url_for("turma_calendario", turma_id=turma.id))

        aula = CalendarioAula.query.get_or_404(aula_id)
        if aula.turma_id != turma.id:
            flash("Linha de calendário não pertence a esta turma.", "error")
            return redirect(url_for("turma_calendario", turma_id=turma.id))

        livro_id = aula.livro_id
        periodo_id = aula.periodo_id

        db.session.delete(aula)
        db.session.commit()
        flash("Linha de calendário apagada.", "success")
        return redirect(
            url_for(
                "turma_calendario",
                turma_id=turma.id,
                livro_id=livro_id,
                periodo_id=periodo_id,
            )
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
