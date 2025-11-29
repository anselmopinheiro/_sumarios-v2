from app import create_app
from models import db, CalendarioAula

app = create_app()

with app.app_context():
    total = CalendarioAula.query.count()
    print(f"Vou apagar {total} linhas de CalendarioAula...")
    CalendarioAula.query.delete()
    db.session.commit()
    print("Feito. Tabela CalendarioAula está vazia.")
