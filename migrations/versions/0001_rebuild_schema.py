"""Rebuild baseline schema with current models

Revision ID: 0001_rebuild_schema
Revises:
Create Date: 2025-06-02
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0001_rebuild_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "anos_letivos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nome", sa.String(length=20), nullable=False, unique=True),
        sa.Column("data_inicio_ano", sa.Date(), nullable=False),
        sa.Column("data_fim_ano", sa.Date(), nullable=False),
        sa.Column("data_fim_semestre1", sa.Date(), nullable=False),
        sa.Column("data_inicio_semestre2", sa.Date(), nullable=False),
        sa.Column("descricao", sa.String(length=255), nullable=True),
        sa.Column(
            "ativo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "fechado",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    op.create_table(
        "livros",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nome", sa.String(length=255), nullable=False, unique=True),
    )

    op.create_table(
        "turmas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nome", sa.String(length=50), nullable=False),
        sa.Column(
            "tipo", sa.String(length=20), nullable=False, server_default="regular"
        ),
        sa.Column("ano_letivo_id", sa.Integer(), sa.ForeignKey("anos_letivos.id")),
    )

    op.create_table(
        "disciplinas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nome", sa.String(length=100), nullable=False),
        sa.Column("sigla", sa.String(length=20)),
        sa.Column(
            "ano_letivo_id",
            sa.Integer(),
            sa.ForeignKey("anos_letivos.id"),
            nullable=False,
        ),
    )

    op.create_table(
        "feriados",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "ano_letivo_id",
            sa.Integer(),
            sa.ForeignKey("anos_letivos.id"),
            nullable=False,
        ),
        sa.Column("data", sa.Date()),
        sa.Column("data_text", sa.String(length=255)),
        sa.Column("nome", sa.String(length=255), nullable=False),
    )

    op.create_table(
        "interrupcoes_letivas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "ano_letivo_id",
            sa.Integer(),
            sa.ForeignKey("anos_letivos.id"),
            nullable=False,
        ),
        sa.Column("tipo", sa.String(length=50), nullable=False),
        sa.Column("data_inicio", sa.Date()),
        sa.Column("data_fim", sa.Date()),
        sa.Column("data_text", sa.String(length=255)),
        sa.Column("descricao", sa.String(length=255)),
    )

    op.create_table(
        "exclusoes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "turma_id", sa.Integer(), sa.ForeignKey("turmas.id"), nullable=False
        ),
        sa.Column("data", sa.Date()),
        sa.Column("data_text", sa.String(length=255)),
        sa.Column("motivo", sa.String(length=255)),
        sa.Column("tipo", sa.String(length=50)),
    )

    op.create_table(
        "extras",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "turma_id", sa.Integer(), sa.ForeignKey("turmas.id"), nullable=False
        ),
        sa.Column("data", sa.Date()),
        sa.Column("data_text", sa.String(length=255)),
        sa.Column("motivo", sa.String(length=255)),
        sa.Column("aulas", sa.Integer(), nullable=False),
        sa.Column("modulo_nome", sa.String(length=255)),
        sa.Column("tipo", sa.String(length=50)),
    )

    op.create_table(
        "horarios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "turma_id", sa.Integer(), sa.ForeignKey("turmas.id"), nullable=False
        ),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("horas", sa.Integer(), nullable=False),
    )

    op.create_table(
        "modulos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "turma_id", sa.Integer(), sa.ForeignKey("turmas.id"), nullable=False
        ),
        sa.Column("nome", sa.String(length=255), nullable=False),
        sa.Column("total_aulas", sa.Integer(), nullable=False),
        sa.Column(
            "tolerancia",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("2"),
        ),
    )

    op.create_table(
        "periodos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "turma_id", sa.Integer(), sa.ForeignKey("turmas.id"), nullable=False
        ),
        sa.Column("nome", sa.String(length=100), nullable=False),
        sa.Column(
            "tipo", sa.String(length=20), nullable=False, server_default="anual"
        ),
        sa.Column("data_inicio", sa.Date(), nullable=False),
        sa.Column("data_fim", sa.Date(), nullable=False),
        sa.Column("modulo_id", sa.Integer(), sa.ForeignKey("modulos.id")),
    )

    op.create_table(
        "turmas_disciplinas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "turma_id", sa.Integer(), sa.ForeignKey("turmas.id"), nullable=False
        ),
        sa.Column(
            "disciplina_id",
            sa.Integer(),
            sa.ForeignKey("disciplinas.id"),
            nullable=False,
        ),
        sa.Column("horas_semanais", sa.Float()),
        sa.UniqueConstraint("turma_id", "disciplina_id", name="uq_turma_disciplina"),
    )

    op.create_table(
        "livros_turmas",
        sa.Column(
            "livro_id", sa.Integer(), sa.ForeignKey("livros.id"), primary_key=True
        ),
        sa.Column(
            "turma_id", sa.Integer(), sa.ForeignKey("turmas.id"), primary_key=True
        ),
    )

    op.create_table(
        "calendario_aulas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "turma_id", sa.Integer(), sa.ForeignKey("turmas.id"), nullable=False
        ),
        sa.Column(
            "periodo_id", sa.Integer(), sa.ForeignKey("periodos.id"), nullable=False
        ),
        sa.Column("data", sa.Date(), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("modulo_id", sa.Integer(), sa.ForeignKey("modulos.id")),
        sa.Column("numero_modulo", sa.Integer()),
        sa.Column("total_geral", sa.Integer()),
        sa.Column("sumarios", sa.String(length=255)),
        sa.Column(
            "tipo", sa.String(length=50), nullable=False, server_default="normal"
        ),
        sa.Column("observacoes", sa.Text()),
        sa.Column("sumario", sa.Text()),
    )


def downgrade():
    op.drop_table("calendario_aulas")
    op.drop_table("livros_turmas")
    op.drop_table("turmas_disciplinas")
    op.drop_table("periodos")
    op.drop_table("modulos")
    op.drop_table("horarios")
    op.drop_table("extras")
    op.drop_table("exclusoes")
    op.drop_table("interrupcoes_letivas")
    op.drop_table("feriados")
    op.drop_table("disciplinas")
    op.drop_table("turmas")
    op.drop_table("livros")
    op.drop_table("anos_letivos")
