from __future__ import annotations

"""Small, diversified discovery packet for the hypothesis LLM."""

from collections import Counter
import json
import sqlite3
from typing import Any

from ..config import load_defaults
from .field_profiles import materialize_field_profiles
from .knowledge import failure_ledger
from .scheduler import controlled_cycle_plan


def _ensure_profiles(connection: sqlite3.Connection) -> None:
    field_count = int(connection.execute("SELECT count(*) FROM fields").fetchone()[0])
    profile_count = int(connection.execute("SELECT count(*) FROM field_profiles").fetchone()[0])
    if profile_count < field_count:
        materialize_field_profiles(connection, only_missing=True)


def _candidate_rows(connection: sqlite3.Connection, max_scan: int = 4000) -> list[sqlite3.Row]:
    min_coverage = float(load_defaults().get("research", {}).get("min_field_coverage", 70))
    return connection.execute(
        """SELECT fp.*,f.description,f.coverage,f.date_coverage,f.alpha_count,
                  (SELECT count(*) FROM alpha_artifacts a
                   WHERE instr(lower(a.field_names_json), '"' || lower(fp.name) || '"') > 0) local_uses
           FROM field_profiles fp JOIN fields f ON f.field_key=fp.field_key
           WHERE coalesce(f.coverage,0)>=?
             AND upper(fp.data_type) IN ('MATRIX','VECTOR')
             AND fp.economic_theme!='generic'
             AND fp.confidence>=0.70
           ORDER BY local_uses ASC,fp.confidence DESC,coalesce(f.coverage,0) DESC,
                    coalesce(f.alpha_count,0) ASC,fp.name
           LIMIT ?""",
        (min_coverage, max_scan),
    ).fetchall()


def _source_priority(dataset: str) -> int:
    text = dataset.lower()
    groups = (
        ("fundamental", "score"),
        ("ravenpack", "news"),
        ("option", "volatility", "risk"),
        ("relationship",),
        ("price volume", "sentiment", "social"),
        ("analyst",),
    )
    return next((index for index, needles in enumerate(groups) if any(item in text for item in needles)), len(groups))


def _short_description(value: Any, limit: int = 220) -> str | None:
    text = " ".join(str(value or "").split())
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _diversified_fields(rows: list[sqlite3.Row], limit: int) -> list[dict[str, Any]]:
    available_datasets = {str(row["dataset_name"] or "unknown") for row in rows}
    available_themes = {str(row["economic_theme"] or "generic") for row in rows}
    dataset_cap = max(1, limit // 4) if len(available_datasets) >= 4 else limit
    theme_cap = max(1, limit // 4) if len(available_themes) >= 4 else limit
    dataset_counts: Counter[str] = Counter()
    theme_counts: Counter[str] = Counter()
    result: list[dict[str, Any]] = []
    selected_names: set[str] = set()
    indexed = list(enumerate(rows))
    while len(result) < limit:
        eligible: list[tuple[int, sqlite3.Row]] = []
        for index, row in indexed:
            name = str(row["name"] or "")
            dataset = str(row["dataset_name"] or "unknown")
            theme = str(row["economic_theme"] or "generic")
            if name.lower() in selected_names:
                continue
            if dataset_counts[dataset] >= dataset_cap or theme_counts[theme] >= theme_cap:
                continue
            eligible.append((index, row))
        if not eligible:
            break
        _, row = min(
            eligible,
            key=lambda item: (
                dataset_counts[str(item[1]["dataset_name"] or "unknown")],
                theme_counts[str(item[1]["economic_theme"] or "generic")],
                _source_priority(str(item[1]["dataset_name"] or "unknown")),
                item[0],
            ),
        )
        dataset = str(row["dataset_name"] or "unknown")
        theme = str(row["economic_theme"] or "generic")
        name = str(row["name"] or "")
        result.append({
            "name": name,
            "description": _short_description(row["description"]),
            "dataset": dataset,
            "data_type": row["data_type"],
            "theme": theme,
            "form": row["semantic_form"],
            "cadence": row["update_cadence"],
            "direction_prior": row["direction_prior"],
            "horizon_prior": json.loads(row["horizon_prior_json"] or "[]"),
            "coverage": row["coverage"],
            "alpha_count": row["alpha_count"],
            "local_uses": row["local_uses"],
            "profile_confidence": row["confidence"],
        })
        selected_names.add(name.lower())
        dataset_counts[dataset] += 1
        theme_counts[theme] += 1
    return result


def build_discovery_context(connection: sqlite3.Connection, count: int = 6, max_fields: int | None = None) -> dict[str, Any]:
    _ensure_profiles(connection)
    field_limit = max_fields or max(4, min(48, count * 4))
    candidates = _diversified_fields(_candidate_rows(connection), field_limit)
    used_themes = sorted({str(item["theme"]) for item in candidates})
    stopped = [dict(row) for row in connection.execute(
        "SELECT family,stop_reason FROM family_trial_stats WHERE stopped=1 ORDER BY updated_at DESC LIMIT 20"
    )]
    existing = [str(row[0]) for row in connection.execute(
        "SELECT family FROM hypotheses GROUP BY family ORDER BY max(created_at) DESC LIMIT 30"
    )]
    cycle = controlled_cycle_plan(connection, 12)
    return {
        "version": "semantic-discovery-v2",
        "requested_hypotheses": count,
        "candidate_fields": candidates,
        "represented_themes": used_themes,
        "failure_ledger": failure_ledger(connection, limit=8),
        "research_directives": {
            "cycle_quotas": cycle["quotas"],
            "diversity_parents": cycle["diversity_parents"][:4],
            "refinement_parents": cycle["refinement_parents"][:4],
            "stopped_families": stopped,
            "existing_family_names": existing,
        },
        "rules": [
            "Hypothesis before formula: do not emit FASTEXPR or operator names.",
            "Prefer underused fields/themes when the mechanism is defensible.",
            "A high-correlation parent requires a different field or economic mechanism, not a window/weight tweak.",
            "One hypothesis uses one core economic mechanism and must include a falsifier.",
            "Field names must be copied exactly from candidate_fields.",
        ],
    }


__all__ = ["build_discovery_context"]
