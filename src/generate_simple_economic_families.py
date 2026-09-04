from __future__ import annotations

import sqlite3
from pathlib import Path
from itertools import product

DB_PATH = Path("data/db/wq_alpha_os.sqlite")

# Field groups are deliberately small. The goal is not random generation,
# but economically interpretable two-leg alpha families.
FIELD_GROUPS = {
    "value": [
        "mdl177_2_deepvaluefactor_ttmcfp",
        "relative_valuation_rank_derivative",
        "fcf_yield_times_forward_roe",
    ],
    "quality": [
        "fscore_total",
        "cashflow_efficiency_rank_derivative",
        "earnings_certainty_rank_derivative",
    ],
    "growth": [
        "growth_potential_rank_derivative",
    ],
    "revision": [
        "analyst_revision_rank_derivative",
        "high_low_eps_revision_sum",
    ],
}

# Prior beliefs about direction. These are hypotheses, not truth.
# The generator also creates full-expression reverse variants.
FIELD_DIRECTION = {
    # Current tests suggest analyst_revision direction is unstable and often better reversed.
    "analyst_revision_rank_derivative": "reverse",
    # Relative valuation high may mean expensive, so reverse it by default.
    "relative_valuation_rank_derivative": "reverse",
    # Value/cashflow-to-price and F-score are assumed positive by default.
    "mdl177_2_deepvaluefactor_ttmcfp": "base",
    "fcf_yield_times_forward_roe": "base",
    "fscore_total": "base",
    "cashflow_efficiency_rank_derivative": "base",
    "growth_potential_rank_derivative": "base",
    "earnings_certainty_rank_derivative": "base",
    "high_low_eps_revision_sum": "base",
}

FAMILIES = [
    ("value_quality", "value", "quality"),
    ("value_growth", "value", "growth"),
    ("value_revision", "value", "revision"),
    ("growth_quality", "growth", "quality"),
    ("revision_quality", "revision", "quality"),
]

WINDOWS = [60, 120, 252]
GROUPS = ["industry", "subindustry"]
WEIGHTS = [(0.50, 0.50), (0.65, 0.35), (0.35, 0.65)]


def connect():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")
    return sqlite3.connect(DB_PATH)


def get_available_fields(cur) -> set[str]:
    return {r[0] for r in cur.execute("SELECT field_name FROM fields").fetchall()}


def ensure_columns(cur):
    # Useful if the starter DB/table is old.
    cur.execute("PRAGMA table_info(alpha_candidates)")
    cols = {r[1] for r in cur.fetchall()}
    if not cols:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS alpha_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                expression TEXT UNIQUE,
                family TEXT,
                fields_used TEXT,
                operators_used TEXT,
                hypothesis TEXT,
                expected_turnover TEXT,
                expected_risk TEXT,
                status TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def normalized_signal(field: str, window: int, group: str, direction: str | None = None) -> str:
    base = f"group_rank(ts_rank({field}, {window}), {group})"
    direction = direction or FIELD_DIRECTION.get(field, "base")
    if direction == "reverse":
        return f"reverse({base})"
    return base


def two_leg_combo(sig1: str, sig2: str, w1: float, w2: float) -> str:
    return (
        f"add(multiply({w1:.2f}, {sig1}), "
        f"multiply({w2:.2f}, {sig2}), filter=true)"
    )


def insert_candidate(cur, expression: str, family: str, fields_used: str, hypothesis: str, status: str):
    cur.execute(
        """
        INSERT OR IGNORE INTO alpha_candidates (
            expression, family, fields_used, operators_used,
            hypothesis, expected_turnover, expected_risk, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            expression,
            family,
            fields_used,
            "group_rank,ts_rank,add,multiply,reverse",
            hypothesis,
            "low-medium",
            "simple_economic_family; no trade_when; no normalize; two-leg only; test TRAIN/TEST/IS before mutating",
            status,
        ),
    )


def generate_component_scouts(cur, available: set[str]) -> int:
    created = 0
    core_fields = []
    for fields in FIELD_GROUPS.values():
        core_fields.extend(fields)

    for field in core_fields:
        if field not in available:
            continue
        for window, group in product(WINDOWS, GROUPS):
            base = f"group_rank(ts_rank({field}, {window}), {group})"
            rev = f"reverse({base})"
            for expr, direction in [(base, "base"), (rev, "reverse")]:
                insert_candidate(
                    cur,
                    expr,
                    f"component_scout_{field}_{window}_{group}_{direction}",
                    field,
                    f"Component direction scout for {field}. Test only to learn direction; do not treat as final alpha.",
                    "component_scout",
                )
                created += cur.rowcount
    return created


def generate_simple_families(cur, available: set[str]) -> int:
    created = 0
    for family_name, group_a, group_b in FAMILIES:
        fields_a = [f for f in FIELD_GROUPS[group_a] if f in available]
        fields_b = [f for f in FIELD_GROUPS[group_b] if f in available]

        for fa, fb in product(fields_a, fields_b):
            if fa == fb:
                continue
            for group in GROUPS:
                for wa, wb in WEIGHTS:
                    # Keep value/quality-like fields slow; revision/growth may use 120 as well.
                    windows_a = [252] if group_a in {"value", "quality"} else [120, 252]
                    windows_b = [252] if group_b in {"value", "quality"} else [120, 252]

                    for win_a, win_b in product(windows_a, windows_b):
                        sa = normalized_signal(fa, win_a, group)
                        sb = normalized_signal(fb, win_b, group)
                        expr = two_leg_combo(sa, sb, wa, wb)
                        rev_expr = f"reverse({expr})"

                        fam = f"{family_name}_{fa}_{fb}_{group}_{win_a}_{win_b}_{wa:.2f}_{wb:.2f}"
                        fields_used = f"{fa},{fb}"
                        hyp = (
                            f"Simple two-leg economic family: {group_a} field {fa} + {group_b} field {fb}. "
                            f"Each leg is normalized by ts_rank then group_rank. No liquidity filter and no normalize layer."
                        )

                        insert_candidate(cur, expr, fam, fields_used, hyp, "simple_econ_family")
                        created += cur.rowcount

                        # Also store full reverse because WQ field direction is often ambiguous.
                        insert_candidate(cur, rev_expr, fam + "_full_reverse", fields_used, hyp + " Full reverse variant.", "simple_econ_family")
                        created += cur.rowcount
    return created


def main():
    conn = connect()
    cur = conn.cursor()
    ensure_columns(cur)

    available = get_available_fields(cur)
    scout_count = generate_component_scouts(cur, available)
    family_count = generate_simple_families(cur, available)

    conn.commit()

    status_counts = cur.execute(
        "SELECT status, COUNT(*) FROM alpha_candidates GROUP BY status ORDER BY status"
    ).fetchall()
    conn.close()

    print(f"Generated/inserted {scout_count} component scout candidates.")
    print(f"Generated/inserted {family_count} simple economic family candidates.")
    print("Status counts:")
    for status, n in status_counts:
        print(f"  {status}: {n}")


if __name__ == "__main__":
    main()
