from __future__ import annotations

"""Empirical memory built only from completed BRAIN simulations."""

import json
import math
from statistics import median
import sqlite3
from typing import Any, Iterable

from ..config import load_defaults
from ..db import json_dumps, utc_now
from .scorer import check_summary


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _median(values: Iterable[Any]) -> float | None:
    clean = [value for item in values if (value := _float(item)) is not None]
    return round(float(median(clean)), 6) if clean else None


def _annual_min(payload: str | None) -> float | None:
    if not payload:
        return None
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        return None
    rows: list[dict[str, Any]] = []
    if isinstance(data, list):
        rows = [item for item in data if isinstance(item, dict)]
    elif isinstance(data, dict):
        raw = data.get("value") or data.get("results") or data.get("data")
        if isinstance(raw, list):
            rows = [item for item in raw if isinstance(item, dict)]
    values = []
    for row in rows:
        if str(row.get("stage") or "IS").upper() != "IS":
            continue
        value = _float(row.get("sharpe"))
        if value is not None:
            values.append(value)
    return min(values) if values else None


def _context_key(role_hash: str, theme: str, horizon: str) -> str:
    return f"{role_hash}|{theme}|{horizon}"


def _horizon_from_plan(resolved_json: str | None) -> str:
    """Read the coarse horizon from AlphaPlan JSON.

    ``alpha_plans`` deliberately stores the resolved plan as JSON rather than
    duplicating every plan attribute as a SQL column. Legacy artifacts usually
    have no plan row at all, so they fall back to ``legacy_or_unknown``.
    """
    if not resolved_json:
        return "legacy_or_unknown"
    try:
        payload = json.loads(resolved_json)
    except (TypeError, ValueError):
        return "legacy_or_unknown"
    if not isinstance(payload, dict):
        return "legacy_or_unknown"
    value = str(payload.get("horizon_bucket") or "").strip()
    return value or "legacy_or_unknown"


def rebuild_motif_stats(connection: sqlite3.Connection) -> dict[str, int]:
    rows = connection.execute(
        """SELECT r.*,m.role_motif_hash,m.field_themes_json,p.resolved_json
           FROM simulation_runs r
           JOIN artifact_motifs m ON m.artifact_id=r.artifact_id
           LEFT JOIN alpha_plans p ON p.artifact_id=r.artifact_id
           WHERE r.platform_status='COMPLETE'
           ORDER BY r.finished_at"""
    ).fetchall()
    groups: dict[str, list[sqlite3.Row]] = {}
    meta: dict[str, tuple[str, str, str]] = {}
    for row in rows:
        try:
            themes = json.loads(row["field_themes_json"] or "[]")
        except (TypeError, ValueError):
            themes = []
        theme = str(themes[0] if themes else "unknown")
        horizon = _horizon_from_plan(row["resolved_json"])
        key = _context_key(row["role_motif_hash"], theme, horizon)
        groups.setdefault(key, []).append(row)
        meta[key] = (row["role_motif_hash"], theme, horizon)

    limits = load_defaults()["research"]
    min_sharpe = float(limits.get("promotion_min_sharpe", 1.25))
    min_fitness = float(limits.get("promotion_min_fitness", 1.0))
    max_corr = float(limits.get("promotion_max_self_correlation", 0.7))
    connection.execute("DELETE FROM motif_stats")
    for key, items in groups.items():
        passes = 0
        annual_values: list[float] = []
        for row in items:
            _, failed, _ = check_summary(json.loads(row["checks_json"] or "[]"))
            sharpe = _float(row["sharpe"])
            fitness = _float(row["fitness"])
            corr = _float(row["self_correlation"])
            if sharpe is not None and fitness is not None and corr is not None and sharpe >= min_sharpe and fitness >= min_fitness and corr <= max_corr and failed == 0:
                passes += 1
            annual = _annual_min(row["annual_json"])
            if annual is not None:
                annual_values.append(annual)
        role_hash, theme, horizon = meta[key]
        n = len(items)
        # Conservative uncertainty proxy: small samples stay uncertain.  It is
        # intentionally simple until enough trials justify a probabilistic model.
        uncertainty = round(1.0 / math.sqrt(max(1, n)), 6)
        stats = {
            "completed_runs": n,
            "median_sharpe": _median(row["sharpe"] for row in items),
            "median_fitness": _median(row["fitness"] for row in items),
            "median_turnover": _median(row["turnover"] for row in items),
            "median_self_correlation": _median(row["self_correlation"] for row in items),
            "pass_rate": round(passes / n, 6),
            "annual_min_sharpe": min(annual_values) if annual_values else None,
            "uncertainty": uncertainty,
        }
        connection.execute(
            """INSERT INTO motif_stats(
                context_key,role_motif_hash,field_theme,horizon_bucket,completed_runs,median_sharpe,
                median_fitness,median_turnover,median_self_correlation,pass_rate,annual_min_sharpe,
                uncertainty,stats_json,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                key, role_hash, theme, horizon, n, stats["median_sharpe"], stats["median_fitness"],
                stats["median_turnover"], stats["median_self_correlation"], stats["pass_rate"],
                stats["annual_min_sharpe"], uncertainty, json_dumps(stats), utc_now(),
            ),
        )
    return {"completed_runs": len(rows), "contexts": len(groups)}


def context_stats(connection: sqlite3.Connection, *, role_motif_hash: str | None = None, field_theme: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    rows = connection.execute(
        """SELECT * FROM motif_stats
           WHERE (? IS NULL OR role_motif_hash=?) AND (? IS NULL OR field_theme=?)
           ORDER BY completed_runs DESC,pass_rate DESC LIMIT ?""",
        (role_motif_hash, role_motif_hash, field_theme, field_theme, limit),
    ).fetchall()
    return [dict(row) for row in rows]


__all__ = ["context_stats", "rebuild_motif_stats"]
