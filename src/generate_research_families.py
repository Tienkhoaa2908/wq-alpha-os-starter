
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path("data/db/wq_alpha_os.sqlite")


def field_exists(cur, field: str) -> bool:
    row = cur.execute("SELECT 1 FROM fields WHERE field_name = ? LIMIT 1", (field,)).fetchone()
    return row is not None


def insert_candidate(cur, expression, family, fields_used, hypothesis, status="research_family"):
    operators = []
    for op in [
        "trade_when", "normalize", "add", "multiply", "reverse", "group_rank",
        "group_neutralize", "group_zscore", "ts_rank", "ts_backfill", "winsorize"
    ]:
        if op in expression:
            operators.append(op)

    cur.execute(
        """
        INSERT OR IGNORE INTO alpha_candidates (
            expression,
            family,
            fields_used,
            operators_used,
            hypothesis,
            expected_turnover,
            expected_risk,
            status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            expression,
            family,
            ",".join(fields_used),
            ",".join(operators),
            hypothesis,
            "low-medium",
            "research_family; multi-component economic logic; test train and test; watch 2019/2020/2023 weakness",
            status,
        ),
    )


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    generated = 0

    # Family 1: Analyst revision is direction-ambiguous.
    # Use reverse because early tests showed base direction can be poor.
    # Combine with value and quality to reduce 2019/2020/2023 regime fragility.
    required = [
        "analyst_revision_rank_derivative",
        "mdl177_2_deepvaluefactor_ttmcfp",
        "fscore_total",
        "volume",
        "adv20",
    ]
    if all(field_exists(cur, f) for f in required):
        expr = (
            "trade_when(volume > adv20, "
            "normalize(add("
            "multiply(0.40, reverse(group_rank(ts_rank(analyst_revision_rank_derivative, 120), industry))), "
            "multiply(0.35, group_rank(ts_rank(mdl177_2_deepvaluefactor_ttmcfp, 252), industry)), "
            "multiply(0.25, group_rank(ts_rank(fscore_total, 252), industry)), "
            "filter=true), useStd=true, limit=3), -1)"
        )
        insert_candidate(
            cur,
            expr,
            "analyst_value_quality_liquidity",
            required,
            "Contrarian analyst revision is combined with deep value and F-score quality. Liquidity trigger avoids trading illiquid/noisy days.",
        )
        generated += 1

    # Family 2: Value + Growth + Cashflow quality.
    required = [
        "relative_valuation_rank_derivative",
        "growth_potential_rank_derivative",
        "cashflow_efficiency_rank_derivative",
    ]
    if all(field_exists(cur, f) for f in required):
        expr = (
            "normalize(add("
            "multiply(0.40, reverse(group_rank(ts_rank(relative_valuation_rank_derivative, 252), industry))), "
            "multiply(0.30, group_rank(ts_rank(growth_potential_rank_derivative, 120), industry)), "
            "multiply(0.30, group_rank(ts_rank(cashflow_efficiency_rank_derivative, 252), industry)), "
            "filter=true), useStd=true, limit=3)"
        )
        insert_candidate(
            cur,
            expr,
            "value_growth_cashflow_quality",
            required,
            "Cheapness/value is paired with growth potential and cashflow efficiency to avoid value traps.",
        )
        generated += 1

    # Family 3: Analyst revision plus EPS revision. Use reverse on analyst if direction is ambiguous.
    required = [
        "analyst_revision_rank_derivative",
        "high_low_eps_revision_sum",
        "volume",
        "adv20",
    ]
    if all(field_exists(cur, f) for f in required):
        expr = (
            "trade_when(volume > adv20, "
            "normalize(add("
            "multiply(0.55, reverse(group_rank(ts_rank(analyst_revision_rank_derivative, 120), industry))), "
            "multiply(0.45, group_rank(ts_rank(high_low_eps_revision_sum, 120), industry)), "
            "filter=true), useStd=true, limit=3), -1)"
        )
        insert_candidate(
            cur,
            expr,
            "analyst_eps_revision_liquidity",
            required,
            "Analyst-rank revision is combined with explicit EPS revision; liquidity filter controls noisy trading.",
        )
        generated += 1

    # Family 4: Pure quality/value without analyst component.
    required = [
        "fcf_yield_times_forward_roe",
        "fscore_total",
    ]
    if all(field_exists(cur, f) for f in required):
        expr = (
            "normalize(add("
            "multiply(0.60, group_rank(ts_rank(fcf_yield_times_forward_roe, 252), industry)), "
            "multiply(0.40, group_rank(ts_rank(fscore_total, 252), industry)), "
            "filter=true), useStd=true, limit=3)"
        )
        insert_candidate(
            cur,
            expr,
            "fcf_yield_forward_roe_quality",
            required,
            "Combines valuation yield and forward profitability quality; slower fundamental profile should reduce turnover.",
        )
        generated += 1

    # Direction scouts around the current promising but weak analyst field.
    scout_fields = [
        "analyst_revision_rank_derivative",
        "relative_valuation_rank_derivative",
        "fscore_total",
        "mdl177_2_deepvaluefactor_ttmcfp",
    ]
    for field in scout_fields:
        if not field_exists(cur, field):
            continue
        for window in [60, 120, 252]:
            for group in ["industry", "subindustry"]:
                base = f"group_rank(ts_rank({field}, {window}), {group})"
                rev = f"reverse({base})"
                insert_candidate(
                    cur,
                    base,
                    f"direction_scout_{field}",
                    [field],
                    f"Direction scout for {field}; base direction; window={window}; group={group}.",
                    status="direction_scout",
                )
                insert_candidate(
                    cur,
                    rev,
                    f"direction_scout_{field}",
                    [field],
                    f"Direction scout for {field}; reversed direction; window={window}; group={group}.",
                    status="direction_scout",
                )
                generated += 2

    conn.commit()
    conn.close()

    print(f"Generated {generated} research-family candidates.")


if __name__ == "__main__":
    main()
