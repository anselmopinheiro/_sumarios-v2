from app import create_app
from models import db, Livro, Turma, Periodo, CalendarioAula

app = create_app()

with app.app_context():
    print("=== LIVROS ===")
    for livro in Livro.query.all():
        print(f"- {livro.id}: {livro.nome}")

    print("\n=== TURMAS ===")
    for turma in Turma.query.all():
        print(f"- {turma.id}: {turma.nome} ({turma.tipo})")

    print("\n=== PERÍODOS ===")
    for p in Periodo.query.all():
        print(f"- Turma {p.turma_id}: {p.nome} {p.data_inicio} a {p.data_fim}")

    total_aulas = CalendarioAula.query.count()
    print(f"\n=== CALENDÁRIO AULAS ===")
    print(f"Total de linhas em CalendarioAula: {total_aulas}")

    if total_aulas > 0:
        amostras = CalendarioAula.query.order_by(CalendarioAula.data).limit(10).all()
        for a in amostras:
            print(
                f"{a.data} | Turma {a.turma_id} | {a.modulo_nome} | "
                f"Nº módulo: {a.n_aula_modulo} | Total: {a.total_aulas} | "
                f"Sumário: {a.n_sumario} | Tipo: {a.tipo_dia}"
            )
