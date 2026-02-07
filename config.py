import os
basedir = os.path.abspath(os.path.dirname(__file__))
instance_dir = os.path.join(basedir, "instance")


def _get_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

class Config:
    SECRET_KEY = "dev"
    DB_PATH = os.path.join(instance_dir, "gestor_lectivo.db")
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + DB_PATH
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    _backup_override = os.environ.get("DB_BACKUP_DIR")
    BACKUP_DIR = _backup_override if _backup_override and os.path.isabs(_backup_override) else os.path.join(
        instance_dir, "backups"
    )
    BACKUP_KEEP = _get_int(os.environ.get("BACKUP_KEEP", 30), 30)
    BACKUP_ON_STARTUP = os.environ.get("BACKUP_ON_STARTUP", "1") != "0"
    BACKUP_ON_COMMIT = os.environ.get("BACKUP_ON_COMMIT", "1") != "0"
    CSV_EXPORT_DIR = os.environ.get("CSV_EXPORT_DIR") or os.path.join(basedir, "exports")
    BACKUP_JSON_DIR = os.environ.get("BACKUP_JSON_DIR") or os.path.join(
        basedir, "exports", "backups"
    )
