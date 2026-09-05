from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
import sqlite3
from typing import Any

from ..config import load_defaults
from ..db import utc_now
from .scorer import check_summary


@dataclass(frozen=True)
class RunDiagnosis:
    action: str
    failure_mode: str
    rationale: str
    allowed_change: str
    priority: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _annual_negative(annual_json: Any) -> bool:
    if not annual_json:
        return False
    try:
        payload = json.loads(annual_json) if isinstance(annual_json, str) else annual_json
    except (TypeError, ValueError):
        return False
    rows = payload if isinstance(payload, list) else payload.get("value", []) if isinstance(payload, dict) else []
    for row in rows:
        if not isinstance(row, dict) or str(row.get("stage") or "IS").upper() != "IS":
            continue
        sharpe = _number(row.get("sharpe"))
        pnl = _number(row.get("pnl"))
        if sharpe is not None and sharpe < 0:
            return True
        if pnl is not None and pnl < 0:
            return True
    return False


def diagnose_run(row: sqlite3.Row | dict[str, Any]) -> RunDiagnosis:
    keys = set(row.keys())
    get = lambda name, default=None: row[name] if name in keys else default
    limits = load_defaults()["research"]
    min_sharpe = float(limits.get("promotion_min_sharpe", 1.25))
    min_fitness = float(limits.get("promotion_min_fitness", 1.0))
    max_corr = float(limits.get("promotion_max_self_correlation", 0.7))
    status = str(get("platform_status", "") or "").upper()
    if status != "COMPLETE":
        return RunDiagnosis("HOLD", "platform_error", "Platform evidence is incomplete; do not infer alpha quality.", "none", 0.0)

    checks_raw = get("checks_json", "[]")
    try:
        checks = json.loads(checks_raw or "[]") if isinstance(checks_raw, str) else checks_raw
    except (TypeError, ValueError):
        checks = []
    _, failed, failures = check_summary(checks)
    if failed:
        return RunDiagnosis("DIAGNOSE_CHECK", "brain_check_failed", f"BRAIN hard check failed: {', '.join(failures[:2])}", "change_only_the_failed_constraint", 0.95)

    sharpe = _number(get("sharpe"))
    fitness = _number(get("fitness"))
    turnover = _number(get("turnover"))
    corr = _number(get("self_correlation"))
    annual_bad = _annual_negative(get("annual_json"))

    if sharpe is None or fitness is None:
        return RunDiagnosis("HOLD", "missing_metrics", "Missing core metrics; do not branch from incomplete evidence.", "none", 0.0)
    if sharpe < 0:
        return RunDiagnosis("DIRECTION_DIAGNOSTIC", "negative_sharpe", "One sign diagnostic is allowed; if it also fails, stop the mechanism.", "polarity_only", 0.9)
    if annual_bad and sharpe < min_sharpe:
        return RunDiagnosis("STOP", "annual_instability", "Weak aggregate performance plus a negative year does not justify more tuning.", "none", 0.92)
    if corr is not None and corr > max_corr:
        if sharpe >= min_sharpe * 0.9 or fitness >= min_fitness * 0.9:
            return RunDiagnosis("BRANCH_SEMANTIC", "high_self_correlation", "The signal has useful strength but lacks diversity; parameter tweaks are forbidden.", "field_or_economic_mechanism", 1.0)
        return RunDiagnosis("STOP", "high_corr_weak_signal", "Correlation is high without enough standalone quality; do not spend more trials on this family.", "none", 0.88)
    if turnover is not None and turnover > 0.7:
        return RunDiagnosis("TURNOVER_INTERVENTION", "high_turnover", "Change one position-smoothing/gating dimension only.", "hump_or_decay_or_independent_gate", 0.82)
    if turnover is not None and turnover < 0.01:
        return RunDiagnosis("RETHINK_TRANSFORM", "flat_signal", "The signal barely changes; inspect update cadence/transform rather than lengthening the window.", "transform_or_field_semantics", 0.85)
    if fitness < min_fitness:
        if sharpe >= min_sharpe * 0.8:
            return RunDiagnosis("REFINE_ONE_DIMENSION", "near_threshold_fitness", "Promising strength but insufficient fitness; allow one hypothesis-driven refinement.", "one_of_horizon_peer_control_or_smoothing", 0.8)
        return RunDiagnosis("STOP", "low_fitness", "Both research utility and fitness are too weak for local tuning.", "none", 0.7)
    if sharpe < min_sharpe:
        return RunDiagnosis("REFINE_ONE_DIMENSION", "near_threshold_sharpe", "Fitness is acceptable but Sharpe is short; change one structural dimension only.", "one_structural_dimension", 0.72)
    if annual_bad:
        return RunDiagnosis("ROBUSTNESS_BRANCH", "annual_instability", "Aggregate metrics pass but yearly evidence is fragile; test robustness, not more fit optimization.", "horizon_or_semantic_confirmation", 0.78)
    return RunDiagnosis("HOLD_FOR_PROMOTION_CHECKS", "promising", "Core metrics are promising; complete correlation/annual/check evidence before further mutation.", "none", 0.65)


def choose_family(connection: sqlite3.Connection) -> str | None:
    rows = connection.execute(
        """SELECT f.family,f.completed_runs,f.total_reward,
                  coalesce(t.effective_trial_count,0) trials,coalesce(t.stopped,0) stopped
           FROM family_stats f LEFT JOIN family_trial_stats t ON t.family=f.family"""
    ).fetchall()
    rows = [row for row in rows if not int(row[4])]
    if not rows:
        row = connection.execute(
            """SELECT a.family FROM alpha_artifacts a
               LEFT JOIN family_trial_stats t ON t.family=a.family
               WHERE a.status!='legacy_unverified' AND coalesce(t.stopped,0)=0
               GROUP BY a.family ORDER BY count(*) DESC LIMIT 1"""
        ).fetchone()
        return row[0] if row else None
    total = max(1, sum(int(row[1]) for row in rows))
    def objective(row: sqlite3.Row) -> float:
        completed = int(row[1])
        if completed == 0:
            return float("inf")
        mean_reward = float(row[2]) / completed
        exploration = math.sqrt(2 * math.log(total) / completed)
        trial_penalty = 0.12 * math.sqrt(max(0, int(row[3])))
        return mean_reward + exploration - trial_penalty
    return str(max(rows, key=objective)[0])


def mutation_hint(row: sqlite3.Row) -> str:
    diagnosis = diagnose_run(row)
    return f"{diagnosis.action}: {diagnosis.rationale} Chỉ được đổi: {diagnosis.allowed_change}."


def mark_family_stopped(connection: sqlite3.Connection, family: str, reason: str) -> None:
    connection.execute(
        """INSERT INTO family_trial_stats(
            family,effective_trial_count,semantic_branches,parameter_only_trials,stopped,stop_reason,updated_at
        ) VALUES(?,0,0,0,1,?,?) ON CONFLICT(family) DO UPDATE SET
        stopped=1,stop_reason=excluded.stop_reason,updated_at=excluded.updated_at""",
        (family, reason, utc_now()),
    )


def controlled_cycle_plan(connection: sqlite3.Connection, budget: int = 12) -> dict[str, Any]:
    """Allocate a 50/25/25 research cycle without calling a model or BRAIN."""
    budget = max(1, int(budget))
    explore = max(1, round(budget * 0.50))
    refine = max(0, round(budget * 0.25))
    diversity = max(0, budget - explore - refine)

    rows = connection.execute(
        """SELECT a.id artifact_id,a.family,a.expression,r.*
           FROM alpha_artifacts a JOIN simulation_runs r ON r.artifact_id=a.id
           WHERE r.platform_status='COMPLETE' ORDER BY r.finished_at DESC"""
    ).fetchall()
    diagnosed = [{"artifact_id": row["artifact_id"], "family": row["family"], **diagnose_run(row).to_dict()} for row in rows]
    refinement = [item for item in diagnosed if item["action"] in {"REFINE_ONE_DIMENSION", "TURNOVER_INTERVENTION", "DIRECTION_DIAGNOSTIC"}][:refine]
    diversity_items = [item for item in diagnosed if item["action"] in {"BRANCH_SEMANTIC", "ROBUSTNESS_BRANCH"}][:diversity]
    stopped = [item for item in diagnosed if item["action"] == "STOP"]
    discovered_cards = int(connection.execute("SELECT count(*) FROM hypothesis_cards WHERE status='discovered'").fetchone()[0])
    return {
        "budget": budget,
        "quotas": {"new_hypotheses": explore, "targeted_refinement": refine, "diversity_or_robustness": diversity},
        "available_discovered_cards": discovered_cards,
        "refinement_parents": refinement,
        "diversity_parents": diversity_items,
        "stop_candidates": stopped,
        "rules": [
            "One child changes one research dimension.",
            "High self-correlation routes to semantic branching, never parameter tuning.",
            "Multi-horizon variants count as robustness/sensitivity, not novelty.",
            "No simulation is launched by this planning command.",
        ],
    }


__all__ = [
    "RunDiagnosis",
    "choose_family",
    "controlled_cycle_plan",
    "diagnose_run",
    "mark_family_stopped",
    "mutation_hint",
]
