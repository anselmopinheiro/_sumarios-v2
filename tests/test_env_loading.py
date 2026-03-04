import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def _assert_env(env_name: str):
    env_file = ROOT / f".env.{env_name}"
    assert env_file.exists(), f"missing env file: {env_file}"

    values = dotenv_values(env_file)
    expected_url = values.get("SUPABASE_URL")
    assert expected_url, f"SUPABASE_URL missing in {env_file}"
    assert values.get("SUPABASE_ANON_KEY"), f"SUPABASE_ANON_KEY missing in {env_file}"
    assert values.get("SUPABASE_SERVICE_ROLE_KEY"), f"SUPABASE_SERVICE_ROLE_KEY missing in {env_file}"

    cmd = [
        sys.executable,
        "-c",
        (
            "import json, os;"
            "from app import create_app;"
            "a=create_app();"
            "r=a.test_client().get('/health');"
            "print(json.dumps({'status': r.status_code, 'payload': r.get_json(), 'env_url': os.getenv('SUPABASE_URL')}))"
        ),
    ]
    env = os.environ.copy()
    env["FLASK_ENV"] = env_name
    env.pop("SUPABASE_URL", None)
    env.pop("SUPABASE_ANON_KEY", None)
    env.pop("SUPABASE_SERVICE_ROLE_KEY", None)

    proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, f"app bootstrap failed for {env_name}: {proc.stdout}\n{proc.stderr}"

    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    raw = lines[-1] if lines else ""
    data = json.loads(raw)

    assert data["status"] == 200
    assert data["payload"]["status"] == "ok"
    assert data["env_url"] == expected_url, (
        f"SUPABASE_URL not loaded correctly for {env_name}: "
        f"expected {expected_url!r}, got {data['env_url']!r}"
    )
    assert data["payload"]["supabase_url"] == expected_url


def test_development_env_loaded_correctly():
    _assert_env("development")


def test_production_env_loaded_correctly():
    _assert_env("production")
