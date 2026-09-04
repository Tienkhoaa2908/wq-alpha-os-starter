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


def score(metrics: dict[str, Any], checks: Any) -> float:
    _, failed, _ = check_summary(checks)
    sharpe = _number(metrics.get("sharpe")) or 0.0
    fitness = _number(metrics.get("fitness")) or 0.0
    turnover = _number(metrics.get("turnover"))
    drawdown = abs(_number(metrics.get("drawdown")) or 0.0)
    margin = _number(metrics.get("margin")) or 0.0
    self_corr = _number(metrics.get("selfCorrelation"))
    reward = 0.38 * sharpe + 0.32 * fitness + 0.12 * min(margin * 10000, 2.0) - 0.08 * drawdown
    if turnover is not None and (turnover < 0.01 or turnover > 0.7):
        reward -= 0.5
    if self_corr is not None and self_corr > 0.7:
        reward -= (self_corr - 0.7) * 2
    reward -= failed * 0.75
    return round(reward, 6)


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
