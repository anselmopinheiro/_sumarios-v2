from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, Iterable, List, Optional, Sequence
from xml.etree.ElementTree import Element, SubElement, tostring

DEFAULT_DEBUG_FIELDS = {"_raw", "domain_details", "rubricas", "tipos"}


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _column_specs(map_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [c for c in (map_data.get("columns") or []) if isinstance(c, dict) and c.get("key")]


def _column_keys_for_csv(
    map_data: Dict[str, Any],
    include_debug: bool = False,
    extra_exclude_fields: Optional[Sequence[str]] = None,
) -> List[str]:
    cols = _column_specs(map_data)
    if cols:
        return [str(c["key"]) for c in cols]

    rows = map_data.get("rows") or []
    if not rows:
        return []

    exclude = set(DEFAULT_DEBUG_FIELDS)
    if include_debug:
        exclude = set()
    if extra_exclude_fields:
        exclude.update(extra_exclude_fields)

    keys: List[str] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        for k, v in r.items():
            if k in exclude:
                continue
            if not include_debug and not _is_scalar(v):
                continue
            if k not in keys:
                keys.append(k)
    return keys


def export_map_to_csv(
    map_data: Dict[str, Any],
    *,
    include_debug: bool = False,
    extra_exclude_fields: Optional[Sequence[str]] = None,
) -> bytes:
    """Export map data to CSV bytes encoded as UTF-8 with BOM and ';' delimiter.

    Uses map columns as primary header source. Row values are read from flat row keys.
    Nested/debug payloads are ignored by default.
    """

    column_specs = _column_specs(map_data)
    keys = _column_keys_for_csv(
        map_data,
        include_debug=include_debug,
        extra_exclude_fields=extra_exclude_fields,
    )

    label_by_key = {str(c["key"]): str(c.get("label") or c["key"]) for c in column_specs}
    headers = [label_by_key.get(k, k) for k in keys]

    sio = io.StringIO(newline="")
    writer = csv.writer(sio, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(headers)

    rows = map_data.get("rows") or []
    for row in rows:
        if not isinstance(row, dict):
            continue
        vals = []
        for k in keys:
            v = row.get(k)
            if not include_debug and not _is_scalar(v):
                vals.append("")
            else:
                vals.append(_to_text(v))
        writer.writerow(vals)

    content = sio.getvalue()
    return ("\ufeff" + content).encode("utf-8")


def _append_xml_value(parent: Element, key: str, value: Any, include_debug: bool) -> None:
    if isinstance(value, dict):
        node = SubElement(parent, key)
        for k, v in value.items():
            if not include_debug and k in DEFAULT_DEBUG_FIELDS:
                continue
            child_key = str(k).replace(" ", "_")
            _append_xml_value(node, child_key, v, include_debug)
        return

    if isinstance(value, list):
        node = SubElement(parent, key)
        for item in value:
            item_node = SubElement(node, "item")
            if isinstance(item, dict):
                for k, v in item.items():
                    _append_xml_value(item_node, str(k).replace(" ", "_"), v, include_debug)
            else:
                item_node.text = _to_text(item)
        return

    node = SubElement(parent, key)
    node.text = _to_text(value)


def export_map_to_xml(
    map_data: Dict[str, Any],
    *,
    include_debug: bool = False,
) -> bytes:
    """Export map data to XML bytes encoded as UTF-8."""

    root = Element("evaluation_map")

    meta_node = SubElement(root, "meta")
    for k, v in (map_data.get("meta") or {}).items():
        _append_xml_value(meta_node, str(k).replace(" ", "_"), v, include_debug)

    cols_node = SubElement(root, "columns")
    for col in _column_specs(map_data):
        cnode = SubElement(cols_node, "column")
        for k, v in col.items():
            _append_xml_value(cnode, str(k).replace(" ", "_"), v, include_debug)

    rows_node = SubElement(root, "rows")
    for idx, row in enumerate(map_data.get("rows") or [], start=1):
        if not isinstance(row, dict):
            continue
        rnode = SubElement(rows_node, "row", index=str(idx))

        # flat cells according to columns first
        keys = [str(c["key"]) for c in _column_specs(map_data)]
        for key in keys:
            val = row.get(key)
            _append_xml_value(rnode, key, val, include_debug)

        if include_debug:
            for key, val in row.items():
                if key in keys:
                    continue
                _append_xml_value(rnode, key, val, include_debug)

    totals = map_data.get("totals")
    if isinstance(totals, dict):
        totals_node = SubElement(root, "totals")
        for k, v in totals.items():
            _append_xml_value(totals_node, str(k).replace(" ", "_"), v, include_debug)

    return tostring(root, encoding="utf-8", xml_declaration=True)


def export_map_to_csv_text(map_data: Dict[str, Any], **kwargs: Any) -> str:
    return export_map_to_csv(map_data, **kwargs).decode("utf-8")


def export_map_to_xml_text(map_data: Dict[str, Any], **kwargs: Any) -> str:
    return export_map_to_xml(map_data, **kwargs).decode("utf-8")
