from __future__ import annotations

import re
import sqlite3
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

from .dsl.specs import SPECS, OperatorSpec


COMPARISON_OPERATOR_SYMBOLS: dict[str, str] = {
    "equal": "==",
    "not_equal": "!=",
    "greater": ">",
    "greater_equal": ">=",
    "less": "<",
    "less_equal": "<=",
}


def _clean(value: object) -> str:
    return str(value or "").strip()


def deduplicate_brain_operators(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Return one sanitized BRAIN record per case-insensitive operator name.

    When duplicate source rows exist, the most informative BRAIN row wins. SPECS
    is intentionally not consulted here: it is compiler capability metadata.
    """
    selected: dict[str, dict[str, str]] = {}
    scores: dict[str, tuple[int, int, int]] = {}
    for row in rows:
        name = _clean(row.get("name")).lower()
        if not name:
            continue
        item = {
            "name": name,
            "category": _clean(row.get("category")),
            "definition": _clean(row.get("definition") or row.get("signature")),
            "description": _clean(row.get("description")),
        }
        score = (
            bool(item["definition"]) + bool(item["description"]) + bool(item["category"]),
            len(item["definition"]),
            len(item["description"]),
        )
        if name not in selected or score > scores[name]:
            selected[name] = item
            scores[name] = score
    return [selected[name] for name in sorted(selected)]


def active_brain_operator_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT name,category,signature,description,raw_json,snapshot_id,updated_at "
        "FROM active_brain_operators ORDER BY name"
    ).fetchall()


def active_brain_operator_count(connection: sqlite3.Connection) -> int:
    return int(connection.execute("SELECT count(*) FROM active_brain_operators").fetchone()[0])


def _definition_kwargs(definition: str) -> set[str]:
    return {name.lower() for name in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*=", definition)}


def audit_operator_registry(
    rows: Iterable[Mapping[str, Any]],
    specs: Mapping[str, OperatorSpec] | None = None,
) -> dict[str, Any]:
    source_rows = list(rows)
    unique = deduplicate_brain_operators(source_rows)
    brain_names = {row["name"] for row in unique}
    typed = dict(SPECS if specs is None else specs)
    comparison_names = sorted(brain_names & set(COMPARISON_OPERATOR_SYMBOLS))
    call_names = sorted(brain_names - set(comparison_names))
    dsl_supported = set(typed) | set(comparison_names)

    mismatches: list[dict[str, Any]] = []
    by_name = {row["name"]: row for row in unique}
    for name in sorted(brain_names & set(typed)):
        brain_kwargs = _definition_kwargs(by_name[name]["definition"])
        typed_kwargs = set(typed[name].allowed_kwargs)
        if brain_kwargs != typed_kwargs:
            mismatches.append(
                {
                    "name": name,
                    "brain_kwargs": sorted(brain_kwargs),
                    "typed_kwargs": sorted(typed_kwargs),
                }
            )

    frequencies = Counter(_clean(row.get("name")).lower() for row in source_rows)
    duplicates = {name: count for name, count in sorted(frequencies.items()) if name and count > 1}
    return {
        "source_rows": len(source_rows),
        "unique_brain_operators": len(unique),
        "call_operators": len(call_names),
        "logical_comparison_operators": comparison_names,
        "brain_not_dsl": sorted(brain_names - dsl_supported),
        "dsl_not_brain": sorted(set(typed) - brain_names),
        "signature_or_kwargs_mismatches": mismatches,
        "duplicate_source_rows": len(source_rows) - len(unique),
        "duplicate_names": duplicates,
        "std": {
            "present_in_brain": "std" in brain_names,
            "present_in_typed_registry": "std" in typed,
            "active": "std" in brain_names,
        },
    }
