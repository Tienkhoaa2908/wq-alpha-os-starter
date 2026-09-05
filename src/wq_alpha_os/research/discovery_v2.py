from __future__ import annotations

"""Small, diversified discovery packet for the hypothesis LLM."""

from collections import defaultdict
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


def _candidate_rows(connection: sqlite3.Connection, max_scan: int = 500) -> list[sqlite3.Row]:
    min_coverage = float(load_defaults().get("research", {}).get("min_field_coverage", 70))
    return connection.execute(
        """SELECT fp.*,f.coverage,f.date_coverage,f.alpha_count,
                  (SELECT count(*) FROM alpha_artifacts a
                   WHERE instr(lower(a.field_names_json), '"' || lower(fp.name) || '"') > 0) local_uses
           FROM field_profiles fp JOIN fields f ON f.field_key=fp.field_key
           WHERE coalesce(f.coverage,0)>=?
           ORDER BY local_uses ASC,fp.confidence DESC,coalesce(f.coverage,0) DESC,
                    coalesce(f.alpha_count,0) ASC,fp.name
           LIMIT ?""",
        (min_coverage, max_scan),
    ).fetchall()


def _diversified_fields(rows: list[sqlite3.Row], limit: int) -> list[dict[str, Any]]:
    by_theme: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        by_theme[str(row["economic_theme"] or "generic")].append(row)
    themes = sorted(by_theme, key=lambda theme: (theme == "generic", theme))
    result: list[dict[str, Any]] = []
    index = 0
    while len(result) < limit and themes:
        next_themes: list[str] = []
        for theme in themes:
            items = by_theme[theme]
            if index < len(items):
                row = items[index]
                result.append({
                    "name": row["name"],
                    "dataset": row["dataset_name"],
                    "data_type": row["data_type"],
                    "theme": row["economic_theme"],
                    "form": row["semantic_form"],
                    "cadence": row["update_cadence"],
                    "direction_prior": row["direction_prior"],
                    "horizon_prior": __import__("json").loads(row["horizon_prior_json"] or "[]"),
                    "coverage": row["coverage"],
                    "local_uses": row["local_uses"],
                    "profile_confidence": row["confidence"],
                })
                if len(result) >= limit:
                    break
            if index + 1 < len(items):
                next_themes.append(theme)
        index += 1
        themes = next_themes
    return result


def build_discovery_context(connection: sqlite3.Connection, count: int = 6, max_fields: int | None = None) -> dict[str, Any]:
    _ensure_profiles(connection)
    field_limit = max_fields or max(18, min(48, count * 6))
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
