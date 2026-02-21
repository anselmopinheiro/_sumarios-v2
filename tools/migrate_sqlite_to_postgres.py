#!/usr/bin/env python3
import argparse
import logging
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import MetaData, create_engine, func, insert, select, text

from config import normalize_database_url

LOGGER = logging.getLogger("sqlite_to_postgres")


def _redact_url(url: str) -> str:
    parsed = urlsplit(url)
    if "@" not in parsed.netloc:
        return url
    _, host_part = parsed.netloc.rsplit("@", 1)
    return f"{parsed.scheme}://***:***@{host_part}{parsed.path}"


def _parse_args():
    parser = argparse.ArgumentParser(description="Migra dados de SQLite para PostgreSQL.")
    parser.add_argument(
        "--sqlite-path",
        default=os.environ.get("SQLITE_PATH", "gestor_lectivo.db"),
        help="Caminho para o ficheiro SQLite (default: SQLITE_PATH ou gestor_lectivo.db)",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="URL de destino PostgreSQL (default: DATABASE_URL)",
    )
    parser.add_argument(
        "--wipe",
        action="store_true",
        help="Limpa tabelas de destino antes de importar.",
    )
    return parser.parse_args()


def _fetch_table_counts(connection, metadata):
    counts = {}
    for table in metadata.sorted_tables:
        counts[table.name] = connection.execute(select(func.count()).select_from(table)).scalar_one()
    return counts


def _wipe_destination(connection, metadata):
    for table in reversed(metadata.sorted_tables):
        connection.execute(text(f'TRUNCATE TABLE "{table.name}" RESTART IDENTITY CASCADE'))


def _migrate_table(sqlite_conn, pg_engine, src_table, dst_table):
    rows = sqlite_conn.execute(select(src_table)).mappings().all()
    with pg_engine.begin() as pg_conn:
        pg_conn.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        if rows:
            pg_conn.execute(insert(dst_table), [dict(row) for row in rows])
    return len(rows)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    args = _parse_args()

    if not args.database_url:
        raise SystemExit("DATABASE_URL é obrigatório (env ou --database-url).")

    sqlite_path = Path(args.sqlite_path)
    if not sqlite_path.exists():
        raise SystemExit(f"SQLite não encontrado: {sqlite_path}")

    database_url = normalize_database_url(args.database_url)
    LOGGER.info("Destino PostgreSQL: %s", _redact_url(database_url))
    LOGGER.info("Origem SQLite: %s", sqlite_path)

    sqlite_engine = create_engine(f"sqlite:///{sqlite_path}")
    postgres_engine = create_engine(database_url)

    source_metadata = MetaData()
    target_metadata = MetaData()

    with sqlite_engine.connect() as sqlite_conn, postgres_engine.connect() as pg_conn:
        source_metadata.reflect(bind=sqlite_conn)
        target_metadata.reflect(bind=pg_conn)

        source_tables = [table.name for table in source_metadata.sorted_tables]
        target_table_names = set(target_metadata.tables.keys())

        missing_tables = [name for name in source_tables if name not in target_table_names]
        if missing_tables:
            raise SystemExit(
                "Destino sem schema completo. Corre 'flask db upgrade' antes da migração. "
                f"Tabelas em falta: {', '.join(missing_tables)}"
            )

        if args.wipe:
            LOGGER.info("A limpar destino (--wipe)...")
            with postgres_engine.begin() as pg_tx:
                _wipe_destination(pg_tx, target_metadata)

        migrated = {}
        for src_table in source_metadata.sorted_tables:
            dst_table = target_metadata.tables[src_table.name]
            LOGGER.info("Migrar tabela: %s", src_table.name)
            migrated[src_table.name] = _migrate_table(sqlite_conn, postgres_engine, src_table, dst_table)
            LOGGER.info("  -> %s registos importados", migrated[src_table.name])

        source_counts = _fetch_table_counts(sqlite_conn, source_metadata)
        target_counts = _fetch_table_counts(pg_conn, target_metadata)

    LOGGER.info("Validação de contagens:")
    has_mismatch = False
    for table_name, src_count in source_counts.items():
        dst_count = target_counts.get(table_name)
        if src_count != dst_count:
            has_mismatch = True
            LOGGER.error("  %s: origem=%s destino=%s", table_name, src_count, dst_count)
        else:
            LOGGER.info("  %s: %s", table_name, src_count)

    if has_mismatch:
        raise SystemExit("Migração concluída com divergências nas contagens.")

    LOGGER.info("Migração concluída com sucesso.")


if __name__ == "__main__":
    main()
