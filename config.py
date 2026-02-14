import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

basedir = os.path.abspath(os.path.dirname(__file__))
instance_dir = os.path.join(basedir, "instance")


def _get_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_database_url(url):
    if not url:
        return url

    normalized = url.replace("postgres://", "postgresql://", 1)
    if normalized.startswith("postgresql://"):
        normalized = normalized.replace("postgresql://", "postgresql+psycopg://", 1)

    parsed = urlsplit(normalized)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if "sslmode" not in query:
        query["sslmode"] = "require"

    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query),
            parsed.fragment,
        )
    )

class Config:
    SECRET_KEY = "dev"
    SQLITE_PATH = os.environ.get("SQLITE_PATH") or os.path.join(instance_dir, "gestor_lectivo.db")
    DATABASE_URL = os.environ.get("DATABASE_URL")
    DB_PATH = SQLITE_PATH
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + DB_PATH
    if DATABASE_URL:
        SQLALCHEMY_DATABASE_URI = normalize_database_url(DATABASE_URL)

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 1800,
    }
    _backup_override = os.environ.get("DB_BACKUP_DIR")
    BACKUP_DIR = _backup_override if _backup_override and os.path.isabs(_backup_override) else os.path.join(
        instance_dir, "backups"
    )
    BACKUP_KEEP = _get_int(os.environ.get("BACKUP_KEEP", 30), 30)
    BACKUP_ON_STARTUP = os.environ.get("BACKUP_ON_STARTUP", "1") != "0"
    BACKUP_ON_COMMIT = os.environ.get("BACKUP_ON_COMMIT", "1") != "0"
    BACKUP_DEBOUNCE_SECONDS = _get_int(os.environ.get("BACKUP_DEBOUNCE_SECONDS", 300), 300)
    BACKUP_CHANGE_THRESHOLD = _get_int(os.environ.get("BACKUP_CHANGE_THRESHOLD", 15), 15)
    BACKUP_CHECK_INTERVAL_SECONDS = _get_int(
        os.environ.get("BACKUP_CHECK_INTERVAL_SECONDS", 30), 30
    )
    CSV_EXPORT_DIR = os.environ.get("CSV_EXPORT_DIR") or os.path.join(basedir, "exports")
    BACKUP_JSON_DIR = os.environ.get("BACKUP_JSON_DIR") or os.path.join(
        basedir, "exports", "backups"
    )
