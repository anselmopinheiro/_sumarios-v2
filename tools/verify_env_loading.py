import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def run_check(env_name: str) -> None:
    env_file = ROOT / f".env.{env_name}"
    if not env_file.exists():
        raise SystemExit(f"ERROR: missing environment file: {env_file}")

    values = dotenv_values(env_file)
    expected = values.get("SUPABASE_URL")
    if not expected:
        raise SystemExit(f"ERROR: SUPABASE_URL not found in {env_file}")

    for key in ["SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY"]:
        if not values.get(key):
            raise SystemExit(f"ERROR: {key} not found in {env_file}")

    cmd = [
        sys.executable,
        "-c",
        (
            "import json;"
            "from app import create_app;"
            "app=create_app();"
            "client=app.test_client();"
            "r=client.get('/health');"
            "print(json.dumps({'status': r.status_code, 'payload': r.get_json()}))"
        ),
    ]
    env = os.environ.copy()
    env["FLASK_ENV"] = env_name
    env.pop("SUPABASE_URL", None)
    env.pop("SUPABASE_ANON_KEY", None)
    env.pop("SUPABASE_SERVICE_ROLE_KEY", None)

    proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(
            f"ERROR: failed to bootstrap app for {env_name}.\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )

    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    json_line = lines[-1] if lines else ""
    try:
        result = json.loads(json_line)
    except Exception as exc:
        raise SystemExit(f"ERROR: could not parse /health response for {env_name}: {exc}\nRaw: {proc.stdout}")

    if result.get("status") != 200:
        raise SystemExit(f"ERROR: /health returned non-200 for {env_name}: {result}")

    payload = result.get("payload") or {}
    if payload.get("status") != "ok":
        raise SystemExit(f"ERROR: /health payload missing ok status for {env_name}: {payload}")

    got_url = payload.get("supabase_url")
    if got_url != expected:
        raise SystemExit(
            f"ERROR: SUPABASE_URL mismatch for {env_name}. expected={expected!r} got={got_url!r}"
        )

    print(f"{env_name} env loaded correctly")


def main() -> None:
    run_check("development")
    run_check("production")


if __name__ == "__main__":
    main()
