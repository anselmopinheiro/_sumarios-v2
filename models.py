from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.ext.associationproxy import association_proxy

db = SQLAlchemy()


class Livro(db.Model):
    __tablename__ = "livros"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(255), unique=True, nullable=False)

    livros_turmas = db.relationship(
        "LivroTurma",
        back_populates="livro",
        cascade="all, delete-orphan",
    )
    turmas = association_proxy(
        "livros_turmas",
        "turma",
        creator=lambda turma: LivroTurma(turma=turma),
    )


class AnoLetivo(db.Model):
    __tablename__ = "anos_letivos"

    id = db.Column(db.Integer, primary_key=True)

    # Ex.: "2025/2026"
    nome = db.Column(db.String(20), unique=True, nullable=False)

    # Datas principais
    data_inicio_ano = db.Column(db.Date, nullable=False)
    data_fim_ano = db.Column(db.Date, nullable=False)

    data_fim_semestre1 = db.Column(db.Date, nullable=False)
    data_inicio_semestre2 = db.Column(db.Date, nullable=False)

    descricao = db.Column(db.String(255))

    # Ano letivo actualmente em uso (“Corrente”)
    ativo = db.Column(db.Boolean, nullable=False, default=False, server_default=db.text("false"))

    # Anos passados que ficam só para consulta/exportação
    fechado = db.Column(db.Boolean, nullable=False, default=False, server_default=db.text("false"))

    # Relações opcionais, se as tiveres:
    # turmas = db.relationship("Turma", back_populates="ano_letivo")
    # interrupcoes = db.relationship("InterrupcaoLetiva", back_populates="ano_letivo")
    # feriados = db.relationship("Feriado", back_populates="ano_letivo")



class Turma(db.Model):
    __tablename__ = "turmas"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(50), nullable=False)
    tipo = db.Column(db.String(20), nullable=False, default="regular")
    periodo_tipo = db.Column(db.String(20), nullable=False, default="anual")

    # deixa como nullable=True para não partir a migração em SQLite
    ano_letivo_id = db.Column(db.Integer, db.ForeignKey("anos_letivos.id"))
    ano_letivo = db.relationship("AnoLetivo", backref="turmas")

    # 👉 NOVO: relação com Livro (simétrica do Livro.turmas)
    livros_turmas = db.relationship(
        "LivroTurma",
        back_populates="turma",
        cascade="all, delete-orphan",
    )
    livros = association_proxy(
        "livros_turmas",
        "livro",
        creator=lambda livro: LivroTurma(livro=livro),
    )
    # NOVO — carga horária por dia da semana
    carga_segunda = db.Column(db.Float, nullable=True)
    carga_terca = db.Column(db.Float, nullable=True)
    carga_quarta = db.Column(db.Float, nullable=True)
    carga_quinta = db.Column(db.Float, nullable=True)
    carga_sexta = db.Column(db.Float, nullable=True)
    # Tempo/horário por dia da semana (1.º a 12.º tempo)
    tempo_segunda = db.Column(db.Integer, nullable=True)
    tempo_terca = db.Column(db.Integer, nullable=True)
    tempo_quarta = db.Column(db.Integer, nullable=True)
    tempo_quinta = db.Column(db.Integer, nullable=True)
    tempo_sexta = db.Column(db.Integer, nullable=True)
    letiva = db.Column(db.Boolean, nullable=False, default=True, server_default=db.text("true"))
    # relação many-to-many com disciplina
    turmas_disciplinas = db.relationship(
        "TurmaDisciplina",
        back_populates="turma",
        cascade="all, delete-orphan",
    )
    disciplinas = association_proxy(
        "turmas_disciplinas",
        "disciplina",
        creator=lambda disciplina: TurmaDisciplina(disciplina=disciplina),
    )
    alunos = db.relationship(
        "Aluno",
        back_populates="turma",
        cascade="all, delete-orphan",
    )

    
    

class Disciplina(db.Model):
    __tablename__ = "disciplinas"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)       # ex.: "Produção Multimédia"
    sigla = db.Column(db.String(20))                       # ex.: "PM"

    ano_letivo_id = db.Column(db.Integer, db.ForeignKey("anos_letivos.id"), nullable=False)
    ano_letivo = db.relationship("AnoLetivo", backref="disciplinas")

    turmas_disciplinas = db.relationship(
        "TurmaDisciplina",
        back_populates="disciplina",
        cascade="all, delete-orphan",
    )
    turmas = association_proxy(
        "turmas_disciplinas",
        "turma",
        creator=lambda turma: TurmaDisciplina(turma=turma),
    )


class LivroTurma(db.Model):
    __tablename__ = "livros_turmas"

    livro_id = db.Column(db.Integer, db.ForeignKey("livros.id"), primary_key=True)
    turma_id = db.Column(db.Integer, db.ForeignKey("turmas.id"), primary_key=True)

    livro = db.relationship("Livro", back_populates="livros_turmas")
    turma = db.relationship("Turma", back_populates="livros_turmas")


class TurmaDisciplina(db.Model):
    __tablename__ = "turmas_disciplinas"

    id = db.Column(db.Integer, primary_key=True)
    turma_id = db.Column(db.Integer, db.ForeignKey("turmas.id"), nullable=False)
    disciplina_id = db.Column(db.Integer, db.ForeignKey("disciplinas.id"), nullable=False)

    turma = db.relationship("Turma", back_populates="turmas_disciplinas")
    disciplina = db.relationship("Disciplina", back_populates="turmas_disciplinas")

    # opcional, mas útil para mais tarde:
    horas_semanais = db.Column(db.Float)

    __table_args__ = (
        db.UniqueConstraint("turma_id", "disciplina_id", name="uq_turma_disciplina"),
    )


class Horario(db.Model):
    __tablename__ = "horarios"
    id = db.Column(db.Integer, primary_key=True)
    turma_id = db.Column(db.Integer, db.ForeignKey("turmas.id"), nullable=False)
    # 0=Seg, 1=Ter, ..., 6=Dom
    weekday = db.Column(db.Integer, nullable=False)
    horas = db.Column(db.Integer, nullable=False)


class Aluno(db.Model):
    __tablename__ = "alunos"

    id = db.Column(db.Integer, primary_key=True)
    turma_id = db.Column(db.Integer, db.ForeignKey("turmas.id"), nullable=False)

    processo = db.Column(db.String(50))
    numero = db.Column(db.Integer)
    nome = db.Column(db.String(255), nullable=False)
    nome_curto = db.Column(db.String(100))
    nee = db.Column(db.Text)
    observacoes = db.Column(db.Text)

    @property
    def nome_curto_exibicao(self):
        raw = (self.nome_curto or "").strip()
        if raw:
            return raw
        full_name = (self.nome or "").strip()
        if not full_name:
            return ""
        parts = [p for p in full_name.split() if p]
        if len(parts) == 1:
            return parts[0]
        return f"{parts[0]} {parts[-1][0]}."

    turma = db.relationship("Turma", back_populates="alunos")
    avaliacoes = db.relationship(
        "AulaAluno", back_populates="aluno", cascade="all, delete-orphan"
    )

    __table_args__ = (
        db.Index("ix_alunos_turma_numero", "turma_id", "numero"),
    )


class DTTurma(db.Model):
    __tablename__ = "dt_turmas"

    id = db.Column(db.Integer, primary_key=True)
    turma_id = db.Column(db.Integer, db.ForeignKey("turmas.id"), nullable=False)
    ano_letivo_id = db.Column(db.Integer, db.ForeignKey("anos_letivos.id"), nullable=False)
    observacoes = db.Column(db.Text)

    turma = db.relationship("Turma", backref="dt_turmas")
    ano_letivo = db.relationship("AnoLetivo", backref="dt_turmas")
    alunos = db.relationship(
        "DTAluno",
        back_populates="dt_turma",
        cascade="all, delete-orphan",
    )
    ocorrencias = db.relationship(
        "DTOcorrencia",
        back_populates="dt_turma",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        db.UniqueConstraint("turma_id", "ano_letivo_id", name="uq_dt_turma_ano"),
    )


class DTAluno(db.Model):
    __tablename__ = "dt_alunos"

    id = db.Column(db.Integer, primary_key=True)
    dt_turma_id = db.Column(db.Integer, db.ForeignKey("dt_turmas.id"), nullable=False)
    aluno_id = db.Column(db.Integer, db.ForeignKey("alunos.id"), nullable=False)

    dt_turma = db.relationship("DTTurma", back_populates="alunos")
    aluno = db.relationship("Aluno")
    justificacoes = db.relationship(
        "DTJustificacao",
        back_populates="dt_aluno",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        db.Index("ix_dt_alunos_turma_aluno", "dt_turma_id", "aluno_id"),
    )


class DTJustificacao(db.Model):
    __tablename__ = "dt_justificacoes"

    id = db.Column(db.Integer, primary_key=True)
    dt_aluno_id = db.Column(db.Integer, db.ForeignKey("dt_alunos.id"), nullable=False)
    data = db.Column(db.Date, nullable=False)
    tipo = db.Column(db.String(20), nullable=False, default="falta")
    motivo = db.Column(db.Text)

    dt_aluno = db.relationship("DTAluno", back_populates="justificacoes")


class DTMotivoDia(db.Model):
    __tablename__ = "dt_motivos_dia"

    id = db.Column(db.Integer, primary_key=True)
    dt_turma_id = db.Column(db.Integer, db.ForeignKey("dt_turmas.id"), nullable=False)
    data = db.Column(db.Date, nullable=False)
    motivo = db.Column(db.Text)

    dt_turma = db.relationship("DTTurma", backref="motivos_dia")

    __table_args__ = (
        db.UniqueConstraint("dt_turma_id", "data", name="uq_dt_motivo_dia"),
    )


class DTDisciplina(db.Model):
    __tablename__ = "dt_disciplinas"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False, unique=True)
    nome_curto = db.Column(db.String(40))
    professor_nome = db.Column(db.String(120))
    ativa = db.Column(db.Boolean, nullable=False, default=True, server_default=db.text("true"))


class DTOcorrenciaAluno(db.Model):
    __tablename__ = "dt_ocorrencia_alunos"

    id = db.Column(db.Integer, primary_key=True)
    dt_ocorrencia_id = db.Column(db.Integer, db.ForeignKey("dt_ocorrencias.id"), nullable=False)
    dt_aluno_id = db.Column(db.Integer, db.ForeignKey("dt_alunos.id"), nullable=False)

    __table_args__ = (
        db.UniqueConstraint("dt_ocorrencia_id", "dt_aluno_id", name="uq_dt_ocorrencia_aluno"),
        db.Index("ix_dt_ocorrencia_alunos_ocorrencia", "dt_ocorrencia_id"),
        db.Index("ix_dt_ocorrencia_alunos_aluno", "dt_aluno_id"),
    )


class DTOcorrencia(db.Model):
    __tablename__ = "dt_ocorrencias"

    id = db.Column(db.Integer, primary_key=True)
    dt_turma_id = db.Column(db.Integer, db.ForeignKey("dt_turmas.id"), nullable=False, index=True)
    data = db.Column(db.Date, nullable=False, index=True)
    hora_inicio = db.Column(db.Time)
    hora_fim = db.Column(db.Time)
    num_tempos = db.Column(db.Integer)
    dt_disciplina_id = db.Column(db.Integer, db.ForeignKey("dt_disciplinas.id"), nullable=False, index=True)
    observacoes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, server_default=db.text("now()"))
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, server_default=db.text("now()"))

    dt_turma = db.relationship("DTTurma", back_populates="ocorrencias")
    disciplina = db.relationship("DTDisciplina", backref="ocorrencias")
    alunos = db.relationship(
        "DTAluno",
        secondary="dt_ocorrencia_alunos",
        backref=db.backref("ocorrencias", lazy="dynamic"),
    )


class Modulo(db.Model):
    __tablename__ = "modulos"
    id = db.Column(db.Integer, primary_key=True)
    turma_id = db.Column(db.Integer, db.ForeignKey("turmas.id"), nullable=False)

    nome = db.Column(db.String(255), nullable=False)
    total_aulas = db.Column(db.Integer, nullable=False)

    # tolerância extra para além do total (usado sobretudo em profissional)
    tolerancia = db.Column(db.Integer, nullable=False, default=2)


class Periodo(db.Model):
    __tablename__ = "periodos"

    id = db.Column(db.Integer, primary_key=True)

    # Nome visível (ex.: "Anual", "1.º semestre", "2.º semestre", "Módulo 3")
    nome = db.Column(db.String(100), nullable=False)

    # NOVO: tipo de período (anual / semestre1 / semestre2 / modular)
    # podes usar valores normalizados para lógica e o "nome" para mostrar.
    tipo = db.Column(db.String(20), nullable=False, default="anual")
    # valores previstos: "anual", "semestre1", "semestre2", "modular"

    data_inicio = db.Column(db.Date, nullable=False)
    data_fim = db.Column(db.Date, nullable=False)

    turma_id = db.Column(db.Integer, db.ForeignKey("turmas.id"), nullable=False)
    turma = db.relationship("Turma", backref="periodos")

    # OPCIONAL (para profissionais): período associado diretamente a um módulo
    modulo_id = db.Column(db.Integer, db.ForeignKey("modulos.id"), nullable=True)
    modulo = db.relationship("Modulo", backref="periodos_modulares")



class Exclusao(db.Model):
    """
    Equivalente à folha 'Exclusões' no Sheets:
    - dia em que não há aulas normais (ou é greve / serviço oficial).
    """

    __tablename__ = "exclusoes"
    id = db.Column(db.Integer, primary_key=True)
    turma_id = db.Column(db.Integer, db.ForeignKey("turmas.id"), nullable=False)

    data = db.Column(db.Date, nullable=True)
    # exemplo: "22 de dezembro de 2025 a 2 de janeiro de 2026"
    data_text = db.Column(db.String(255), nullable=True)

    motivo = db.Column(db.String(255))
    # normal / greve / servico_oficial
    tipo = db.Column(db.String(50))


class Extra(db.Model):
    """
    Equivalente à folha 'Extras' no Sheets:
    - aulas extra ou serviços oficiais que aparecem no calendário.
    """

    __tablename__ = "extras"
    id = db.Column(db.Integer, primary_key=True)
    turma_id = db.Column(db.Integer, db.ForeignKey("turmas.id"), nullable=False)

    data = db.Column(db.Date, nullable=True)
    data_text = db.Column(db.String(255), nullable=True)

    motivo = db.Column(db.String(255))
    aulas = db.Column(db.Integer, nullable=False)
    modulo_nome = db.Column(db.String(255))
    # extra / servico_oficial
    tipo = db.Column(db.String(50))


class InterrupcaoLetiva(db.Model):
    """
    Interrupções de Natal, Páscoa, Carnaval, intercalares, etc.
    Podem ser dadas por datas explícitas ou por expressão textual em PT.
    """

    __tablename__ = "interrupcoes_letivas"
    id = db.Column(db.Integer, primary_key=True)

    ano_letivo_id = db.Column(db.Integer, db.ForeignKey("anos_letivos.id"), nullable=False)
    ano_letivo = db.relationship("AnoLetivo", backref="interrupcoes")

    # tipos: natal, pascoa, carnaval, intercalar1, intercalar2, outros
    tipo = db.Column(db.String(50), nullable=False)

    data_inicio = db.Column(db.Date, nullable=True)
    data_fim = db.Column(db.Date, nullable=True)

    # ex.: "22 de dezembro de 2025 a 2 de janeiro de 2026"
    # ou "16 e 17 de fevereiro de 2026"
    data_text = db.Column(db.String(255), nullable=True)

    descricao = db.Column(db.String(255), nullable=True)


class Feriado(db.Model):
    """
    Feriados do ano letivo (nacionais, municipais, dia do agrupamento, etc.)
    """

    __tablename__ = "feriados"
    id = db.Column(db.Integer, primary_key=True)

    ano_letivo_id = db.Column(db.Integer, db.ForeignKey("anos_letivos.id"), nullable=False)
    ano_letivo = db.relationship("AnoLetivo", backref="feriados")

    data = db.Column(db.Date, nullable=True)
    data_text = db.Column(db.String(255), nullable=True)

    nome = db.Column(db.String(255), nullable=False)


class CalendarioAula(db.Model):
    """
    Tabela final com o “resultado” da previsão:
    1 linha por dia de aula (ou greve / serviço oficial / extra).
    """

    __tablename__ = "calendario_aulas"
    id = db.Column(db.Integer, primary_key=True)

    turma_id = db.Column(db.Integer, db.ForeignKey("turmas.id"), nullable=False)
    periodo_id = db.Column(db.Integer, db.ForeignKey("periodos.id"), nullable=False)

    data = db.Column(db.Date, nullable=False)
    # 0=Seg, 1=Ter, ..., 6=Dom
    weekday = db.Column(db.Integer, nullable=False)

    modulo_id = db.Column(db.Integer, db.ForeignKey("modulos.id"))
    modulo = db.relationship("Modulo")
    numero_modulo = db.Column(db.Integer)
    total_geral = db.Column(db.Integer)
    sumarios = db.Column(db.String(255))

    # normal / greve / servico_oficial / extra
    tipo = db.Column(db.String(50), default="normal", nullable=False)

    apagado = db.Column(db.Boolean, default=False, nullable=False, server_default=db.text("false"))

    # Número de tempos que não contam para a numeração (aplicável em faltas, serviço oficial, etc.)
    tempos_sem_aula = db.Column(db.Integer, default=0)

    observacoes = db.Column(db.Text)
    sumario = db.Column(db.Text)
    previsao = db.Column(db.Text)
    atividade = db.Column(db.Boolean, default=False, server_default=db.text("false"), nullable=False)
    atividade_nome = db.Column(db.Text)

    turma = db.relationship("Turma", backref="calendario_aulas")
    avaliacoes = db.relationship(
        "AulaAluno", back_populates="aula", cascade="all, delete-orphan"
    )

    __table_args__ = (
        db.Index("ix_cal_aulas_turma_data", "turma_id", "data", "apagado"),
        db.Index("ix_cal_aulas_periodo", "periodo_id", "data"),
        db.Index("ix_cal_aulas_modulo", "modulo_id"),
    )


class AulaSumarioHistorico(db.Model):
    __tablename__ = "sumario_historico"

    id = db.Column(db.Integer, primary_key=True)
    calendario_aula_id = db.Column(
        db.Integer, db.ForeignKey("calendario_aulas.id"), nullable=False
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, server_default=db.text("now()"))
    acao = db.Column(db.String(50), nullable=False)
    sumario_anterior = db.Column(db.Text)
    sumario_novo = db.Column(db.Text)
    autor = db.Column(db.String(100), default="local", nullable=False)

    aula = db.relationship("CalendarioAula", backref="sumario_historico")

    __table_args__ = (
        db.Index("ix_sumario_hist_aula_data", "calendario_aula_id", "created_at"),
    )


class AulaAluno(db.Model):
    __tablename__ = "aulas_alunos"

    id = db.Column(db.Integer, primary_key=True)
    aula_id = db.Column(db.Integer, db.ForeignKey("calendario_aulas.id"), nullable=False)
    aluno_id = db.Column(db.Integer, db.ForeignKey("alunos.id"), nullable=False)

    # True = atraso; False = pontual
    atraso = db.Column(db.Boolean, default=False, nullable=False, server_default=db.text("false"))
    # Número de tempos em falta (0 = presente)
    faltas = db.Column(db.Integer, default=0, nullable=False)

    responsabilidade = db.Column(db.Integer, default=3, server_default="3")
    comportamento = db.Column(db.Integer, default=3, server_default="3")
    participacao = db.Column(db.Integer, default=3, server_default="3")
    trabalho_autonomo = db.Column(db.Integer, default=3, server_default="3")
    portatil_material = db.Column(db.Integer, default=3, server_default="3")
    atividade = db.Column(db.Integer, default=3, server_default="3")
    falta_disciplinar = db.Column(db.Integer, default=0, server_default="0", nullable=False)

    aula = db.relationship("CalendarioAula", back_populates="avaliacoes")
    aluno = db.relationship("Aluno", back_populates="avaliacoes")

    __table_args__ = (
        db.UniqueConstraint("aula_id", "aluno_id", name="uq_aula_aluno"),
        db.Index("ix_aulas_alunos_aula", "aula_id"),
        db.Index("ix_aulas_alunos_aluno", "aluno_id"),
    )


class GrupoTurma(db.Model):
    __tablename__ = "grupos_turma"

    id = db.Column(db.Integer, primary_key=True)
    turma_id = db.Column(db.Integer, db.ForeignKey("turmas.id"), nullable=False, index=True)
    nome = db.Column(db.String(255), nullable=False)

    turma = db.relationship("Turma", backref=db.backref("grupos_catalogo", cascade="all, delete-orphan"))

    __table_args__ = (
        db.UniqueConstraint("turma_id", "nome", name="uq_grupo_turma_nome"),
    )


class GrupoTurmaMembro(db.Model):
    __tablename__ = "grupo_turma_membros"

    id = db.Column(db.Integer, primary_key=True)
    grupo_turma_id = db.Column(db.Integer, db.ForeignKey("grupos_turma.id"), nullable=False, index=True)
    aluno_id = db.Column(db.Integer, db.ForeignKey("alunos.id"), nullable=False, index=True)

    grupo = db.relationship("GrupoTurma", backref=db.backref("membros", cascade="all, delete-orphan"))
    aluno = db.relationship("Aluno")

    __table_args__ = (
        db.UniqueConstraint("grupo_turma_id", "aluno_id", name="uq_grupo_turma_membro"),
    )


class Trabalho(db.Model):
    __tablename__ = "trabalhos"

    id = db.Column(db.Integer, primary_key=True)
    turma_id = db.Column(db.Integer, db.ForeignKey("turmas.id"), nullable=False, index=True)
    titulo = db.Column(db.String(255), nullable=False)
    descricao = db.Column(db.Text)
    modo = db.Column(db.String(20), nullable=False, default="individual", server_default="individual")
    data_limite = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, server_default=db.text("now()"))

    turma = db.relationship("Turma", backref=db.backref("trabalhos", cascade="all, delete-orphan"))


class TrabalhoGrupo(db.Model):
    __tablename__ = "trabalho_grupos"

    id = db.Column(db.Integer, primary_key=True)
    trabalho_id = db.Column(db.Integer, db.ForeignKey("trabalhos.id"), nullable=False, index=True)
    nome = db.Column(db.String(255), nullable=False)

    trabalho = db.relationship("Trabalho", backref=db.backref("grupos", cascade="all, delete-orphan"))

    __table_args__ = (
        db.UniqueConstraint("trabalho_id", "nome", name="uq_trabalho_grupo_nome"),
    )


class TrabalhoGrupoMembro(db.Model):
    __tablename__ = "trabalho_grupo_membros"

    id = db.Column(db.Integer, primary_key=True)
    trabalho_grupo_id = db.Column(db.Integer, db.ForeignKey("trabalho_grupos.id"), nullable=False, index=True)
    aluno_id = db.Column(db.Integer, db.ForeignKey("alunos.id"), nullable=False, index=True)

    grupo = db.relationship("TrabalhoGrupo", backref=db.backref("membros", cascade="all, delete-orphan"))
    aluno = db.relationship("Aluno")

    __table_args__ = (
        db.UniqueConstraint("trabalho_grupo_id", "aluno_id", name="uq_trabalho_grupo_membro"),
    )


class Entrega(db.Model):
    __tablename__ = "entregas"

    id = db.Column(db.Integer, primary_key=True)
    trabalho_id = db.Column(db.Integer, db.ForeignKey("trabalhos.id"), nullable=False, index=True)
    trabalho_grupo_id = db.Column(db.Integer, db.ForeignKey("trabalho_grupos.id"), nullable=False, index=True)

    entregue = db.Column(db.Boolean, nullable=False, default=False, server_default=db.text("false"))
    data_entrega = db.Column(db.DateTime)
    consecucao = db.Column(db.Integer)
    qualidade = db.Column(db.Integer)
    observacoes = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, server_default=db.text("now()"))

    trabalho = db.relationship("Trabalho", backref=db.backref("entregas", cascade="all, delete-orphan"))
    grupo = db.relationship("TrabalhoGrupo", backref=db.backref("entrega", uselist=False, cascade="all, delete-orphan"))

    __table_args__ = (
        db.UniqueConstraint("trabalho_id", "trabalho_grupo_id", name="uq_entrega_trabalho_grupo"),
        db.CheckConstraint("consecucao IS NULL OR (consecucao >= 1 AND consecucao <= 5)", name="ck_entrega_consecucao_1_5"),
        db.CheckConstraint("qualidade IS NULL OR (qualidade >= 1 AND qualidade <= 5)", name="ck_entrega_qualidade_1_5"),
    )


class ParametroDefinicao(db.Model):
    __tablename__ = "parametro_definicoes"

    id = db.Column(db.Integer, primary_key=True)
    trabalho_id = db.Column(db.Integer, db.ForeignKey("trabalhos.id"), nullable=False, index=True)
    nome = db.Column(db.String(120), nullable=False)
    tipo = db.Column(db.String(20), nullable=False, default="numerico", server_default="numerico")
    ordem = db.Column(db.Integer, nullable=False, default=0, server_default="0")

    trabalho = db.relationship("Trabalho", backref=db.backref("parametros", cascade="all, delete-orphan"))

    __table_args__ = (
        db.UniqueConstraint("trabalho_id", "nome", name="uq_parametro_trabalho_nome"),
    )


class EntregaParametro(db.Model):
    __tablename__ = "entrega_parametros"

    id = db.Column(db.Integer, primary_key=True)
    entrega_id = db.Column(db.Integer, db.ForeignKey("entregas.id"), nullable=False, index=True)
    parametro_definicao_id = db.Column(db.Integer, db.ForeignKey("parametro_definicoes.id"), nullable=False, index=True)
    valor_numerico = db.Column(db.Integer)
    valor_texto = db.Column(db.Text)

    entrega = db.relationship("Entrega", backref=db.backref("parametros", cascade="all, delete-orphan"))
    parametro = db.relationship("ParametroDefinicao")

    __table_args__ = (
        db.UniqueConstraint("entrega_id", "parametro_definicao_id", name="uq_entrega_parametro"),
        db.CheckConstraint("valor_numerico IS NULL OR (valor_numerico >= 1 AND valor_numerico <= 5)", name="ck_entrega_parametro_num_1_5"),
    )
