from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
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
    ativo = db.Column(db.Boolean, nullable=False, default=False)

    # Anos passados que ficam só para consulta/exportação
    fechado = db.Column(db.Boolean, nullable=False, default=False)

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
    letiva = db.Column(db.Boolean, nullable=False, default=True)
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
    ev2_subject_configs = db.relationship(
        "EV2SubjectConfig",
        back_populates="disciplina",
        cascade="all, delete-orphan",
    )
    ev2_events = db.relationship(
        "EV2Event",
        back_populates="disciplina",
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

    data_nascimento = db.Column(db.Date)
    tipo_identificacao = db.Column(db.String(30))
    numero_identificacao = db.Column(db.String(80))
    email = db.Column(db.String(255))
    telefone = db.Column(db.String(40))
    numero_utente_sns = db.Column(db.String(40))
    numero_processo = db.Column(db.String(50))

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




class DTJustificacaoTexto(db.Model):
    __tablename__ = "dt_justificacao_textos"

    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(120), nullable=False)
    texto = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, server_default=db.text("now()"))
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, server_default=db.text("now()"))

class AlunoContextoDT(db.Model):
    __tablename__ = "aluno_contexto_dt"

    id = db.Column(db.Integer, primary_key=True)
    aluno_id = db.Column(db.Integer, db.ForeignKey("alunos.id"), nullable=False, unique=True)
    dt_observacoes = db.Column(db.Text)
    ee_observacoes = db.Column(db.Text)
    alerta_dt = db.Column(db.Text)
    resumo_sinalizacao = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    aluno = db.relationship("Aluno", backref=db.backref("contexto_dt", uselist=False, cascade="all, delete-orphan"))


class EncarregadoEducacao(db.Model):
    __tablename__ = "ee"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(255), nullable=False)
    telefone = db.Column(db.String(40))
    email = db.Column(db.String(255))
    observacoes = db.Column(db.Text)
    nome_alternativo = db.Column(db.String(255))
    telefone_alternativo = db.Column(db.String(40))
    email_alternativo = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class EEAluno(db.Model):
    __tablename__ = "ee_alunos"

    id = db.Column(db.Integer, primary_key=True)
    ee_id = db.Column(db.Integer, db.ForeignKey("ee.id"), nullable=False, index=True)
    aluno_id = db.Column(db.Integer, db.ForeignKey("alunos.id"), nullable=False, index=True)
    parentesco = db.Column(db.String(80))
    observacoes = db.Column(db.Text)
    data_inicio = db.Column(db.Date, nullable=False)
    data_fim = db.Column(db.Date)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    ee = db.relationship("EncarregadoEducacao", backref=db.backref("alunos_relacoes", cascade="all, delete-orphan"))
    aluno = db.relationship("Aluno", backref=db.backref("ee_relacoes", cascade="all, delete-orphan"))


class DTCargoAluno(db.Model):
    __tablename__ = "dt_cargos_alunos"

    id = db.Column(db.Integer, primary_key=True)
    dt_turma_id = db.Column(db.Integer, db.ForeignKey("dt_turmas.id"), nullable=False, index=True)
    aluno_id = db.Column(db.Integer, db.ForeignKey("alunos.id"), nullable=False, index=True)
    cargo = db.Column(db.String(40), nullable=False)
    data_inicio = db.Column(db.Date, nullable=False)
    data_fim = db.Column(db.Date)
    motivo_fim = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    dt_turma = db.relationship("DTTurma", backref="cargos_alunos")
    aluno = db.relationship("Aluno", backref="cargos_dt")


class DTCargoEE(db.Model):
    __tablename__ = "dt_cargos_ee"

    id = db.Column(db.Integer, primary_key=True)
    dt_turma_id = db.Column(db.Integer, db.ForeignKey("dt_turmas.id"), nullable=False, index=True)
    ee_id = db.Column(db.Integer, db.ForeignKey("ee.id"), nullable=False, index=True)
    cargo = db.Column(db.String(60), nullable=False)
    data_inicio = db.Column(db.Date, nullable=False)
    data_fim = db.Column(db.Date)
    motivo_fim = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    dt_turma = db.relationship("DTTurma", backref="cargos_ee")
    ee = db.relationship("EncarregadoEducacao", backref="cargos_dt")


class TipoContacto(db.Model):
    __tablename__ = "tipo_contacto"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False, unique=True)
    ordem = db.Column(db.Integer, nullable=False, default=0)


class MotivoContacto(db.Model):
    __tablename__ = "motivo_contacto"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False, unique=True)
    ordem = db.Column(db.Integer, nullable=False, default=0)


class Contacto(db.Model):
    __tablename__ = "contactos"

    id = db.Column(db.Integer, primary_key=True)
    ee_id = db.Column(db.Integer, db.ForeignKey("ee.id"), nullable=False, index=True)
    dt_turma_id = db.Column(db.Integer, db.ForeignKey("dt_turmas.id"), nullable=False, index=True)
    data_hora = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    iniciado_por = db.Column(db.String(20), nullable=False, default="professor")
    resumo = db.Column(db.Text)
    observacoes_gerais = db.Column(db.Text)
    estado_contacto = db.Column(db.String(40), nullable=False, default="realizado")
    estado_reuniao = db.Column(db.String(40), nullable=False, default="nao_agendada")
    data_reuniao = db.Column(db.DateTime)
    requer_followup = db.Column(db.Boolean, nullable=False, default=False)
    data_followup = db.Column(db.Date)
    confidencial = db.Column(db.Boolean, nullable=False, default=False)
    created_by = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    ee = db.relationship("EncarregadoEducacao", backref="contactos")
    dt_turma = db.relationship("DTTurma", backref="contactos")


class ContactoTipo(db.Model):
    __tablename__ = "contacto_tipos"

    id = db.Column(db.Integer, primary_key=True)
    contacto_id = db.Column(db.Integer, db.ForeignKey("contactos.id"), nullable=False, index=True)
    tipo_contacto_id = db.Column(db.Integer, db.ForeignKey("tipo_contacto.id"), nullable=False, index=True)


class ContactoAluno(db.Model):
    __tablename__ = "contacto_alunos"

    id = db.Column(db.Integer, primary_key=True)
    contacto_id = db.Column(db.Integer, db.ForeignKey("contactos.id"), nullable=False, index=True)
    aluno_id = db.Column(db.Integer, db.ForeignKey("alunos.id"), nullable=False, index=True)
    ee_aluno_id_snapshot = db.Column(db.Integer, db.ForeignKey("ee_alunos.id"))
    observacoes = db.Column(db.Text)
    resultado_individual = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    contacto = db.relationship("Contacto", backref=db.backref("alunos", cascade="all, delete-orphan"))
    aluno = db.relationship("Aluno")
    ee_aluno_snapshot = db.relationship("EEAluno")


class ContactoAlunoMotivo(db.Model):
    __tablename__ = "contacto_aluno_motivos"

    id = db.Column(db.Integer, primary_key=True)
    contacto_aluno_id = db.Column(db.Integer, db.ForeignKey("contacto_alunos.id"), nullable=False, index=True)
    motivo_contacto_id = db.Column(db.Integer, db.ForeignKey("motivo_contacto.id"), nullable=False, index=True)
    detalhe = db.Column(db.Text)

    contacto_aluno = db.relationship("ContactoAluno", backref=db.backref("motivos", cascade="all, delete-orphan"))
    motivo = db.relationship("MotivoContacto")


class ContactoLink(db.Model):
    __tablename__ = "contacto_links"

    id = db.Column(db.Integer, primary_key=True)
    contacto_id = db.Column(db.Integer, db.ForeignKey("contactos.id"), nullable=False, index=True)
    titulo = db.Column(db.String(255), nullable=False)
    url = db.Column(db.String(1000), nullable=False)
    tipo = db.Column(db.String(80))
    observacoes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    contacto = db.relationship("Contacto", backref=db.backref("links", cascade="all, delete-orphan"))


class DTDisciplina(db.Model):
    __tablename__ = "dt_disciplinas"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False, unique=True)
    nome_curto = db.Column(db.String(40))
    professor_nome = db.Column(db.String(120))
    ativa = db.Column(db.Boolean, nullable=False, default=True)


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

    apagado = db.Column(db.Boolean, default=False, nullable=False)

    # Número de tempos que não contam para a numeração (aplicável em faltas, serviço oficial, etc.)
    tempos_sem_aula = db.Column(db.Integer, default=0)

    observacoes = db.Column(db.Text)
    observacoes_html = db.Column(db.Text)
    sumario = db.Column(db.Text)
    previsao = db.Column(db.Text)
    atividade = db.Column(db.Boolean, default=False, nullable=False)
    atividade_nome = db.Column(db.Text)

    turma = db.relationship("Turma", backref="calendario_aulas")
    avaliacoes = db.relationship(
        "AulaAluno", back_populates="aula", cascade="all, delete-orphan"
    )
    ev2_events = db.relationship(
        "EV2Event", back_populates="aula", cascade="all, delete-orphan"
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
    atraso = db.Column(db.Boolean, default=False, nullable=False)
    # Número de tempos em falta (0 = presente)
    faltas = db.Column(db.Integer, default=0, nullable=False)

    responsabilidade = db.Column(db.Integer, default=3, server_default="3")
    comportamento = db.Column(db.Integer, default=3, server_default="3")
    participacao = db.Column(db.Integer, default=3, server_default="3")
    trabalho_autonomo = db.Column(db.Integer, default=3, server_default="3")
    portatil_material = db.Column(db.Integer, default=3, server_default="3")
    atividade = db.Column(db.Integer, default=3, server_default="3")
    falta_disciplinar = db.Column(db.Integer, default=0, server_default="0", nullable=False)
    observacoes = db.Column(db.Text, nullable=True)

    aula = db.relationship("CalendarioAula", back_populates="avaliacoes")
    aluno = db.relationship("Aluno", back_populates="avaliacoes")

    __table_args__ = (
        db.UniqueConstraint("aula_id", "aluno_id", name="uq_aula_aluno"),
        db.Index("ix_aulas_alunos_aula", "aula_id"),
        db.Index("ix_aulas_alunos_aluno", "aluno_id"),
    )




class Avaliacao(db.Model):
    __tablename__ = "avaliacoes"

    id = db.Column(db.Integer, primary_key=True)
    aluno_id = db.Column(db.Integer, db.ForeignKey("alunos.id"), nullable=False)
    aula_id = db.Column(db.Integer, db.ForeignKey("calendario_aulas.id"), nullable=False)
    resultado = db.Column(db.Float, nullable=True)

    aluno = db.relationship("Aluno", backref="aula_avaliacoes")
    aula = db.relationship("CalendarioAula", backref="aula_avaliacoes")
    itens = db.relationship("AvaliacaoItem", back_populates="avaliacao", cascade="all, delete-orphan")

    __table_args__ = (
        db.UniqueConstraint("aluno_id", "aula_id", name="uq_avaliacao_aluno_aula"),
        db.Index("ix_avaliacoes_aula", "aula_id"),
        db.Index("ix_avaliacoes_aluno", "aluno_id"),
    )


class AvaliacaoItem(db.Model):
    __tablename__ = "avaliacao_itens"

    id = db.Column(db.Integer, primary_key=True)
    avaliacao_id = db.Column(db.Integer, db.ForeignKey("avaliacoes.id"), nullable=False)
    rubrica_id = db.Column(db.Integer, db.ForeignKey("ev2_rubrics.id"), nullable=False)
    pontuacao = db.Column(db.Float, nullable=True)

    avaliacao = db.relationship("Avaliacao", back_populates="itens")
    rubrica = db.relationship("EV2Rubric")

    __table_args__ = (
        db.UniqueConstraint("avaliacao_id", "rubrica_id", name="uq_avaliacao_item_once"),
        db.Index("ix_avaliacao_itens_avaliacao", "avaliacao_id"),
        db.Index("ix_avaliacao_itens_rubrica", "rubrica_id"),
    )

class EV2Domain(db.Model):
    __tablename__ = "ev2_domains"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False, unique=True)
    letra = db.Column(db.String(5), nullable=True)
    codigo = db.Column(db.String(20), nullable=True)
    descricao = db.Column(db.Text)
    ativo = db.Column(db.Boolean, nullable=False, default=True, server_default=db.text("true"))

    rubricas = db.relationship(
        "EV2Rubric", back_populates="dominio", cascade="all, delete-orphan"
    )


class EV2Rubric(db.Model):
    __tablename__ = "ev2_rubrics"

    id = db.Column(db.Integer, primary_key=True)
    domain_id = db.Column(db.Integer, db.ForeignKey("ev2_domains.id"), nullable=False)
    codigo = db.Column(db.String(80), nullable=False)
    nome = db.Column(db.String(140), nullable=False)
    descricao = db.Column(db.Text)
    ativo = db.Column(db.Boolean, nullable=False, default=True, server_default=db.text("true"))
    pontuacao_padrao_basico = db.Column(db.Float, default=3)
    pontuacao_padrao_secundario = db.Column(db.Float, default=12)

    dominio = db.relationship("EV2Domain", back_populates="rubricas")
    subject_rubrics = db.relationship("EV2SubjectRubric", back_populates="rubrica")

    __table_args__ = (
        db.UniqueConstraint("domain_id", "codigo", name="uq_ev2_rubric_domain_codigo"),
        db.Index("ix_ev2_rubrics_domain", "domain_id"),
    )


class EV2ExtraParam(db.Model):
    __tablename__ = "ev2_extra_params"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(80), nullable=False, unique=True)
    nome = db.Column(db.String(140), nullable=False)
    descricao = db.Column(db.Text)
    ativo = db.Column(db.Boolean, nullable=False, default=True, server_default=db.text("true"))


class EV2SubjectConfig(db.Model):
    __tablename__ = "ev2_subject_configs"

    id = db.Column(db.Integer, primary_key=True)
    turma_id = db.Column(db.Integer, db.ForeignKey("turmas.id"), nullable=False)
    disciplina_id = db.Column(db.Integer, db.ForeignKey("disciplinas.id"), nullable=False)
    nome = db.Column(db.String(140), nullable=False)
    ativo = db.Column(db.Boolean, nullable=False, default=True, server_default=db.text("true"))
    usar_ev2 = db.Column(db.Boolean, nullable=False, default=False, server_default=db.text("false"))
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        server_default=db.text("now()"),
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        server_default=db.text("now()"),
    )

    turma = db.relationship("Turma", backref="ev2_subject_configs")
    disciplina = db.relationship("Disciplina", back_populates="ev2_subject_configs")
    type_weights = db.relationship(
        "EV2SubjectTypeWeight",
        back_populates="subject_config",
        cascade="all, delete-orphan",
    )
    rubrics = db.relationship(
        "EV2SubjectRubric",
        back_populates="subject_config",
        cascade="all, delete-orphan",
    )
    events = db.relationship(
        "EV2Event",
        back_populates="subject_config",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        db.UniqueConstraint("turma_id", "disciplina_id", "nome", name="uq_ev2_subject_cfg_nome"),
        db.Index("ix_ev2_subject_cfg_turma_disciplina", "turma_id", "disciplina_id"),
    )


class EV2SubjectTypeWeight(db.Model):
    __tablename__ = "ev2_subject_type_weights"

    id = db.Column(db.Integer, primary_key=True)
    subject_config_id = db.Column(
        db.Integer, db.ForeignKey("ev2_subject_configs.id"), nullable=False
    )
    evaluation_type = db.Column(db.String(32), nullable=False)
    weight = db.Column(db.Numeric(5, 2), nullable=False)

    subject_config = db.relationship("EV2SubjectConfig", back_populates="type_weights")

    __table_args__ = (
        db.UniqueConstraint(
            "subject_config_id", "evaluation_type", name="uq_ev2_subject_weight_type"
        ),
        db.CheckConstraint(
            "evaluation_type IN ('observacao_direta','portfolio','projetos','trabalhos')",
            name="ck_ev2_subject_weight_type",
        ),
        db.CheckConstraint("weight >= 0 AND weight <= 100", name="ck_ev2_subject_weight_range"),
        db.Index("ix_ev2_subject_weight_config", "subject_config_id"),
    )


class EV2SubjectRubric(db.Model):
    __tablename__ = "ev2_subject_rubrics"

    id = db.Column(db.Integer, primary_key=True)
    subject_config_id = db.Column(
        db.Integer, db.ForeignKey("ev2_subject_configs.id"), nullable=False
    )
    rubric_id = db.Column(db.Integer, db.ForeignKey("ev2_rubrics.id"), nullable=False)
    weight = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    scale_min = db.Column(db.Integer, nullable=False, default=1)
    scale_max = db.Column(db.Integer, nullable=False, default=5)
    ativo = db.Column(db.Boolean, nullable=False, default=True, server_default=db.text("true"))

    subject_config = db.relationship("EV2SubjectConfig", back_populates="rubrics")
    rubrica = db.relationship("EV2Rubric", back_populates="subject_rubrics")

    __table_args__ = (
        db.UniqueConstraint(
            "subject_config_id", "rubric_id", name="uq_ev2_subject_rubric_once"
        ),
        db.CheckConstraint("weight >= 0 AND weight <= 100", name="ck_ev2_subject_rubric_weight"),
        db.CheckConstraint("scale_min < scale_max", name="ck_ev2_subject_rubric_scale"),
        db.Index("ix_ev2_subject_rubric_config", "subject_config_id"),
    )


class EV2Event(db.Model):
    __tablename__ = "ev2_events"

    id = db.Column(db.Integer, primary_key=True)
    subject_config_id = db.Column(
        db.Integer, db.ForeignKey("ev2_subject_configs.id"), nullable=False
    )
    disciplina_id = db.Column(db.Integer, db.ForeignKey("disciplinas.id"), nullable=False)
    aula_id = db.Column(db.Integer, db.ForeignKey("calendario_aulas.id"), nullable=True)
    evaluation_type = db.Column(db.String(32), nullable=False)
    numero = db.Column(db.Integer, nullable=True)
    titulo = db.Column(db.String(255), nullable=False)
    data_inicio = db.Column(db.Date, nullable=True)
    prazo_entrega = db.Column(db.Date, nullable=True)
    tema_multiplo = db.Column(db.Boolean, nullable=False, default=False, server_default=db.text("false"))
    descricao = db.Column(db.Text)
    data = db.Column(db.Date, nullable=False)
    group_mode = db.Column(db.String(20), nullable=False, default="individual", server_default="individual")
    peso_evento = db.Column(db.Numeric(5, 2), nullable=False, default=100, server_default="100")
    extra_component_weight = db.Column(db.Numeric(5, 2), nullable=False, default=0, server_default="0")
    config_snapshot = db.Column(db.JSON, nullable=False)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        server_default=db.text("now()"),
    )

    subject_config = db.relationship("EV2SubjectConfig", back_populates="events")
    disciplina = db.relationship("Disciplina", back_populates="ev2_events")
    aula = db.relationship("CalendarioAula", back_populates="ev2_events")
    students = db.relationship(
        "EV2EventStudent", back_populates="event", cascade="all, delete-orphan"
    )

    __table_args__ = (
        db.CheckConstraint(
            "evaluation_type IN ('observacao_direta','portfolio','projetos','trabalhos')",
            name="ck_ev2_event_type",
        ),
        db.CheckConstraint(
            "group_mode IN ('individual','grupo')",
            name="ck_ev2_event_group_mode",
        ),
        db.CheckConstraint(
            "peso_evento >= 0 AND peso_evento <= 100",
            name="ck_ev2_event_peso",
        ),
        db.CheckConstraint(
            "extra_component_weight >= 0 AND extra_component_weight <= 100",
            name="ck_ev2_event_extra_weight",
        ),
        db.Index("ix_ev2_events_config_data", "subject_config_id", "data"),
        db.Index("ix_ev2_events_disciplina_data", "disciplina_id", "data"),
        db.Index("ix_ev2_events_aula_type", "aula_id", "evaluation_type"),
        db.Index("ix_ev2_events_aula_data", "aula_id", "data"),
        db.Index("ix_ev2_events_tipo_numero", "evaluation_type", "numero"),
    )


class EV2AulaEventLink(db.Model):
    __tablename__ = "ev2_aula_event_links"

    id = db.Column(db.Integer, primary_key=True)
    aula_id = db.Column(db.Integer, db.ForeignKey("calendario_aulas.id"), nullable=False, index=True)
    event_id = db.Column(db.Integer, db.ForeignKey("ev2_events.id"), nullable=False, index=True)
    grupo_turma_id = db.Column(db.Integer, db.ForeignKey("grupos_turma.id"), nullable=True, index=True)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        server_default=db.text("now()"),
    )

    aula = db.relationship("CalendarioAula", backref=db.backref("ev2_event_links", cascade="all, delete-orphan"))
    event = db.relationship("EV2Event", backref=db.backref("aula_links", cascade="all, delete-orphan"))
    grupo_turma = db.relationship("GrupoTurma")

    __table_args__ = (
        db.UniqueConstraint("aula_id", "event_id", "grupo_turma_id", name="uq_ev2_aula_event_once"),
        db.Index("ix_ev2_aula_event_aula", "aula_id"),
        db.Index("ix_ev2_aula_event_event", "event_id"),
        db.Index("ix_ev2_aula_event_grupo", "grupo_turma_id"),
    )


class EV2EventStudent(db.Model):
    __tablename__ = "ev2_event_students"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("ev2_events.id"), nullable=False)
    aluno_id = db.Column(db.Integer, db.ForeignKey("alunos.id"), nullable=False)
    group_key = db.Column(db.String(80), nullable=True)
    tempos_totais = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    tempos_presentes = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    estado_assiduidade = db.Column(
        db.String(20),
        nullable=False,
        default="presente_total",
        server_default="presente_total",
    )
    pontualidade_manual = db.Column(db.Boolean, nullable=False, default=True, server_default=db.text("true"))
    elegivel_avaliacao = db.Column(db.Boolean, nullable=False, default=True, server_default=db.text("true"))
    observacoes = db.Column(db.Text)

    event = db.relationship("EV2Event", back_populates="students")
    aluno = db.relationship("Aluno", backref="ev2_event_entries")
    assessments = db.relationship(
        "EV2Assessment", back_populates="event_student", cascade="all, delete-orphan"
    )

    __table_args__ = (
        db.UniqueConstraint("event_id", "aluno_id", name="uq_ev2_event_student"),
        db.CheckConstraint("tempos_totais >= 1", name="ck_ev2_event_student_tempos_totais"),
        db.CheckConstraint(
            "tempos_presentes >= 0 AND tempos_presentes <= tempos_totais",
            name="ck_ev2_event_student_tempos_presentes",
        ),
        db.CheckConstraint(
            "estado_assiduidade IN ('presente_total','parcial','ausente_total')",
            name="ck_ev2_event_student_estado_assiduidade",
        ),
        db.Index("ix_ev2_event_students_event", "event_id"),
        db.Index("ix_ev2_event_students_aluno", "aluno_id"),
        db.Index("ix_ev2_event_students_aluno_event", "aluno_id", "event_id"),
    )


class EV2EvaluationGroup(db.Model):
    __tablename__ = "ev2_evaluation_groups"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("ev2_events.id"), nullable=False, index=True)
    nome = db.Column(db.String(120), nullable=False)
    ordem = db.Column(db.Integer, nullable=True)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        server_default=db.text("now()"),
    )

    event = db.relationship("EV2Event", backref=db.backref("evaluation_groups", cascade="all, delete-orphan"))

    __table_args__ = (
        db.UniqueConstraint("event_id", "nome", name="uq_ev2_eval_group_event_nome"),
        db.Index("ix_ev2_eval_group_event_ordem", "event_id", "ordem"),
    )


class EV2EvaluationGroupMember(db.Model):
    __tablename__ = "ev2_evaluation_group_members"

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("ev2_evaluation_groups.id"), nullable=False, index=True)
    aluno_id = db.Column(db.Integer, db.ForeignKey("alunos.id"), nullable=False, index=True)

    group = db.relationship("EV2EvaluationGroup", backref=db.backref("members", cascade="all, delete-orphan"))
    aluno = db.relationship("Aluno")

    __table_args__ = (
        db.UniqueConstraint("group_id", "aluno_id", name="uq_ev2_eval_group_member_once"),
        db.Index("ix_ev2_eval_group_member_group", "group_id"),
    )


class EV2EventTheme(db.Model):
    __tablename__ = "ev2_event_themes"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("ev2_events.id"), nullable=False, index=True)
    nome_tema = db.Column(db.String(255), nullable=False)
    descricao = db.Column(db.Text, nullable=True)
    ordem = db.Column(db.Integer, nullable=True)

    event = db.relationship("EV2Event", backref=db.backref("themes", cascade="all, delete-orphan"))

    __table_args__ = (
        db.UniqueConstraint("event_id", "nome_tema", name="uq_ev2_event_theme_nome"),
        db.Index("ix_ev2_event_theme_event_ordem", "event_id", "ordem"),
    )


class EV2AulaThemeAssignment(db.Model):
    __tablename__ = "ev2_aula_theme_assignments"

    id = db.Column(db.Integer, primary_key=True)
    aula_id = db.Column(db.Integer, db.ForeignKey("calendario_aulas.id"), nullable=False, index=True)
    event_id = db.Column(db.Integer, db.ForeignKey("ev2_events.id"), nullable=False, index=True)
    group_id = db.Column(db.Integer, db.ForeignKey("ev2_evaluation_groups.id"), nullable=False, index=True)
    theme_id = db.Column(db.Integer, db.ForeignKey("ev2_event_themes.id"), nullable=True, index=True)
    entregue = db.Column(db.Boolean, nullable=False, default=False, server_default=db.text("false"))
    data_entrega = db.Column(db.Date, nullable=True)
    observacoes = db.Column(db.Text, nullable=True)

    aula = db.relationship("CalendarioAula")
    event = db.relationship("EV2Event")
    group = db.relationship("EV2EvaluationGroup")
    theme = db.relationship("EV2EventTheme")

    __table_args__ = (
        db.UniqueConstraint("aula_id", "event_id", "group_id", name="uq_ev2_aula_theme_assignment"),
        db.Index("ix_ev2_aula_theme_assignment_aula_event", "aula_id", "event_id"),
    )


class EV2Assessment(db.Model):
    __tablename__ = "ev2_assessments"

    id = db.Column(db.Integer, primary_key=True)
    event_student_id = db.Column(
        db.Integer, db.ForeignKey("ev2_event_students.id"), nullable=False
    )
    tipo = db.Column(db.String(20), nullable=False)
    rubric_id = db.Column(
        db.Integer, db.ForeignKey("ev2_rubrics.id"), nullable=True
    )
    extra_param_id = db.Column(
        db.Integer, db.ForeignKey("ev2_extra_params.id"), nullable=True
    )
    state = db.Column(db.String(32), nullable=False, default="nao_observado", server_default="nao_observado")
    score_numeric = db.Column(db.Numeric(6, 2), nullable=True)
    weight = db.Column(db.Numeric(5, 2), nullable=False, default=0, server_default="0")
    counts_for_grade = db.Column(db.Boolean, nullable=False, default=True, server_default=db.text("true"))
    observacoes = db.Column(db.Text)

    event_student = db.relationship("EV2EventStudent", back_populates="assessments")
    rubrica = db.relationship("EV2Rubric")
    extra_param = db.relationship("EV2ExtraParam")

    __table_args__ = (
        db.CheckConstraint(
            "tipo IN ('rubrica','extra_param')",
            name="ck_ev2_assessment_tipo",
        ),
        db.CheckConstraint(
            "state IN ('avaliado','ausente','nao_observado')",
            name="ck_ev2_assessment_state",
        ),
        db.CheckConstraint("weight >= 0 AND weight <= 100", name="ck_ev2_assessment_weight"),
        db.CheckConstraint(
            "(rubric_id IS NOT NULL AND extra_param_id IS NULL) OR "
            "(rubric_id IS NULL AND extra_param_id IS NOT NULL)",
            name="ck_ev2_assessment_target_one",
        ),
        db.CheckConstraint(
            "(tipo = 'rubrica' AND rubric_id IS NOT NULL AND extra_param_id IS NULL) OR "
            "(tipo = 'extra_param' AND rubric_id IS NULL AND extra_param_id IS NOT NULL)",
            name="ck_ev2_assessment_tipo_target",
        ),
        db.CheckConstraint(
            "(state = 'avaliado' AND score_numeric IS NOT NULL) OR "
            "(state IN ('ausente','nao_observado') AND score_numeric IS NULL)",
            name="ck_ev2_assessment_state_score",
        ),
        db.UniqueConstraint(
            "event_student_id", "rubric_id", name="uq_ev2_assessment_student_rubric"
        ),
        db.UniqueConstraint(
            "event_student_id", "extra_param_id", name="uq_ev2_assessment_student_extra"
        ),
        db.Index("ix_ev2_assessments_student", "event_student_id"),
        db.Index("ix_ev2_assessments_student_tipo", "event_student_id", "tipo"),
        db.Index("ix_ev2_assessments_rubric", "rubric_id"),
        db.Index("ix_ev2_assessments_extra", "extra_param_id"),
        db.Index("ix_ev2_assessments_state", "state"),
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
    modo = db.Column(db.String(20), nullable=False, default="individual")
    data_limite = db.Column(db.Date)
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

    entregue = db.Column(db.Boolean, nullable=False, default=False)
    data_entrega = db.Column(db.Date)
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
    tipo = db.Column(db.String(20), nullable=False, default="numerico")
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


class OfflineError(db.Model):
    __tablename__ = "offline_errors"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
        index=True,
    )
    operation = db.Column(db.String(32), nullable=False)
    summary = db.Column(db.Text, nullable=False)
    details = db.Column(db.Text)
    context_json = db.Column(db.JSON, nullable=True)

    __table_args__ = (
        db.Index("ix_offline_errors_operation", "operation"),
    )


class OfflineState(db.Model):
    __tablename__ = "offline_state"

    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.Text)
