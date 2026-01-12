import os
basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = "dev"
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(basedir, "gestor_lectivo.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    BACKUP_DIR = os.environ.get("DB_BACKUP_DIR") or os.path.join(basedir, "backups")
    CSV_EXPORT_DIR = os.environ.get("CSV_EXPORT_DIR") or os.path.join(basedir, "exports")
    BACKUP_JSON_DIR = os.environ.get("BACKUP_JSON_DIR") or os.path.join(
        basedir, "exports", "backups"
    )
