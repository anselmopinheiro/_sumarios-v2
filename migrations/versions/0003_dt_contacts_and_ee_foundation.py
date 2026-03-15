"""add DT/EE/contacts foundation tables and aluno stable fields

Revision ID: 0003_dt_contacts_and_ee_foundation
Revises: 0002_dt_justificacao_textos
Create Date: 2026-03-14
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_dt_contacts_and_ee_foundation"
down_revision = "0002_dt_justificacao_textos"
branch_labels = None
depends_on = None


TIPOS_CONTACTO = [
    "Telefónico",
    "Email",
    "Presencial",
    "Carta registada",
    "Reunião online",
    "Outro",
]

MOTIVOS_CONTACTO = [
    "Participação disciplinar",
    "Mau comportamento",
    "TPC por fazer",
    "Falta de trabalho",
    "Faltas injustificadas",
    "Assiduidade",
    "Pontualidade",
    "Aproveitamento",
    "Informação geral",
    "Reunião",
    "Elogio",
    "Outro",
]


def _has_column(inspector, table_name, column_name):
    cols = {c["name"] for c in inspector.get_columns(table_name)}
    return column_name in cols


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    with op.batch_alter_table("alunos") as batch_op:
        if not _has_column(inspector, "alunos", "data_nascimento"):
            batch_op.add_column(sa.Column("data_nascimento", sa.Date(), nullable=True))
        if not _has_column(inspector, "alunos", "tipo_identificacao"):
            batch_op.add_column(sa.Column("tipo_identificacao", sa.String(length=30), nullable=True))
        if not _has_column(inspector, "alunos", "numero_identificacao"):
            batch_op.add_column(sa.Column("numero_identificacao", sa.String(length=80), nullable=True))
        if not _has_column(inspector, "alunos", "email"):
            batch_op.add_column(sa.Column("email", sa.String(length=255), nullable=True))
        if not _has_column(inspector, "alunos", "telefone"):
            batch_op.add_column(sa.Column("telefone", sa.String(length=40), nullable=True))
        if not _has_column(inspector, "alunos", "numero_utente_sns"):
            batch_op.add_column(sa.Column("numero_utente_sns", sa.String(length=40), nullable=True))
        if not _has_column(inspector, "alunos", "numero_processo"):
            batch_op.add_column(sa.Column("numero_processo", sa.String(length=50), nullable=True))

    op.create_table(
        "aluno_contexto_dt",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("aluno_id", sa.Integer(), nullable=False),
        sa.Column("dt_observacoes", sa.Text(), nullable=True),
        sa.Column("ee_observacoes", sa.Text(), nullable=True),
        sa.Column("alerta_dt", sa.Text(), nullable=True),
        sa.Column("resumo_sinalizacao", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["aluno_id"], ["alunos.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("aluno_id", name="uq_aluno_contexto_dt_aluno"),
    )

    op.create_table(
        "ee",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nome", sa.String(length=255), nullable=False),
        sa.Column("telefone", sa.String(length=40), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("observacoes", sa.Text(), nullable=True),
        sa.Column("nome_alternativo", sa.String(length=255), nullable=True),
        sa.Column("telefone_alternativo", sa.String(length=40), nullable=True),
        sa.Column("email_alternativo", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "ee_alunos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ee_id", sa.Integer(), nullable=False),
        sa.Column("aluno_id", sa.Integer(), nullable=False),
        sa.Column("parentesco", sa.String(length=80), nullable=True),
        sa.Column("observacoes", sa.Text(), nullable=True),
        sa.Column("data_inicio", sa.Date(), nullable=False),
        sa.Column("data_fim", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["ee_id"], ["ee.id"]),
        sa.ForeignKeyConstraint(["aluno_id"], ["alunos.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ee_alunos_ee_id", "ee_alunos", ["ee_id"])
    op.create_index("ix_ee_alunos_aluno_id", "ee_alunos", ["aluno_id"])

    op.create_table(
        "dt_cargos_alunos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dt_turma_id", sa.Integer(), nullable=False),
        sa.Column("aluno_id", sa.Integer(), nullable=False),
        sa.Column("cargo", sa.String(length=40), nullable=False),
        sa.Column("data_inicio", sa.Date(), nullable=False),
        sa.Column("data_fim", sa.Date(), nullable=True),
        sa.Column("motivo_fim", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["dt_turma_id"], ["dt_turmas.id"]),
        sa.ForeignKeyConstraint(["aluno_id"], ["alunos.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dt_cargos_alunos_dt_turma_id", "dt_cargos_alunos", ["dt_turma_id"])
    op.create_index("ix_dt_cargos_alunos_aluno_id", "dt_cargos_alunos", ["aluno_id"])

    op.create_table(
        "dt_cargos_ee",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dt_turma_id", sa.Integer(), nullable=False),
        sa.Column("ee_id", sa.Integer(), nullable=False),
        sa.Column("cargo", sa.String(length=60), nullable=False),
        sa.Column("data_inicio", sa.Date(), nullable=False),
        sa.Column("data_fim", sa.Date(), nullable=True),
        sa.Column("motivo_fim", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["dt_turma_id"], ["dt_turmas.id"]),
        sa.ForeignKeyConstraint(["ee_id"], ["ee.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dt_cargos_ee_dt_turma_id", "dt_cargos_ee", ["dt_turma_id"])
    op.create_index("ix_dt_cargos_ee_ee_id", "dt_cargos_ee", ["ee_id"])

    op.create_table(
        "tipo_contacto",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nome", sa.String(length=100), nullable=False),
        sa.Column("ordem", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nome", name="uq_tipo_contacto_nome"),
    )

    op.create_table(
        "motivo_contacto",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nome", sa.String(length=120), nullable=False),
        sa.Column("ordem", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nome", name="uq_motivo_contacto_nome"),
    )

    op.create_table(
        "contactos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ee_id", sa.Integer(), nullable=False),
        sa.Column("dt_turma_id", sa.Integer(), nullable=False),
        sa.Column("data_hora", sa.DateTime(), nullable=False),
        sa.Column("iniciado_por", sa.String(length=20), nullable=False),
        sa.Column("resumo", sa.Text(), nullable=True),
        sa.Column("observacoes_gerais", sa.Text(), nullable=True),
        sa.Column("estado_contacto", sa.String(length=40), nullable=False),
        sa.Column("estado_reuniao", sa.String(length=40), nullable=False),
        sa.Column("data_reuniao", sa.DateTime(), nullable=True),
        sa.Column("requer_followup", sa.Boolean(), nullable=False),
        sa.Column("data_followup", sa.Date(), nullable=True),
        sa.Column("confidencial", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["ee_id"], ["ee.id"]),
        sa.ForeignKeyConstraint(["dt_turma_id"], ["dt_turmas.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contactos_ee_id", "contactos", ["ee_id"])
    op.create_index("ix_contactos_dt_turma_id", "contactos", ["dt_turma_id"])

    op.create_table(
        "contacto_tipos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contacto_id", sa.Integer(), nullable=False),
        sa.Column("tipo_contacto_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["contacto_id"], ["contactos.id"]),
        sa.ForeignKeyConstraint(["tipo_contacto_id"], ["tipo_contacto.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contacto_id", "tipo_contacto_id", name="uq_contacto_tipo_unique"),
    )

    op.create_table(
        "contacto_alunos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contacto_id", sa.Integer(), nullable=False),
        sa.Column("aluno_id", sa.Integer(), nullable=False),
        sa.Column("ee_aluno_id_snapshot", sa.Integer(), nullable=True),
        sa.Column("observacoes", sa.Text(), nullable=True),
        sa.Column("resultado_individual", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["contacto_id"], ["contactos.id"]),
        sa.ForeignKeyConstraint(["aluno_id"], ["alunos.id"]),
        sa.ForeignKeyConstraint(["ee_aluno_id_snapshot"], ["ee_alunos.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "contacto_aluno_motivos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contacto_aluno_id", sa.Integer(), nullable=False),
        sa.Column("motivo_contacto_id", sa.Integer(), nullable=False),
        sa.Column("detalhe", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["contacto_aluno_id"], ["contacto_alunos.id"]),
        sa.ForeignKeyConstraint(["motivo_contacto_id"], ["motivo_contacto.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "contacto_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contacto_id", sa.Integer(), nullable=False),
        sa.Column("titulo", sa.String(length=255), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("tipo", sa.String(length=80), nullable=True),
        sa.Column("observacoes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["contacto_id"], ["contactos.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    tipo_tbl = sa.table("tipo_contacto", sa.column("nome", sa.String), sa.column("ordem", sa.Integer))
    motivo_tbl = sa.table("motivo_contacto", sa.column("nome", sa.String), sa.column("ordem", sa.Integer))

    for idx, nome in enumerate(TIPOS_CONTACTO, start=1):
        exists = bind.execute(sa.text("SELECT 1 FROM tipo_contacto WHERE nome = :nome"), {"nome": nome}).fetchone()
        if not exists:
            op.bulk_insert(tipo_tbl, [{"nome": nome, "ordem": idx}])

    for idx, nome in enumerate(MOTIVOS_CONTACTO, start=1):
        exists = bind.execute(sa.text("SELECT 1 FROM motivo_contacto WHERE nome = :nome"), {"nome": nome}).fetchone()
        if not exists:
            op.bulk_insert(motivo_tbl, [{"nome": nome, "ordem": idx}])


def downgrade():
    op.drop_table("contacto_links")
    op.drop_table("contacto_aluno_motivos")
    op.drop_table("contacto_alunos")
    op.drop_table("contacto_tipos")
    op.drop_index("ix_contactos_dt_turma_id", table_name="contactos")
    op.drop_index("ix_contactos_ee_id", table_name="contactos")
    op.drop_table("contactos")
    op.drop_table("motivo_contacto")
    op.drop_table("tipo_contacto")
    op.drop_index("ix_dt_cargos_ee_ee_id", table_name="dt_cargos_ee")
    op.drop_index("ix_dt_cargos_ee_dt_turma_id", table_name="dt_cargos_ee")
    op.drop_table("dt_cargos_ee")
    op.drop_index("ix_dt_cargos_alunos_aluno_id", table_name="dt_cargos_alunos")
    op.drop_index("ix_dt_cargos_alunos_dt_turma_id", table_name="dt_cargos_alunos")
    op.drop_table("dt_cargos_alunos")
    op.drop_index("ix_ee_alunos_aluno_id", table_name="ee_alunos")
    op.drop_index("ix_ee_alunos_ee_id", table_name="ee_alunos")
    op.drop_table("ee_alunos")
    op.drop_table("ee")
    op.drop_table("aluno_contexto_dt")

    with op.batch_alter_table("alunos") as batch_op:
        batch_op.drop_column("numero_processo")
        batch_op.drop_column("numero_utente_sns")
        batch_op.drop_column("telefone")
        batch_op.drop_column("email")
        batch_op.drop_column("numero_identificacao")
        batch_op.drop_column("tipo_identificacao")
        batch_op.drop_column("data_nascimento")
