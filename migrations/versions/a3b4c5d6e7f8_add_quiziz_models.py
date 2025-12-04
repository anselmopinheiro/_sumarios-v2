"""Add quiziz tables and turma access code"""
"""Add quiziz tables and turma access code"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a3b4c5d6e7f8"
down_revision = "1d4f9c0e9c2d"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    turma_columns = {col["name"] for col in inspector.get_columns("turmas")}
    if "codigo_acesso" not in turma_columns:
        op.add_column(
            "turmas",
            sa.Column("codigo_acesso", sa.String(length=20), unique=True),
        )

    op.create_table(
        "alunos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nickname", sa.String(length=80), nullable=False),
        sa.Column("turma_id", sa.Integer(), sa.ForeignKey("turmas.id"), nullable=False),
        sa.Column("criado_em", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("turma_id", "nickname", name="uq_aluno_nickname_turma"),
    )

    op.create_table(
        "quizzes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("titulo", sa.String(length=255), nullable=False),
        sa.Column("turma_id", sa.Integer(), sa.ForeignKey("turmas.id"), nullable=False),
        sa.Column("criado_em", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "quiz_questions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("quiz_id", sa.Integer(), sa.ForeignKey("quizzes.id"), nullable=False),
        sa.Column("texto", sa.String(length=500), nullable=False),
    )

    op.create_table(
        "quiz_options",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("question_id", sa.Integer(), sa.ForeignKey("quiz_questions.id"), nullable=False),
        sa.Column("texto", sa.String(length=255), nullable=False),
        sa.Column("correta", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "quiz_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("quiz_id", sa.Integer(), sa.ForeignKey("quizzes.id"), nullable=False),
        sa.Column("aluno_id", sa.Integer(), sa.ForeignKey("alunos.id"), nullable=False),
        sa.Column("iniciado_em", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("concluido_em", sa.DateTime(), nullable=True),
        sa.Column("pontuacao", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_perguntas", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("quiz_id", "aluno_id", name="uq_quiz_aluno"),
    )

    op.create_table(
        "quiz_answers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("attempt_id", sa.Integer(), sa.ForeignKey("quiz_attempts.id"), nullable=False),
        sa.Column("question_id", sa.Integer(), sa.ForeignKey("quiz_questions.id"), nullable=False),
        sa.Column("option_id", sa.Integer(), sa.ForeignKey("quiz_options.id"), nullable=False),
        sa.Column("correta", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_table("quiz_answers")
    op.drop_table("quiz_attempts")
    op.drop_table("quiz_options")
    op.drop_table("quiz_questions")
    op.drop_table("quizzes")
    op.drop_table("alunos")

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    turma_columns = {col["name"] for col in inspector.get_columns("turmas")}
    if "codigo_acesso" in turma_columns:
        op.drop_column("turmas", "codigo_acesso")
