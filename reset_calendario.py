from app import create_app
from models import db, CalendarioAula

app = create_app()

with app.app_context():
    total = CalendarioAula.query.filter_by(deleted=False).count()
    print(f"Vou marcar {total} linhas de CalendarioAula como apagadas...")
    CalendarioAula.query.update({"deleted": True})
    db.session.commit()
    restantes = CalendarioAula.query.filter_by(deleted=False).count()
    print(f"Feito. Linhas ativas restantes: {restantes}.")
