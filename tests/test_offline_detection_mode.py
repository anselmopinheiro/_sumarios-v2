import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run_python_request(env_overrides):
    cmd = [
        sys.executable,
        "-c",
        (
            "import json;"
            "from app import create_app;"
            "app=create_app();"
            "r=app.test_client().get('/', follow_redirects=False);"
            "print(json.dumps({'status': r.status_code, 'location': r.headers.get('Location')}))"
        ),
    ]
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


def test_sqlite_mode_does_not_redirect_to_offline_and_returns_200():
    db_path = ROOT / 'instance' / '_test_sqlite_mode.db'
    if db_path.exists():
        db_path.unlink()

    env = {
        "SKIP_DB_BOOTSTRAP": "1",
        "APP_DB_MODE": "sqlite",
        "DATABASE_URL": "",
        "FLASK_ENV": "development",
        "SQLITE_PATH": str(db_path),
    }
    _run_flask_upgrade(env)
    result = _run_python_request(env)

    assert result["status"] == 200
    assert result["location"] is None or "/offline" not in (result["location"] or "")


def test_postgres_mode_invalid_remote_redirects_to_offline():
    result = _run_python_request(
        {
            "SKIP_DB_BOOTSTRAP": "1",
            "APP_DB_MODE": "postgres",
            "DATABASE_URL": "postgresql+psycopg://invalid:invalid@127.0.0.1:1/postgres",
            "SUPABASE_CONNECT_TIMEOUT": "1",
            "SUPABASE_STATEMENT_TIMEOUT_MS": "1000",
            "FLASK_ENV": "development",
        }
    )
    assert result["status"] in {301, 302, 307, 308}
    assert "/offline" in (result["location"] or "")
