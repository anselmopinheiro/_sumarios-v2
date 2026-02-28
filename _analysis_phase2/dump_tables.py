from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def set_safe_env() -> None:
    os.environ.setdefault("SECRET_KEY", "dev")
    os.environ.setdefault("APP_DB_MODE", "sqlite")
    os.environ.setdefault("SQLITE_PATH", "instance/_analysis_models.db")
    os.environ.setdefault("OFFLINE_DB_PATH", "instance/_analysis_offline.db")


def load_metadata():
    set_safe_env()
    try:
        from models import db  # type: ignore

        metadata = db.metadata
        return metadata
    except Exception:
        from app import create_app  # type: ignore

        app = create_app()
        app.app_context().push()
        from models import db  # type: ignore

        return db.metadata


def table_stats(table):
    has_fk = any(col.foreign_keys for col in table.columns)
    has_unique = any(getattr(c, "unique", False) for c in table.columns) or any(
        c.__class__.__name__ == "UniqueConstraint" for c in table.constraints
    )
    has_indexes = bool(table.indexes)
    return {
        "table_name": table.name,
        "columns_count": len(table.columns),
        "has_fk": int(bool(has_fk)),
        "has_unique": int(bool(has_unique)),
        "has_indexes": int(bool(has_indexes)),
    }


def main() -> None:
    out_dir = Path("_analysis_phase2")
    out_dir.mkdir(parents=True, exist_ok=True)
    metadata = load_metadata()
    rows = [table_stats(t) for t in metadata.sorted_tables]

    out_csv = out_dir / "TABLES_IN_METADATA.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "table_name",
                "columns_count",
                "has_fk",
                "has_unique",
                "has_indexes",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} tables to {out_csv}")


if __name__ == "__main__":
    main()
