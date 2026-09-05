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

from ..config import PROJECT_ROOT, load_defaults
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
                  f.description,f.coverage,f.date_coverage,f.alpha_count
           FROM field_profiles fp JOIN fields f ON f.field_key=fp.field_key
           WHERE upper(fp.data_type) IN ('MATRIX','VECTOR')
             AND coalesce(f.coverage,0)>=70
             AND (fp.economic_theme='generic' OR fp.confidence<?)
           ORDER BY coalesce(f.coverage,0) DESC,fp.confidence ASC,fp.name LIMIT ?""",
        (LOW_CONFIDENCE, int(limit)),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["description"] = _short_description(item.get("description"))
        result.append(item)
    return result


def _short_description(value: Any, limit: int = 220) -> str | None:
    text = " ".join(str(value or "").split())
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _misclassification_risk_samples(connection: sqlite3.Connection, per_dataset: int = 3) -> list[dict[str, Any]]:
    rows = connection.execute(
        """SELECT fp.name,fp.dataset_name,fp.data_type,fp.economic_theme,fp.semantic_form,
                  fp.secondary_themes_json,fp.classification_source,fp.confidence,
                  f.description,f.coverage
           FROM field_profiles fp JOIN fields f ON f.field_key=fp.field_key
           WHERE upper(fp.data_type) IN ('MATRIX','VECTOR')
             AND (fp.economic_theme='generic' OR fp.confidence<0.70 OR fp.secondary_themes_json NOT IN ('[]',''))
           ORDER BY fp.dataset_name,fp.confidence ASC,coalesce(f.coverage,0) DESC,fp.name"""
    ).fetchall()
    counts: Counter[str] = Counter()
    result: list[dict[str, Any]] = []
    for row in rows:
        dataset = str(row["dataset_name"] or "unknown")
        if counts[dataset] >= per_dataset:
            continue
        secondary = json.loads(row["secondary_themes_json"] or "[]")
        reasons = []
        if row["economic_theme"] == "generic":
            reasons.append("generic_theme")
        if float(row["confidence"] or 0) < LOW_CONFIDENCE:
            reasons.append("low_confidence")
        if secondary:
            reasons.append("competing_theme_evidence")
        result.append({
            "name": row["name"],
            "dataset_name": dataset,
            "data_type": row["data_type"],
            "description": _short_description(row["description"]),
            "economic_theme": row["economic_theme"],
            "secondary_themes": secondary,
            "semantic_form": row["semantic_form"],
            "confidence": row["confidence"],
            "risk_reasons": reasons,
        })
        counts[dataset] += 1
    return result


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
        "misclassification_risk_samples": _misclassification_risk_samples(connection),
        "review_candidates": _review_candidates(connection),
        "notes": [
            "Descriptions are truncated to 220 characters in review and misclassification-risk samples.",
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
    candidates = packet.get("candidate_fields", [])
    themes = Counter(str(item.get("theme") or "unknown") for item in candidates)
    datasets = Counter(str(item.get("dataset") or "unknown") for item in candidates)
    total = len(candidates)
    infrastructure = sum(str(item.get("data_type") or "").upper() not in {"MATRIX", "VECTOR"} for item in candidates)
    generic = sum(str(item.get("theme") or "generic") == "generic" for item in candidates)
    low_confidence = sum(float(item.get("profile_confidence") or 0) < LOW_CONFIDENCE for item in candidates)
    missing_description = sum(not str(item.get("description") or "").strip() for item in candidates)
    max_dataset_share = round(max(datasets.values(), default=0) / total, 6) if total else 0.0
    max_theme_share = round(max(themes.values(), default=0) / total, 6) if total else 0.0
    min_coverage = float(load_defaults().get("research", {}).get("min_field_coverage", 70))
    eligible = connection.execute(
        """SELECT count(DISTINCT fp.dataset_name) datasets,count(DISTINCT fp.economic_theme) themes
           FROM field_profiles fp JOIN fields f ON f.field_key=fp.field_key
           WHERE upper(fp.data_type) IN ('MATRIX','VECTOR') AND fp.economic_theme!='generic'
             AND fp.confidence>=? AND coalesce(f.coverage,0)>=?""",
        (LOW_CONFIDENCE, min_coverage),
    ).fetchone()
    eligible_dataset_count = int(eligible["datasets"] or 0)
    eligible_theme_count = int(eligible["themes"] or 0)
    forbidden = _forbidden_packet_keys(packet)
    reasons: list[str] = []
    if forbidden:
        reasons.append("formula_surface_present")
    if infrastructure:
        reasons.append("infrastructure_field_present")
    if generic:
        reasons.append("generic_field_present")
    if low_confidence:
        reasons.append("low_confidence_field_present")
    if missing_description:
        reasons.append("missing_description")
    if eligible_dataset_count >= 4 and max_dataset_share > 0.25:
        reasons.append("dataset_cap_exceeded")
    if eligible_theme_count >= 4 and max_theme_share > 0.25:
        reasons.append("theme_cap_exceeded")
    directives = packet.get("research_directives", {})
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "packet": packet,
        "audit": {
            "candidate_field_count": total,
            "theme_counts": dict(sorted(themes.items())),
            "dataset_counts": dict(sorted(datasets.items())),
            "dataset_count": len(datasets),
            "theme_count": len(themes),
            "eligible_dataset_count": eligible_dataset_count,
            "eligible_theme_count": eligible_theme_count,
            "dataset_cap": 0.25,
            "theme_cap": 0.25,
            "max_dataset_share": max_dataset_share,
            "max_theme_share": max_theme_share,
            "low_confidence_count": low_confidence,
            "generic_count": generic,
            "infrastructure_count": infrastructure,
            "missing_description_count": missing_description,
            "forbidden_formula_keys": forbidden,
            "contains_formula_surface": bool(forbidden),
            "cycle_plan": {
                "diversity_parent_count": len(directives.get("diversity_parents", [])),
                "refinement_parent_count": len(directives.get("refinement_parents", [])),
            },
            "gate_pass": not reasons,
            "gate_reasons": reasons or ["all_packet_gates_passed"],
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
        "gate_pass": packet_audit["audit"]["gate_pass"],
    }


__all__ = [
    "build_agent_packet_audit",
    "build_field_semantic_audit",
    "write_audit_snapshots",
]
