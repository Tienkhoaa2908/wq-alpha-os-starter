from __future__ import annotations

from typing import Any


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def check_summary(checks: Any) -> tuple[int, int, list[str]]:
    if not isinstance(checks, list):
        return 0, 0, []
    passed = failed = 0
    failures: list[str] = []
    for check in checks:
        if not isinstance(check, dict):
            continue
        status = str(check.get("result") or check.get("status") or "").upper()
        if status in {"PASS", "PASSED", "SUCCESS"}:
            passed += 1
        elif status in {"FAIL", "FAILED", "ERROR"}:
            failed += 1
            failures.append(str(check.get("name") or check.get("message") or "unknown"))
    return passed, failed, failures


def score_vector(
    metrics: dict[str, Any],
    checks: Any,
    *,
    annual_summary: dict[str, Any] | None = None,
    complexity_nodes: int | None = None,
    complexity_depth: int | None = None,
    novelty_score: float | None = None,
    effective_trial_count: int | None = None,
) -> dict[str, float]:
    """Return interpretable research objectives instead of one opaque reward.

    The vector separates performance, robustness, tradability, diversity,
    simplicity, evidence quality and multiple-testing burden.  It is intended
    for scheduling/research decisions; BRAIN's own checks remain hard gates.
    """
    passed, failed, _ = check_summary(checks)
    sharpe = _number(metrics.get("sharpe")) or 0.0
    fitness = _number(metrics.get("fitness")) or 0.0
    turnover = _number(metrics.get("turnover"))
    drawdown = abs(_number(metrics.get("drawdown")) or 0.0)
    margin = _number(metrics.get("margin")) or 0.0
    self_corr = _number(metrics.get("selfCorrelation"))
    sub_sharpe = _number(metrics.get("subuniverseSharpe"))

    performance = 0.46 * sharpe + 0.40 * fitness + 0.08 * min(max(margin * 10000, 0.0), 2.0)
    if sub_sharpe is not None:
        performance += 0.06 * sub_sharpe

    annual = annual_summary or {}
    min_annual = _number(annual.get("min_sharpe"))
    mean_annual = _number(annual.get("mean_sharpe"))
    negative_years = int(annual.get("negative_sharpe_years") or 0)
    robustness = 0.0
    if min_annual is not None:
        robustness += 0.55 * min_annual
    if mean_annual is not None:
        robustness += 0.45 * mean_annual
    robustness -= 0.75 * negative_years
    robustness -= 0.08 * drawdown

    tradability = 0.0
    if turnover is not None:
        if 0.01 <= turnover <= 0.7:
            tradability += 1.0
        else:
            tradability -= 1.0
        # Mild preference for lower turnover once inside the valid region.
        if 0.01 <= turnover <= 0.7:
            tradability += max(0.0, 0.5 - turnover)

    diversity = float(novelty_score if novelty_score is not None else 0.5)
    if self_corr is None:
        diversity -= 0.35
    elif self_corr > 0.7:
        diversity -= (self_corr - 0.7) * 3.0
    else:
        diversity += (0.7 - self_corr) * 0.5

    nodes = max(1, int(complexity_nodes or 1))
    depth = max(1, int(complexity_depth or 1))
    simplicity = max(-1.0, 1.0 - 0.018 * nodes - 0.035 * depth)

    total_checks = passed + failed
    evidence_quality = (passed / total_checks if total_checks else 0.0) - 0.75 * failed
    if self_corr is None:
        evidence_quality -= 0.25

    trials = max(0, int(effective_trial_count or 0))
    trial_burden = min(2.0, 0.18 * (trials ** 0.5))

    return {
        "performance": round(performance, 6),
        "robustness": round(robustness, 6),
        "tradability": round(tradability, 6),
        "diversity": round(diversity, 6),
        "simplicity": round(simplicity, 6),
        "evidence_quality": round(evidence_quality, 6),
        "trial_burden": round(trial_burden, 6),
    }


def research_utility(vector: dict[str, float]) -> float:
    """Scalar used only for queue ordering; decisions still inspect the vector."""
    utility = (
        0.30 * vector.get("performance", 0.0)
        + 0.18 * vector.get("robustness", 0.0)
        + 0.13 * vector.get("tradability", 0.0)
        + 0.20 * vector.get("diversity", 0.0)
        + 0.07 * vector.get("simplicity", 0.0)
        + 0.12 * vector.get("evidence_quality", 0.0)
        - 0.20 * vector.get("trial_burden", 0.0)
    )
    return round(utility, 6)


def score(metrics: dict[str, Any], checks: Any) -> float:
    # Backward-compatible scalar for existing simulation ingestion.
    vector = score_vector(metrics, checks)
    return research_utility(vector)


def promotable(metrics: dict[str, Any], checks: Any, limits: dict[str, Any]) -> bool:
    _, failed, _ = check_summary(checks)
    sharpe = _number(metrics.get("sharpe")) or -999
    fitness = _number(metrics.get("fitness")) or -999
    self_corr = _number(metrics.get("selfCorrelation"))
    return (
        sharpe >= float(limits["promotion_min_sharpe"])
        and fitness >= float(limits["promotion_min_fitness"])
        and (self_corr is None or self_corr <= float(limits["promotion_max_self_correlation"]))
        and (not limits["promotion_requires_all_checks"] or failed == 0)
    )


__all__ = ["check_summary", "promotable", "research_utility", "score", "score_vector"]
