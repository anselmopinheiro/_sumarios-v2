import csv
import io
import json
import os
import shutil
import unicodedata
from collections import defaultdict
from datetime import datetime, date, timedelta

from flask import (
    Flask,
    render_template,
    redirect,
    url_for,
    request,
    flash,
    Response,
    jsonify,
)

from flask_migrate import Migrate
from alembic.script import ScriptDirectory
from sqlalchemy import func, inspect, text
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
    Aluno,
    AulaAluno,
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
    importar_calendarios_json,
    importar_calendario_escolar_json,
    exportar_outras_datas_json,
    importar_outras_datas_json,
    listar_aulas_especiais,
    calcular_mapa_avaliacao_diaria,
    listar_sumarios_pendentes,
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


def _total_previsto_ui(sumarios_txt, tempos_sem_aula):
    sumarios_limpos = [s.strip() for s in (sumarios_txt or "").split(",") if s.strip()]
    base = len(sumarios_limpos) if sumarios_limpos else 1
    if tempos_sem_aula:
        try:
            base = max(base, int(tempos_sem_aula))
        except (TypeError, ValueError):
            pass
    return max(base, 1)


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


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    Migrate(app, db)

    os.makedirs(app.instance_path, exist_ok=True)
    export_options_path = os.path.join(app.instance_path, "export_options.json")

    def _default_csv_dir():
        return app.config.get("CSV_EXPORT_DIR") or os.path.join(app.root_path, "exports")

    def _load_export_options():
        options = {"csv_dest_dir": _default_csv_dir()}

        try:
            with open(export_options_path, "r", encoding="utf-8") as handle:
                stored = json.load(handle)
                if isinstance(stored, dict) and stored.get("csv_dest_dir"):
                    options["csv_dest_dir"] = stored["csv_dest_dir"]
        except FileNotFoundError:
            pass
        except (OSError, json.JSONDecodeError) as exc:
            app.logger.warning("Não foi possível ler opções de exportação: %s", exc)

        app.config["CSV_EXPORT_DIR"] = options["csv_dest_dir"] or _default_csv_dir()
        return options

    def _save_export_options(csv_dest_dir):
        try:
            os.makedirs(os.path.dirname(export_options_path), exist_ok=True)
            with open(export_options_path, "w", encoding="utf-8") as handle:
                json.dump({"csv_dest_dir": csv_dest_dir}, handle, ensure_ascii=False, indent=2)
        except OSError as exc:
            app.logger.warning("Não foi possível gravar opções de exportação: %s", exc)

    _load_export_options()

    # Garantir que colunas recentes existem em instalações que ainda não
    # aplicaram as migrações correspondentes (evita erros em bases de dados
    # antigas carregadas a partir de ficheiro).
    def _ensure_columns():
        insp = inspect(db.engine)
        tabelas = set(insp.get_table_names())

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
                        CONSTRAINT fk_aula FOREIGN KEY(aula_id) REFERENCES calendario_aulas(id),
                        CONSTRAINT fk_aluno FOREIGN KEY(aluno_id) REFERENCES alunos(id),
                        CONSTRAINT uq_aula_aluno UNIQUE(aula_id, aluno_id)
                    )
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

    def _backup_database():
        uri = app.config.get("SQLALCHEMY_DATABASE_URI")
        backup_dir = app.config.get("BACKUP_DIR")

        if not uri or not backup_dir:
            return

        if uri.startswith("sqlite:///"):
            db_path = uri.replace("sqlite:///", "", 1)
        else:
            return

        if not os.path.isfile(db_path):
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name, ext = os.path.splitext(os.path.basename(db_path))
        backup_name = f"{base_name}_{timestamp}{ext or '.db'}"

        try:
            os.makedirs(backup_dir, exist_ok=True)
            shutil.copy2(db_path, os.path.join(backup_dir, backup_name))
        except OSError as exc:
            app.logger.warning(
                "Não foi possível criar backup da base de dados em %s: %s",
                backup_dir,
                exc,
            )

    with app.app_context():
        _ensure_columns()
        _backup_database()

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

    # ----------------------------------------
    # DASHBOARD
    # ----------------------------------------
    @app.route("/")
    def dashboard():
        turmas = turmas_abertas_ativas()
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

        return render_template(
            "turmas/list.html",
            turmas_abertas=turmas_abertas,
            turmas_fechadas=turmas_fechadas,
            csv_dest_dir=app.config.get("CSV_EXPORT_DIR"),
        )

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

        _save_export_options(csv_dest_dir)
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
                        linha.get("sumarios") or "",
                        linha.get("sumario") or "",
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
            nome_curto = (request.form.get("nome_curto") or "").strip()
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
                nome_curto=nome_curto or None,
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
        nome_curto = (request.form.get("nome_curto") or "").strip()
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
        aluno.nome_curto = nome_curto or None
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
            nome_curto = _valor("nome_curto").strip() or None
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

    @app.route("/turmas/<int:turma_id>/calendario")
    def turma_calendario(turma_id):
        turma = Turma.query.get_or_404(turma_id)
        ano = turma.ano_letivo
        ano_fechado = bool(ano and ano.fechado)

        periodos_disponiveis = filtrar_periodos_para_turma(
            turma,
            (
                Periodo.query
                .filter_by(turma_id=turma.id)
                .order_by(Periodo.data_inicio)
                .all()
            ),
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
            periodo_atual=periodo_atual,
            periodos_disponiveis=periodos_disponiveis,
            calendario_existe=calendario_existe,
            tipos_sem_aula=DEFAULT_TIPOS_SEM_AULA,
            tipos_aula=TIPOS_AULA,
            tipo_labels=dict(TIPOS_AULA),
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

        periodos_disponiveis = filtrar_periodos_para_turma(
            turma,
            (
                Periodo.query.filter_by(turma_id=turma.id)
                .order_by(Periodo.data_inicio)
                .all()
            ),
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

        mapa = calcular_mapa_avaliacao_diaria(
            turma,
            alunos,
            data_inicio=data_inicio,
            data_fim=data_fim,
            periodo_id=periodo_atual.id if periodo_atual else None,
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

        periodos_disponiveis = filtrar_periodos_para_turma(
            turma,
            (
                Periodo.query.filter_by(turma_id=turma.id)
                .order_by(Periodo.data_inicio)
                .all()
            ),
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

        mapa = calcular_mapa_avaliacao_diaria(
            turma,
            alunos,
            data_inicio=data_inicio,
            data_fim=data_fim,
            periodo_id=periodo_atual.id if periodo_atual else None,
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
                if media is not None:
                    valores.append(media)
                output.write(f"<td>{_media_formatada(media)}</td>")
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

        return render_template(
            "turmas/calendario_diario.html",
            turma=turma_selecionada,
            periodo_atual=periodo_atual,
            periodos_disponiveis=periodos_disponiveis,
            aulas=aulas,
            faltas_por_aula=faltas_por_aula,
            tempos_por_aula=tempos_por_aula,
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
            tempos_por_aula=tempos_por_aula,
            tipos_sem_aula=DEFAULT_TIPOS_SEM_AULA,
            tipos_aula=TIPOS_AULA,
            tipo_labels=dict(TIPOS_AULA),
            anos_fechados=anos_fechados,
        )

    @app.route("/calendario/sumarios-pendentes")
    def calendario_sumarios_pendentes():
        hoje = date.today()
        turma_id = request.args.get("turma_id", type=int)
        turma_selecionada = Turma.query.get(turma_id) if turma_id else None

        aulas = listar_sumarios_pendentes(hoje, turma_id=turma_id)
        faltas_por_aula = _mapear_alunos_em_falta(aulas)
        anos_fechados = {
            a.turma_id: bool(
                a.turma and a.turma.ano_letivo and a.turma.ano_letivo.fechado
            )
            for a in aulas
            if a.turma_id
        }

        return render_template(
            "turmas/sumarios_pendentes.html",
            hoje=hoje,
            aulas=aulas,
            turmas=turmas_abertas_ativas(),
            turma_selecionada=turma_selecionada,
            faltas_por_aula=faltas_por_aula,
            tipos_sem_aula=DEFAULT_TIPOS_SEM_AULA,
            tipos_aula=TIPOS_AULA,
            tipo_labels=dict(TIPOS_AULA),
            anos_fechados=anos_fechados,
        )


    @app.route("/calendarios/import", methods=["GET", "POST"])
    def calendarios_import():
        turmas = turmas_abertas_ativas()

        if request.method == "POST":
            ficheiro = request.files.get("ficheiro")
            conteudo = request.form.get("conteudo")
            turma_padrao_id = request.form.get("turma_id_padrao", type=int)

            bruto: str | None = None
            if ficheiro and ficheiro.filename:
                bruto = ficheiro.read().decode("utf-8", errors="ignore")
            elif conteudo:
                bruto = conteudo

            if not bruto:
                flash("Seleciona um ficheiro JSON para importar.", "error")
                return redirect(url_for("calendarios_import"))

            try:
                payload = json.loads(bruto)
            except ValueError:
                flash("Ficheiro JSON inválido.", "error")
                return redirect(url_for("calendarios_import"))

            linhas: list[dict] = []

            if isinstance(payload, dict) and "turmas" in payload:
                for bloco in payload.get("turmas") or []:
                    aulas = bloco.get("aulas") or []
                    turma_info = bloco.get("turma") if isinstance(bloco.get("turma"), dict) else {}
                    bloco_turma_id = bloco.get("turma_id") or bloco.get("id") or turma_info.get("id")
                    bloco_turma_nome = bloco.get("turma_nome") or turma_info.get("nome")
                    for aula in aulas:
                        linha = dict(aula)
                        if bloco_turma_id:
                            linha.setdefault("turma_id", bloco_turma_id)
                        if bloco_turma_nome:
                            linha.setdefault("turma_nome", bloco_turma_nome)
                        linhas.append(linha)
            elif isinstance(payload, dict) and "aulas" in payload:
                turma_info = payload.get("turma") if isinstance(payload.get("turma"), dict) else {}
                turma_payload_id = payload.get("turma_id") or turma_info.get("id")
                turma_payload_nome = payload.get("turma_nome") or turma_info.get("nome")
                for aula in payload.get("aulas") or []:
                    linha = dict(aula)
                    if turma_payload_id:
                        linha.setdefault("turma_id", turma_payload_id)
                    if turma_payload_nome:
                        linha.setdefault("turma_nome", turma_payload_nome)
                    linhas.append(linha)
            elif isinstance(payload, list):
                linhas = list(payload)
            else:
                flash(
                    "Formato de backup desconhecido: esperado lista de aulas ou objeto com 'aulas'.",
                    "error",
                )
                return redirect(url_for("calendarios_import"))

            if turma_padrao_id:
                for linha in linhas:
                    if not linha.get("turma_id") and not linha.get("turma_nome"):
                        linha["turma_id"] = turma_padrao_id

            if not linhas:
                flash("Nenhuma linha de calendário encontrada no JSON.", "warning")
                return redirect(url_for("calendarios_import"))

            contadores, turmas_fechadas, turmas_inexistentes, _ = importar_calendarios_json(
                linhas
            )

            flash(
                "Importação concluída: "
                f"{contadores['criados']} criadas, "
                f"{contadores['atualizados']} atualizadas, "
                f"{contadores['ignorados']} ignoradas.",
                "success",
            )

            if turmas_fechadas:
                flash(
                    "Turmas ignoradas por ano letivo fechado: " + ", ".join(turmas_fechadas),
                    "warning",
                )
            if turmas_inexistentes:
                flash(
                    "Turmas não encontradas no ficheiro: " + ", ".join(turmas_inexistentes),
                    "warning",
                )

            return redirect(url_for("calendarios_import"))

        return render_template("calendario_import.html", turmas=turmas)

    @app.route("/calendario/outras-datas")
    def calendario_outras_datas():
        tipo_filtro, turma_filtro, data_inicio, data_fim = _extrair_filtros_outras_datas(
            request.args
        )

        turmas = turmas_abertas_ativas()
        aulas = listar_aulas_especiais(turma_filtro, tipo_filtro, data_inicio, data_fim)
        faltas_por_aula = _mapear_alunos_em_falta(aulas)

        return render_template(
            "turmas/outras_datas.html",
            aulas=aulas,
            faltas_por_aula=faltas_por_aula,
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
                previsao=previsao_txt,
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

    @app.route("/calendario/outras-datas/export/json")
    def calendario_outras_datas_export_json():
        tipo_filtro, turma_filtro, data_inicio, data_fim = _extrair_filtros_outras_datas(
            request.args
        )

        dados = exportar_outras_datas_json(turma_filtro, tipo_filtro, data_inicio, data_fim)
        filtros_meta = _filtros_outras_datas_redirect(
            tipo_filtro, turma_filtro, data_inicio, data_fim
        )

        turma_info = None
        if turma_filtro:
            turma = Turma.query.get(turma_filtro)
            if turma:
                turma_info = {"id": turma.id, "nome": turma.nome}

        payload = json.dumps(
            {
                "exportado_em": date.today().isoformat(),
                "turma": turma_info,
                "filtros": filtros_meta,
                "aulas": dados,
            },
            ensure_ascii=False,
            indent=2,
        )

        filename = f"outras_datas_{date.today().isoformat()}.json"
        response = Response(payload, mimetype="application/json; charset=utf-8")
        response.headers["Content-Disposition"] = f"attachment; filename={filename}"
        return response

    @app.route("/calendario/outras-datas/export/csv")
    def calendario_outras_datas_export_csv():
        tipo_filtro, turma_filtro, data_inicio, data_fim = _extrair_filtros_outras_datas(
            request.args
        )

        dados = exportar_outras_datas_json(turma_filtro, tipo_filtro, data_inicio, data_fim)

        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=";")
        writer.writerow([
            "Turma",
            "Data",
            "Tipo",
            "N.º Sumário",
            "Sumário",
            "Previsão",
            "Observações",
        ])
        for linha in dados:
            data_txt = linha.get("data")
            data_legivel = ""
            try:
                data_legivel = datetime.fromisoformat(data_txt).strftime("%d/%m/%Y") if data_txt else ""
            except ValueError:
                data_legivel = data_txt or ""

            writer.writerow(
                [
                    linha.get("turma_nome") or "",
                    data_legivel,
                    dict(TIPOS_AULA).get(linha.get("tipo"), linha.get("tipo")),
                    linha.get("sumarios") or "",
                    linha.get("sumario") or "",
                    linha.get("previsao") or "",
                    linha.get("observacoes") or "",
                ]
            )

        payload = "\ufeff" + buf.getvalue()
        filename = f"outras_datas_{date.today().isoformat()}.csv"
        response = Response(payload, mimetype="text/csv; charset=utf-8")
        response.headers["Content-Disposition"] = f"attachment; filename={filename}"
        return response

    @app.route("/calendario/outras-datas/import/json", methods=["POST"])
    def calendario_outras_datas_import_json():
        tipo_filtro, turma_filtro, data_inicio, data_fim = _extrair_filtros_outras_datas(
            request.form
        )
        filtros_limpos = _filtros_outras_datas_redirect(
            tipo_filtro, turma_filtro, data_inicio, data_fim
        )

        ficheiro = request.files.get("ficheiro")
        conteudo = request.form.get("conteudo")
        bruto: str | None = None

        if ficheiro and ficheiro.filename:
            bruto = ficheiro.read().decode("utf-8", errors="ignore")
        elif conteudo:
            bruto = conteudo

        if not bruto:
            flash("Seleciona um ficheiro JSON para importar.", "error")
            return redirect(url_for("calendario_outras_datas", **filtros_limpos))

        try:
            payload = json.loads(bruto)
        except ValueError:
            flash("Ficheiro JSON inválido.", "error")
            return redirect(url_for("calendario_outras_datas", **filtros_limpos))

        if isinstance(payload, dict) and "aulas" in payload:
            linhas = payload.get("aulas") or []
        elif isinstance(payload, list):
            linhas = payload
        else:
            flash("Formato de backup desconhecido: esperado array JSON de aulas.", "error")
            return redirect(url_for("calendario_outras_datas", **filtros_limpos))

        contadores, turmas_fechadas, turmas_inexistentes, _ = importar_outras_datas_json(
            linhas
        )

        msg = (
            "Importação concluída: "
            f"{contadores['criados']} criadas, "
            f"{contadores['atualizados']} atualizadas, "
            f"{contadores['ignorados']} ignoradas."
        )
        if turmas_fechadas:
            msg += f" Turmas bloqueadas: {', '.join(sorted(set(turmas_fechadas)))}."
        if turmas_inexistentes:
            msg += f" Turmas não encontradas: {', '.join(sorted(set(turmas_inexistentes)))}."

        flash(msg, "success")
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
            previsao_txt = (request.form.get("previsao") or "").strip()
            tipo = request.form.get("tipo") or "normal"
            tempos_sem_aula = request.form.get("tempos_sem_aula", type=int)

            sumarios_originais = [s.strip() for s in sumarios_txt.split(",") if s.strip()]
            total_previsto = _total_previsto_ui(sumarios_txt, tempos_sem_aula)
            if tempos_sem_aula is None:
                if tipo in DEFAULT_TIPOS_SEM_AULA:
                    tempos_sem_aula = total_previsto
                else:
                    tempos_sem_aula = 0
            tempos_sem_aula = max(0, min(tempos_sem_aula, total_previsto))

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
                previsao=previsao_txt,
                tipo=tipo,
                tempos_sem_aula=tempos_sem_aula if tipo in DEFAULT_TIPOS_SEM_AULA else 0,
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
            previsao_txt = (request.form.get("previsao") or "").strip()
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
                return redirect(
                    url_for("turma_calendario_dia", turma_id=turma.id, data=data_ref)
                )
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

        def _parse_nota(field_name, default_val=3):
            valor = request.form.get(field_name)
            if valor in (None, ""):
                return default_val
            return _clamp_int(valor, min_val=1, max_val=5)

        if request.method == "POST":
            if ano_fechado:
                flash("Ano letivo fechado: apenas leitura.", "error")
                destino = return_url or url_for("turma_calendario", turma_id=turma.id)
                return redirect(destino)

            aula.atividade = bool(request.form.get("atividade_flag"))
            aula.atividade_nome = (
                request.form.get("atividade_nome") if aula.atividade else None
            )

            for aluno in alunos:
                avaliacao = avaliacoes.get(aluno.id)
                if not avaliacao:
                    avaliacao = AulaAluno(aula=aula, aluno=aluno)
                    db.session.add(avaliacao)
                    avaliacoes[aluno.id] = avaliacao

                avaliacao.atraso = bool(request.form.get(f"atraso_{aluno.id}"))
                avaliacao.faltas = (
                    _clamp_int(request.form.get(f"faltas_{aluno.id}"), default=0, min_val=0, max_val=6)
                    or 0
                )
                avaliacao.responsabilidade = _parse_nota(f"responsabilidade_{aluno.id}")
                avaliacao.comportamento = _parse_nota(f"comportamento_{aluno.id}")
                avaliacao.participacao = _parse_nota(f"participacao_{aluno.id}")
                avaliacao.trabalho_autonomo = _parse_nota(f"trabalho_autonomo_{aluno.id}")
                avaliacao.portatil_material = _parse_nota(f"portatil_material_{aluno.id}")
                avaliacao.atividade = _parse_nota(f"atividade_{aluno.id}")

            db.session.commit()
            flash("Avaliações de alunos guardadas.", "success")
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
        )

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

        aceita_json = request.headers.get("X-Requested-With") == "XMLHttpRequest"

        sumario_txt = request.form.get("sumario")
        if sumario_txt is not None:
            aula.sumario = sumario_txt.strip()

        previsao_txt = request.form.get("previsao")
        if previsao_txt is not None:
            aula.previsao = previsao_txt.strip()

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

        mensagem = "Sumário atualizado."

        if novo_tipo != tipo_original or mudou_tempos:
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

        if not aceita_json:
            flash(mensagem, "success")
        else:
            return jsonify(
                {
                    "status": "ok",
                    "sumario": aula.sumario or "",
                    "previsao": aula.previsao or "",
                    "tipo": aula.tipo,
                    "tempos_sem_aula": aula.tempos_sem_aula or 0,
                }
            )

        periodo_id = request.form.get("periodo_id", type=int)
        redirect_view = request.form.get("view")
        data_ref = request.form.get("data_ref")

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
            return redirect(
                url_for(
                    "turma_calendario_dia",
                    turma_id=turma.id,
                    data=data_ref,
                    periodo_id=periodo_id,
                )
            )
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
    app.run(debug=True)
