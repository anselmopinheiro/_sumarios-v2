from datetime import date
from app import create_app
from models import (
    db,
    AnoLetivo,
    Livro,
    Turma,
    Horario,
    Modulo,
    Periodo,
    Disciplina,
)

app = create_app()

with app.app_context():
    print("=== SEED: início ===")

    # 1) Ano Letivo
    nome_ano = "2025/2026"
    ano = AnoLetivo.query.filter_by(nome=nome_ano).first()
    if not ano:
        ano = AnoLetivo(
            nome=nome_ano,
            data_inicio_ano=date(2025, 9, 1),
            data_fim_ano=date(2026, 7, 31),
            data_fim_semestre1=date(2026, 1, 31),
            data_inicio_semestre2=date(2026, 2, 1),
            descricao="Ano letivo de teste para o Gestor Lectivo",
            ativo=True,
            fechado=False,
        )
        db.session.add(ano)
        print(f"Criado Ano Letivo: {nome_ano}")
    else:
        print(f"Ano Letivo já existe: {nome_ano}")
        if not ano.ativo:
            ano.ativo = True
            print("Marcado como ano letivo ativo.")

    db.session.flush()

    # 2) Livro
    nome_livro = "sumarios_2025_2026"
    livro = Livro.query.filter_by(nome=nome_livro).first()
    if not livro:
        livro = Livro(nome=nome_livro)
        db.session.add(livro)
        print(f"Criado Livro: {nome_livro}")
    else:
        print(f"Livro já existe: {nome_livro}")

    db.session.flush()

    # 3) Turma
    nome_turma = "9.º D"
    turma = (
        Turma.query
        .filter_by(nome=nome_turma, ano_letivo_id=ano.id)
        .first()
    )
    if not turma:
        turma = Turma(
            nome=nome_turma,
            tipo="profissional",
            ano_letivo_id=ano.id,
        )
        db.session.add(turma)
        print(f"Criada Turma: {nome_turma}")
    else:
        print(f"Turma já existe: {nome_turma}")
        if turma.ano_letivo_id is None:
            turma.ano_letivo_id = ano.id
            print("Associado ano letivo à turma existente.")

    db.session.flush()

    # 3.1) Associar livro à turma (tabela livros_turmas)
    if turma not in livro.turmas:
        livro.turmas.append(turma)
        print("Associada Turma ao Livro.")

    db.session.flush()

    # 4) Limpar Horários, Módulos e Períodos anteriores desta turma (caso existam)
    Horario.query.filter_by(turma_id=turma.id).delete()
    Modulo.query.filter_by(turma_id=turma.id).delete()
    Periodo.query.filter_by(turma_id=turma.id).delete()
    db.session.commit()
    print("Horários, Módulos e Períodos antigos desta turma foram limpos.")

    # 5) Criar Horário
    # 0=Seg, 1=Ter, 2=Qua, 3=Qui, 4=Sex
    horarios_dados = [
        (0, 3),  # Segunda-feira: 3 aulas
        (2, 3),  # Quarta-feira: 3 aulas
    ]

    for weekday, horas in horarios_dados:
        h = Horario(
            turma_id=turma.id,
            weekday=weekday,
            horas=horas,
        )
        db.session.add(h)
        print(f"Horário criado: weekday={weekday}, horas={horas}")

    # 6) Criar Módulos (exemplo)
    modulos_dados = [
        ("Módulo 1 - Introdução", 15, 2),
        ("Módulo 2 - Conceitos Avançados", 20, 2),
    ]

    for nome_mod, total, tolerancia in modulos_dados:
        m = Modulo(
            turma_id=turma.id,
            nome=nome_mod,
            total_aulas=total,
            tolerancia=tolerancia,
        )
        db.session.add(m)
        print(f"Módulo criado: {nome_mod} ({total} aulas, tolerância {tolerancia})")

    # 7) Criar Período anual
    periodo = Periodo(
        turma_id=turma.id,
        nome="Anual",
        data_inicio=date(2025, 9, 15),
        data_fim=date(2026, 6, 30),
    )
    db.session.add(periodo)
    print("Período 'Anual' criado para a turma.")

    # 8) Disciplinas do Ano Letivo e associação à Turma
    disciplinas_def = [
        ("Tecnologias de Informação e Comunicação", "TIC"),
        ("Produção Multimédia", "PM"),
        ("Jornalismo e Comunicação", "JC"),
    ]

    disciplinas_criadas = []
    for nome_disc, sigla in disciplinas_def:
        disc = (
            Disciplina.query
            .filter_by(nome=nome_disc, ano_letivo_id=ano.id)
            .first()
        )
        if not disc:
            disc = Disciplina(
                nome=nome_disc,
                sigla=sigla,
                ano_letivo_id=ano.id,
            )
            db.session.add(disc)
            disciplinas_criadas.append(nome_disc)
        # associar à turma (many-to-many)
        if disc not in turma.disciplinas:
            turma.disciplinas.append(disc)
            print(f"Associada disciplina '{nome_disc}' à turma {turma.nome}.")

    if disciplinas_criadas:
        print("Disciplinas criadas:", ", ".join(disciplinas_criadas))
    else:
        print("Disciplinas já existiam para este ano letivo.")

    db.session.commit()
    print("=== SEED concluído com sucesso. ===")
