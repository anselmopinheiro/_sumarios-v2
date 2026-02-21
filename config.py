import importlib.util
import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

basedir = os.path.abspath(os.path.dirname(__file__))
instance_dir = os.path.join(basedir, "instance")


def _get_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _absolute_sqlite_path(path_value):
    raw = (path_value or "gestor_lectivo.db").strip()
    if os.path.isabs(raw):
        return raw
    return os.path.abspath(os.path.join(basedir, raw))


def _detect_postgres_driver():
    if importlib.util.find_spec("psycopg") is not None:
        return "psycopg"
    if importlib.util.find_spec("psycopg2") is not None:
        return "psycopg2"
    return None


def _replace_netloc_port(netloc, port):
    if not netloc or port is None:
        return netloc
    userinfo = ""
    hostport = netloc
    if "@" in netloc:
        userinfo, hostport = netloc.rsplit("@", 1)

    if hostport.startswith("[") and "]" in hostport:
        host = hostport.split("]", 1)[0] + "]"
    else:
        host = hostport.split(":", 1)[0]

    rebuilt = f"{host}:{int(port)}"
    return f"{userinfo}@{rebuilt}" if userinfo else rebuilt


def normalize_database_url(url: str) -> str:
    normalized = (url or "").strip()
    if not normalized:
        return ""

    normalized = normalized.replace("postgres://", "postgresql://", 1)

    if normalized.startswith("postgresql://"):
        driver = _detect_postgres_driver()
        if driver:
            normalized = normalized.replace("postgresql://", f"postgresql+{driver}://", 1)

    parsed = urlsplit(normalized)
    if not parsed.scheme.startswith("postgresql"):
        return normalized

    query = dict(parse_qsl(parsed.query, keep_blank_values=True))

    if "sslmode" not in query:
        query["sslmode"] = "require"

    if "connect_timeout" not in query:
        query["connect_timeout"] = str(_get_int(os.environ.get("SUPABASE_CONNECT_TIMEOUT"), 5))

    statement_timeout_ms = _get_int(os.environ.get("SUPABASE_STATEMENT_TIMEOUT_MS"), 15000)
    if "options" not in query and statement_timeout_ms > 0:
        query["options"] = f"-c statement_timeout={statement_timeout_ms}"

    mode = (os.environ.get("SUPABASE_DB_MODE") or "").strip().lower()
    desired_port = os.environ.get("SUPABASE_DB_PORT")
    if desired_port:
        desired_port = _get_int(desired_port, None)
    elif mode == "pooler":
        desired_port = 6543
    elif mode == "direct":
        desired_port = 5432
    else:
        desired_port = None

    netloc = _replace_netloc_port(parsed.netloc, desired_port)

    return urlunsplit(
        (
            parsed.scheme,
            netloc,
            parsed.path,
            urlencode(query),
            parsed.fragment,
        )
    )


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev")

    APP_DB_MODE = (os.environ.get("APP_DB_MODE", "sqlite") or "sqlite").strip().lower()
    if APP_DB_MODE not in {"sqlite", "postgres"}:
        APP_DB_MODE = "sqlite"

    SUPABASE_DB_MODE = (os.environ.get("SUPABASE_DB_MODE", "direct") or "direct").strip().lower()
    SUPABASE_DB_PORT = os.environ.get("SUPABASE_DB_PORT")
    SUPABASE_CONNECT_TIMEOUT = _get_int(os.environ.get("SUPABASE_CONNECT_TIMEOUT"), 5)
    SUPABASE_STATEMENT_TIMEOUT_MS = _get_int(os.environ.get("SUPABASE_STATEMENT_TIMEOUT_MS"), 15000)

    SQLITE_PATH = _absolute_sqlite_path(os.environ.get("SQLITE_PATH") or "gestor_lectivo.db")
    DB_PATH = SQLITE_PATH
    DATABASE_URL = os.environ.get("DATABASE_URL")

    SQLALCHEMY_DATABASE_URI = "sqlite:///" + SQLITE_PATH
    if APP_DB_MODE == "postgres" and DATABASE_URL:
        SQLALCHEMY_DATABASE_URI = normalize_database_url(DATABASE_URL)

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = os.environ.get("SQLALCHEMY_ECHO", "0") == "1"

    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 1800,
    }

    if APP_DB_MODE == "postgres":
        connect_args = {"connect_timeout": SUPABASE_CONNECT_TIMEOUT}
        if SUPABASE_STATEMENT_TIMEOUT_MS > 0:
            connect_args["options"] = f"-c statement_timeout={SUPABASE_STATEMENT_TIMEOUT_MS}"
        SQLALCHEMY_ENGINE_OPTIONS["connect_args"] = connect_args

    _backup_override = os.environ.get("DB_BACKUP_DIR")
    BACKUP_DIR = _backup_override if _backup_override and os.path.isabs(_backup_override) else os.path.join(
        instance_dir, "backups"
    )
    BACKUP_KEEP = _get_int(os.environ.get("BACKUP_KEEP", 30), 30)
    BACKUP_ON_STARTUP = os.environ.get("BACKUP_ON_STARTUP", "1") != "0"
    BACKUP_ON_COMMIT = os.environ.get("BACKUP_ON_COMMIT", "1") != "0"
    BACKUP_DEBOUNCE_SECONDS = _get_int(os.environ.get("BACKUP_DEBOUNCE_SECONDS", 300), 300)
    BACKUP_CHANGE_THRESHOLD = _get_int(os.environ.get("BACKUP_CHANGE_THRESHOLD", 15), 15)
    BACKUP_CHECK_INTERVAL_SECONDS = _get_int(os.environ.get("BACKUP_CHECK_INTERVAL_SECONDS", 30), 30)
    CSV_EXPORT_DIR = os.environ.get("CSV_EXPORT_DIR") or os.path.join(basedir, "exports")
    BACKUP_JSON_DIR = os.environ.get("BACKUP_JSON_DIR") or os.path.join(
        basedir, "exports", "backups"
    )
