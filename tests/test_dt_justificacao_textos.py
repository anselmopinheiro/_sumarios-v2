import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run_python_script(env_overrides, script):
    cmd = [sys.executable, "-c", script]
    env = os.environ.copy()
    env.update(env_overrides)
    proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, f"process failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    return json.loads(lines[-1])


def _run_flask_upgrade(env_overrides):
    env = os.environ.copy()
    env.update(env_overrides)
    cmd = ["flask", "--app", "app", "db", "upgrade"]
    proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, f"upgrade failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"


def test_dt_justificacao_textos_crud_flow():
    db_path = ROOT / "instance" / "_test_dt_justificacoes_textos.db"
    if db_path.exists():
        db_path.unlink()

    env = {
        "APP_DB_MODE": "sqlite",
        "DATABASE_URL": "",
        "FLASK_ENV": "development",
        "SQLITE_PATH": str(db_path),
        "SKIP_DB_BOOTSTRAP": "1",
    }
    _run_flask_upgrade(env)

    result = _run_python_script(
        env,
        (
            "import json;"
            "from app import create_app;"
            "app=create_app();"
            "c=app.test_client();"
            "r_add=c.post('/direcao-turma/justificacoes-texto/add', data={'titulo':'Modelo A','texto':'Justificação exemplo'}, follow_redirects=False);"
            "r_list=c.get('/direcao-turma/justificacoes-texto', follow_redirects=False);"
            "r_edit=c.post('/direcao-turma/justificacoes-texto/1/edit', data={'titulo':'Modelo B','texto':'Texto atualizado'}, follow_redirects=False);"
            "r_del=c.post('/direcao-turma/justificacoes-texto/1/delete', follow_redirects=False);"
            "print(json.dumps({'add': r_add.status_code, 'list': r_list.status_code, 'edit': r_edit.status_code, 'del': r_del.status_code, 'contains': 'Modelo A' in r_list.get_data(as_text=True)}))"
        ),
    )

    assert result["add"] in {301, 302, 303}
    assert result["list"] == 200
    assert result["edit"] in {301, 302, 303}
    assert result["del"] in {301, 302, 303}
    assert result["contains"]
