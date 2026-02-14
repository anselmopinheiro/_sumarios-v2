#!/usr/bin/env python3
import argparse
import json
import sqlite3
from pathlib import Path


def _parse_args():
    parser = argparse.ArgumentParser(description="Exporta schema SQLite para JSON.")
    parser.add_argument("--sqlite-path", default="gestor_lectivo.db", help="Ficheiro SQLite origem")
    parser.add_argument("--output", default="tools/schema_sqlite.json", help="JSON de saída")
    return parser.parse_args()


def _get_tables(conn):
    cur = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    )
    return [row[0] for row in cur.fetchall()]


def _extract_table(conn, table_name):
    cols = []
    for cid, name, col_type, notnull, default, pk in conn.execute(f"PRAGMA table_info('{table_name}')"):
        cols.append(
            {
                "name": name,
                "type": col_type,
                "nullable": not bool(notnull),
                "default": default,
                "primary_key": bool(pk),
            }
        )

    pk_cols = [c["name"] for c in cols if c["primary_key"]]

    fks = []
    for row in conn.execute(f"PRAGMA foreign_key_list('{table_name}')"):
        fks.append(
            {
                "name": None,
                "constrained_columns": [row[3]],
                "referred_table": row[2],
                "referred_columns": [row[4]],
                "on_update": row[5],
                "on_delete": row[6],
            }
        )

    indexes = []
    uniques = []
    for idx in conn.execute(f"PRAGMA index_list('{table_name}')"):
        idx_name = idx[1]
        if idx_name.startswith("sqlite_autoindex"):
            continue
        unique = bool(idx[2])
        cols_idx = [r[2] for r in conn.execute(f"PRAGMA index_info('{idx_name}')").fetchall()]
        indexes.append({"name": idx_name, "unique": unique, "column_names": cols_idx})
        if unique:
            uniques.append({"name": idx_name, "column_names": cols_idx})

    return {
        "name": table_name,
        "columns": cols,
        "primary_key": {"name": None, "constrained_columns": pk_cols},
        "foreign_keys": fks,
        "unique_constraints": uniques,
        "indexes": indexes,
    }


def main():
    args = _parse_args()
    sqlite_path = Path(args.sqlite_path)
    if not sqlite_path.exists():
        raise SystemExit(f"SQLite não encontrado: {sqlite_path}")

    with sqlite3.connect(sqlite_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        payload = {
            "source": str(sqlite_path),
            "tables": [_extract_table(conn, t) for t in _get_tables(conn)],
        }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Schema exportado para {output}")


if __name__ == "__main__":
    main()
