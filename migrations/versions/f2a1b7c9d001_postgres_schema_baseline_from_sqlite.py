"""Create missing schema objects in PostgreSQL from SQLite baseline.

Revision ID: f2a1b7c9d001
Revises: e8a1c2d3f4b5
Create Date: 2026-02-14
"""

from __future__ import annotations

import json
from pathlib import Path

from alembic import op
import sqlalchemy as sa


revision = "f2a1b7c9d001"
down_revision = "e8a1c2d3f4b5"
branch_labels = None
depends_on = None


def _map_sqlite_type(type_name: str):
    upper = (type_name or "").upper()
    if upper.startswith("VARCHAR"):
        if "(" in upper and ")" in upper:
            try:
                size = int(upper.split("(", 1)[1].split(")", 1)[0])
                return sa.String(length=size)
            except ValueError:
                pass
        return sa.String()
    if "CHAR" in upper:
        return sa.String()
    if "BOOLEAN" in upper:
        return sa.Boolean()
    if "DATE" == upper:
        return sa.Date()
    if "DATETIME" in upper or "TIMESTAMP" in upper:
        return sa.DateTime()
    if "FLOAT" in upper or "REAL" in upper or "DOUBLE" in upper:
        return sa.Float()
    if "INT" in upper:
        return sa.Integer()
    if "TEXT" in upper:
        return sa.Text()
    return sa.Text()


def _server_default(col_type, raw_default):
    if raw_default is None:
        return None

    value = str(raw_default).strip()
    while value.startswith("(") and value.endswith(")") and len(value) > 1:
        value = value[1:-1].strip()

    if isinstance(col_type, sa.Boolean):
        if value in {"0", "false", "FALSE"}:
            return sa.text("false")
        if value in {"1", "true", "TRUE"}:
            return sa.text("true")

    if isinstance(col_type, sa.Integer) and value.lstrip("-").isdigit():
        return sa.text(value)

    return sa.text(value)


def _topological_order(tables):
    remaining = {table["name"]: table for table in tables}
    resolved = []

    while remaining:
        progressed = False
        for table_name in list(remaining.keys()):
            table = remaining[table_name]
            dependencies = {
                fk["referred_table"]
                for fk in table.get("foreign_keys", [])
                if fk.get("referred_table") and fk.get("referred_table") != table_name
            }
            if dependencies.issubset(set(resolved)):
                resolved.append(table_name)
                remaining.pop(table_name)
                progressed = True
        if not progressed:
            resolved.extend(remaining.keys())
            break

    by_name = {table["name"]: table for table in tables}
    return [by_name[name] for name in resolved]


def _load_schema():
    schema_path = Path(__file__).resolve().parents[2] / "tools" / "schema_sqlite.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    schema = _load_schema()
    ordered_tables = _topological_order(schema["tables"])

    for table in ordered_tables:
        table_name = table["name"]
        if table_name in existing_tables:
            continue

        pk_cols = table.get("primary_key", {}).get("constrained_columns") or []
        single_int_pk = None
        if len(pk_cols) == 1:
            for col_data in table["columns"]:
                if col_data["name"] == pk_cols[0] and "INT" in (col_data.get("type") or "").upper():
                    single_int_pk = col_data["name"]
                    break

        columns = []
        for col_data in table["columns"]:
            col_type = _map_sqlite_type(col_data.get("type"))
            kwargs = {
                "nullable": col_data.get("nullable", True),
            }
            default = _server_default(col_type, col_data.get("default"))
            if default is not None:
                kwargs["server_default"] = default

            if col_data["name"] == single_int_pk:
                kwargs["primary_key"] = True
                kwargs["nullable"] = False
                columns.append(sa.Column(col_data["name"], col_type, sa.Identity(always=False), **kwargs))
                continue

            if col_data["name"] in pk_cols:
                kwargs["primary_key"] = True
                kwargs["nullable"] = False

            columns.append(sa.Column(col_data["name"], col_type, **kwargs))

        constraints = []
        for fk in table.get("foreign_keys", []):
            constrained = fk.get("constrained_columns") or []
            referred_table = fk.get("referred_table")
            referred_columns = fk.get("referred_columns") or []
            if not constrained or not referred_table or not referred_columns:
                continue

            constraints.append(
                sa.ForeignKeyConstraint(
                    constrained,
                    [f"{referred_table}.{column}" for column in referred_columns],
                    name=fk.get("name"),
                    ondelete=fk.get("on_delete") if fk.get("on_delete") != "NO ACTION" else None,
                    onupdate=fk.get("on_update") if fk.get("on_update") != "NO ACTION" else None,
                )
            )

        for uq in table.get("unique_constraints", []):
            columns_uq = uq.get("column_names") or []
            if columns_uq:
                constraints.append(sa.UniqueConstraint(*columns_uq, name=uq.get("name")))

        op.create_table(table_name, *columns, *constraints)
        existing_tables.add(table_name)

    inspector = sa.inspect(bind)
    existing_indexes = {
        (table_name, idx.get("name"))
        for table_name in inspector.get_table_names()
        for idx in inspector.get_indexes(table_name)
    }

    for table in ordered_tables:
        table_name = table["name"]
        for idx in table.get("indexes", []):
            idx_name = idx.get("name")
            columns = idx.get("column_names") or []
            if not idx_name or not columns:
                continue
            if (table_name, idx_name) in existing_indexes:
                continue
            op.create_index(idx_name, table_name, columns, unique=bool(idx.get("unique")))


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    schema = _load_schema()
    for table in reversed(_topological_order(schema["tables"])):
        op.drop_table(table["name"])
