from datetime import date

from app import create_app
from models import db, AnoLetivo, InterrupcaoLetiva, Feriado

app = create_app()

with app.app_context():
    ano = AnoLetivo.query.first()
    if not ano:
        print("⚠ Não existe nenhum Ano Letivo. Cria um primeiro na interface ou no seed.")
        raise SystemExit(1)

    print(f"Vou usar o Ano Letivo: {ano.nome}")

    # Limpar interrupções e feriados anteriores deste ano letivo (para poderes repetir o seed)
    InterrupcaoLetiva.query.filter_by(ano_letivo_id=ano.id).delete()
    Feriado.query.filter_by(ano_letivo_id=ano.id).delete()
    db.session.commit()

    # -------------------------
    # INTERPUPÇÕES LETIVAS
    # -------------------------

    interrupcoes = [
        # NATAL
        InterrupcaoLetiva(
            ano_letivo_id=ano.id,
            tipo="natal",
            # podes deixar data_inicio/data_fim a None e usar só data_text;
            # o motor usa sempre data_text se existir
            data_inicio=None,
            data_fim=None,
            data_text="22 de dezembro de 2025 a 2 de janeiro de 2026",
            descricao="Interrupção de Natal",
        ),

        # CARNAVAL (exemplo: dois dias)
        InterrupcaoLetiva(
            ano_letivo_id=ano.id,
            tipo="carnaval",
            data_inicio=None,
            data_fim=None,
            data_text="16 e 17 de fevereiro de 2026",
            descricao="Interrupção de Carnaval",
        ),

        # INTERCALAR 1 (exemplo: semana em outubro)
        InterrupcaoLetiva(
            ano_letivo_id=ano.id,
            tipo="intercalar1",
            data_inicio=None,
            data_fim=None,
            data_text="27 de outubro de 2025 a 31 de outubro de 2025",
            descricao="Interrupção do 1.º período (exemplo)",
        ),

        # PÁSCOA (exemplo: fim de março a início de abril)
        InterrupcaoLetiva(
            ano_letivo_id=ano.id,
            tipo="pascoa",
            data_inicio=None,
            data_fim=None,
            data_text="30 de março de 2026 a 10 de abril de 2026",
            descricao="Interrupção da Páscoa (exemplo)",
        ),

        # INTERCALAR 2 (exemplo: antes da Páscoa)
        InterrupcaoLetiva(
            ano_letivo_id=ano.id,
            tipo="intercalar2",
            data_inicio=None,
            data_fim=None,
            data_text="9 de fevereiro de 2026 a 13 de fevereiro de 2026",
            descricao="Interrupção intermédia (exemplo)",
        ),
    ]

    db.session.add_all(interrupcoes)

    # -------------------------
    # FERIADOS (exemplos)
    # -------------------------

    feriados = [
        Feriado(
            ano_letivo_id=ano.id,
            nome="Implantação da República",
            data=date(2025, 10, 5),
            data_text=None,
        ),
        Feriado(
            ano_letivo_id=ano.id,
            nome="Todos os Santos",
            data=date(2025, 11, 1),
            data_text=None,
        ),
        Feriado(
            ano_letivo_id=ano.id,
            nome="Restauração da Independência",
            data=date(2025, 12, 1),
            data_text=None,
        ),
        Feriado(
            ano_letivo_id=ano.id,
            nome="Imaculada Conceição",
            data=date(2025, 12, 8),
            data_text=None,
        ),
        Feriado(
            ano_letivo_id=ano.id,
            nome="Ano Novo",
            data=date(2026, 1, 1),
            data_text=None,
        ),
        Feriado(
            ano_letivo_id=ano.id,
            nome="25 de Abril",
            data=date(2026, 4, 25),
            data_text=None,
        ),
    ]

    db.session.add_all(feriados)
    db.session.commit()

    print("✅ Interrupções e feriados criados para", ano.nome)
