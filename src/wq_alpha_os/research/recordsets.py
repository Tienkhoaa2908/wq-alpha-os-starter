from __future__ import annotations

"""Utilities for decoding BRAIN recordset payloads.

BRAIN recordsets have appeared in several equivalent shapes over time.  The
current API commonly returns a schema plus ``records`` where each record wraps
a positional list under ``value``.  Older evidence may already contain row
objects.  Research code should reason over decoded row dictionaries instead of
re-implementing partial parsers in multiple modules.
"""

from typing import Any


def _schema_names(payload: dict[str, Any]) -> list[str]:
    schema = payload.get("schema")
    if not isinstance(schema, dict):
        return []
    properties = schema.get("properties")
    if isinstance(properties, list):
        names: list[str] = []
        for item in properties:
            if isinstance(item, dict):
                names.append(str(item.get("name") or ""))
            else:
                names.append(str(item))
        return names
    if isinstance(properties, dict):
        def index_for(item: tuple[str, Any]) -> int:
            value = item[1]
            if isinstance(value, dict):
                try:
                    return int(value.get("index", 0))
                except (TypeError, ValueError):
                    return 0
            return 0
        return [name for name, _ in sorted(properties.items(), key=index_for)]
    return []


def decode_recordset(payload: Any) -> list[dict[str, Any]]:
    """Return recordset rows as dictionaries for current and legacy shapes."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []

    names = _schema_names(payload)
    candidates: Any = None
    for key in ("records", "value", "results", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            candidates = value
            break
    if not isinstance(candidates, list):
        return []

    rows: list[dict[str, Any]] = []
    for item in candidates:
        if isinstance(item, dict) and "value" in item:
            item = item.get("value")
        if isinstance(item, dict):
            rows.append(item)
        elif isinstance(item, list) and names:
            rows.append(dict(zip(names, item)))
    return rows


def annual_sharpes(payload: Any) -> list[float]:
    """Extract in-sample yearly Sharpe values from a decoded recordset."""
    values: list[float] = []
    for row in decode_recordset(payload):
        if str(row.get("stage") or "IS").upper() != "IS":
            continue
        try:
            values.append(float(row.get("sharpe")))
        except (TypeError, ValueError):
            continue
    return values


__all__ = ["annual_sharpes", "decode_recordset"]
