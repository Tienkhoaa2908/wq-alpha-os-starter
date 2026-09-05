from __future__ import annotations

"""Sanitized audits used to calibrate the v2 research brain.

The local SQLite database remains the detailed source of truth.  This module
exports small, source-controlled summaries so ChatGPT/Codex can inspect field
classification quality and the exact discovery packet without receiving raw
BRAIN responses, credentials or PnL series.
"""

from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from typing import Any

from ..config import PROJECT_ROOT
from .discovery_v2 import build_discovery_context


LOW_CONFIDENCE = 0.70


def _distribution(connection: sqlite3.Connection, column: str) -> dict[str, int]:
    allowed = {
        "economic_theme", "semantic_form", "update_cadence", "data_type", "classification_source",
        "unit_family", "signedness", "direction_prior", "sparsity_class", "peer_dependence",
    }
    if column not in allowed:
        raise ValueError(f"Unsupported audit column: {column}")
    rows = connection.execute(
        f"SELECT coalesce(nullif({column},''),'unknown') value,count(*) n FROM field_profiles GROUP BY value ORDER BY n DESC,value"
    ).fetchall()
    return {str(row["value"]): int(row["n"]) for row in rows}


def _rate(value: int, total: int) -> float:
    return round(value / total, 6) if total else 0.0


def _field_quality(connection: sqlite3.Connection, total: int) -> dict[str, Any]:
    def count(where: str, params: tuple[Any, ...] = ()) -> int:
        return int(connection.execute(f"SELECT count(*) FROM field_profiles fp JOIN fields f ON f.field_key=fp.field_key WHERE {where}", params).fetchone()[0])

    generic = count("fp.economic_theme='generic'")
    unknown_unit = count("fp.unit_family='unknown'")
    low_confidence = count("fp.confidence<?", (LOW_CONFIDENCE,))
    ambiguous_direction = count("fp.direction_prior='ambiguous'")
    high_coverage_generic = count("fp.economic_theme='generic' AND coalesce(f.coverage,0)>=70")
    vector_total = count("upper(fp.data_type)='VECTOR'")
    vector_bad_form = count("upper(fp.data_type)='VECTOR' AND fp.semantic_form NOT LIKE 'vector_%'")
    return {
        "generic_theme": {"count": generic, "rate": _rate(generic, total)},
        "unknown_unit": {"count": unknown_unit, "rate": _rate(unknown_unit, total)},
        "low_confidence_lt_0_70": {"count": low_confidence, "rate": _rate(low_confidence, total)},
        "ambiguous_direction": {"count": ambiguous_direction, "rate": _rate(ambiguous_direction, total)},
        "high_coverage_generic": {"count": high_coverage_generic, "rate": _rate(high_coverage_generic, total)},
        "vector_fields": vector_total,
        "vector_with_nonvector_form": vector_bad_form,
    }


def _review_candidates(connection: sqlite3.Connection, limit: int = 48) -> list[dict[str, Any]]:
    rows = connection.execute(
        """SELECT fp.name,fp.dataset_name,fp.data_type,fp.economic_theme,fp.semantic_form,
                  fp.update_cadence,fp.unit_family,fp.direction_prior,fp.confidence,
                  f.coverage,f.date_coverage,f.alpha_count
           FROM field_profiles fp JOIN fields f ON f.field_key=fp.field_key
           WHERE fp.economic_theme='generic' OR fp.unit_family='unknown' OR fp.confidence<?
           ORDER BY coalesce(f.coverage,0) DESC,fp.confidence ASC,fp.name LIMIT ?""",
        (LOW_CONFIDENCE, int(limit)),
    ).fetchall()
    return [dict(row) for row in rows]


def _dataset_summary(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """SELECT fp.dataset_name,
                  count(*) fields,
                  round(avg(fp.confidence),4) avg_confidence,
                  sum(CASE WHEN fp.economic_theme='generic' THEN 1 ELSE 0 END) generic_fields,
                  sum(CASE WHEN fp.unit_family='unknown' THEN 1 ELSE 0 END) unknown_unit_fields,
                  sum(CASE WHEN upper(fp.data_type)='VECTOR' THEN 1 ELSE 0 END) vector_fields
           FROM field_profiles fp
           GROUP BY fp.dataset_name
           ORDER BY fields DESC,fp.dataset_name"""
    ).fetchall()
    return [dict(row) for row in rows]


def _theme_form_pairs(connection: sqlite3.Connection, limit: int = 40) -> list[dict[str, Any]]:
    rows = connection.execute(
        """SELECT economic_theme,semantic_form,count(*) n
           FROM field_profiles
           GROUP BY economic_theme,semantic_form
           ORDER BY n DESC,economic_theme,semantic_form LIMIT ?""",
        (int(limit),),
    ).fetchall()
    return [dict(row) for row in rows]


def build_field_semantic_audit(connection: sqlite3.Connection) -> dict[str, Any]:
    total = int(connection.execute("SELECT count(*) FROM field_profiles").fetchone()[0])
    distributions = {
        column: _distribution(connection, column)
        for column in (
            "economic_theme", "semantic_form", "update_cadence", "data_type", "classification_source",
            "unit_family", "signedness", "direction_prior", "sparsity_class", "peer_dependence",
        )
    }
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "total_profiles": total,
        "quality": _field_quality(connection, total),
        "distributions": distributions,
        "theme_form_pairs": _theme_form_pairs(connection),
        "dataset_summary": _dataset_summary(connection),
        "review_candidates": _review_candidates(connection),
        "notes": [
            "Descriptions are intentionally omitted from the source-controlled audit.",
            "Generic/unknown/low-confidence counts are calibration signals, not automatic rejection criteria.",
            "LLM review should be limited to ambiguous high-value fields after this deterministic audit is inspected.",
        ],
    }


def _forbidden_packet_keys(value: Any) -> list[str]:
    forbidden = {"expression", "formula", "operator", "operators", "operator_name"}
    found: list[str] = []
    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if str(key).lower() in forbidden:
                    found.append(str(key))
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)
    visit(value)
    return sorted(set(found))


def build_agent_packet_audit(connection: sqlite3.Connection, count: int = 6) -> dict[str, Any]:
    packet = build_discovery_context(connection, count=count)
    themes = Counter(str(item.get("theme") or "unknown") for item in packet.get("candidate_fields", []))
    datasets = Counter(str(item.get("dataset") or "unknown") for item in packet.get("candidate_fields", []))
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "packet": packet,
        "audit": {
            "candidate_field_count": len(packet.get("candidate_fields", [])),
            "theme_counts": dict(sorted(themes.items())),
            "dataset_counts": dict(sorted(datasets.items())),
            "forbidden_formula_keys": _forbidden_packet_keys(packet),
            "contains_formula_surface": bool(_forbidden_packet_keys(packet)),
        },
    }


def write_audit_snapshots(
    connection: sqlite3.Connection,
    *,
    field_path: Path | None = None,
    packet_path: Path | None = None,
    count: int = 6,
) -> dict[str, Any]:
    field_path = field_path or PROJECT_ROOT / "docs" / "generated" / "field_semantic_audit.json"
    packet_path = packet_path or PROJECT_ROOT / "docs" / "generated" / "agent_packet_preview.json"
    field_path.parent.mkdir(parents=True, exist_ok=True)
    packet_path.parent.mkdir(parents=True, exist_ok=True)
    field_audit = build_field_semantic_audit(connection)
    packet_audit = build_agent_packet_audit(connection, count=count)
    field_path.write_text(json.dumps(field_audit, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    packet_path.write_text(json.dumps(packet_audit, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return {
        "field_audit": str(field_path),
        "packet_preview": str(packet_path),
        "total_profiles": field_audit["total_profiles"],
        "packet_fields": packet_audit["audit"]["candidate_field_count"],
        "forbidden_formula_keys": packet_audit["audit"]["forbidden_formula_keys"],
    }


__all__ = [
    "build_agent_packet_audit",
    "build_field_semantic_audit",
    "write_audit_snapshots",
]
