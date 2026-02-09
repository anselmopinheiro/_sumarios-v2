# api/index.py
import os
import sys
import traceback

# garante que a raiz do projeto está no sys.path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    # opção 1: tens app = Flask(...)
    from app import app  # muda "app" para o teu módulo real (ex.: from src.app import app)

    # opção 2: tens create_app()
    # from app import create_app
    # app = create_app()

except Exception:
    print("Erro ao importar a aplicação Flask:")
    traceback.print_exc()
    raise

@app.get("/health")
def health():
    return {"status": "ok"}
