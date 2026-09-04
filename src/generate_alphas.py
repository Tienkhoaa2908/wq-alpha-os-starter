from __future__ import annotations

from sqlalchemy import select, delete
from src.schema import make_session, Field, AlphaCandidate


CORE_DATASET_PRIORITY = {
    "Fundamental Scores": 100,
    "Systematic Risk Metrics": 95,
    "Analysts' Factor Model": 90,
    "Company Fundamental Data for Equity": 80,
    "Relationship Data for Equity": 55,
    "Price Volume Data for Equity": 30,
    "Report Footnotes": 20,
}


BAD_FIELD_KEYWORDS = [
    "ticker", "cusip", "isin", "sedol", "currency", "country",
    "split", "adjfactor", "identifier"
]


def safe_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default


def safe_int(x, default=0):
    try:
        return int(x)
    except Exception:
        return default


def is_bad_field(f: Field) -> bool:
    name = (f.field_name or "").lower()
    desc = (f.description or "").lower()
    text = f"{name} {desc}"

    if f.field_type != "Matrix":
        return True

    if any(k in text for k in BAD_FIELD_KEYWORDS):
        return True

    if f.field_role in {"identifier", "group_control", "scale_or_control"}:
        return True

    if safe_float(f.coverage) < 40:
        return True

    if safe_float(f.date_coverage) < 90:
        return True

    return False


def dataset_priority(f: Field) -> int:
    return CORE_DATASET_PRIORITY.get(f.dataset_name or "", 10)


def field_score(f: Field) -> float:
    score = 0.0

    coverage = safe_float(f.coverage)
    date_coverage = safe_float(f.date_coverage)
    alphas = safe_int(f.alphas_count)

    score += min(coverage, 100) * 0.25
    score += min(date_coverage, 100) * 0.20
    score += dataset_priority(f) * 0.25

    if f.expected_turnover == "low":
        score += 15
    elif f.expected_turnover == "medium":
        score += 8
    elif f.expected_turnover == "high":
        score -= 10

    if f.economic_theme != "unknown":
        score += 10

    # alphas_count rất cao có nghĩa field phổ biến, nhưng quá cao có thể crowded.
    if 100 <= alphas <= 20000:
        score += 8
    elif alphas > 20000:
        score += 2

    if f.dataset_name == "Report Footnotes":
        score -= 15

    if f.category == "Price Volume":
        score -= 10

    return score


def infer_operators(expr: str) -> str:
    known = [
        "rank", "group_rank", "group_neutralize", "group_zscore",
        "ts_rank", "ts_backfill", "group_backfill", "ts_delta",
        "ts_mean", "ts_sum", "ts_std_dev", "ts_decay_linear",
        "trade_when", "multiply", "divide", "winsorize",
        "reverse", "abs", "bucket", "densify"
    ]
    return ",".join([op for op in known if op in expr])


def add_candidate(session, expression, family, fields_used, hypothesis, expected_turnover, expected_risk):
    existing = session.execute(
        select(AlphaCandidate).where(AlphaCandidate.expression == expression)
    ).scalar_one_or_none()

    if existing:
        return False

    session.add(AlphaCandidate(
        expression=expression,
        family=family,
        fields_used=fields_used,
        operators_used=infer_operators(expression),
        hypothesis=hypothesis,
        expected_turnover=expected_turnover,
        expected_risk=expected_risk,
        status="new"
    ))

    return True


def generate_model_candidates(session, fields: list[Field]) -> int:
    created = 0

    model_fields = [
        f for f in fields
        if not is_bad_field(f)
        and f.dataset_name in {"Fundamental Scores", "Analysts' Factor Model", "Systematic Risk Metrics"}
    ]

    model_fields = sorted(model_fields, key=field_score, reverse=True)[:80]

    for f in model_fields:
        name = f.field_name

        templates = [
            (
                f"group_neutralize(rank({name}), industry)",
                "model_rank_industry_neutral",
                "medium"
            ),
            (
                f"group_rank(rank({name}), subindustry)",
                "model_subindustry_rank",
                "medium"
            ),
            (
                f"group_rank(ts_rank({name}, 60), industry)",
                "model_ts_rank_60",
                "medium"
            ),
            (
                f"group_rank(ts_rank({name}, 120), industry)",
                "model_ts_rank_120",
                "medium"
            ),
            (
                f"trade_when(volume > adv20, group_rank(rank({name}), industry), -1)",
                "model_liquidity_filtered",
                "medium"
            ),
        ]

        for expr, family, turnover in templates:
            created += add_candidate(
                session=session,
                expression=expr,
                family=family,
                fields_used=name,
                hypothesis=f"Use model field {name} from {f.dataset_name} as core signal; normalize by industry/subindustry.",
                expected_turnover=turnover,
                expected_risk=f"coverage={f.coverage}; dataset={f.dataset_name}; theme={f.economic_theme}"
            )

    return created


def generate_fundamental_candidates(session, fields: list[Field]) -> int:
    created = 0

    fields_by_name = {f.field_name: f for f in fields}

    # Chỉ dùng các field phổ thông trước. Đừng dùng field footnote quá niche.
    preferred_names = [
        "assets", "liabilities", "debt", "debt_lt",
        "sales", "revenue",
        "income", "operating_income", "ebit", "ebitda", "eps",
        "cashflow_op", "equity", "capex", "enterprise_value"
    ]

    selected = [
        fields_by_name[n] for n in preferred_names
        if n in fields_by_name and not is_bad_field(fields_by_name[n])
    ]

    # Thêm field quality/growth/leverage điểm cao từ Company Fundamental
    extra = [
        f for f in fields
        if not is_bad_field(f)
        and f.dataset_name == "Company Fundamental Data for Equity"
        and f.economic_theme in {
            "quality_profitability",
            "growth",
            "leverage_balance_sheet",
            "balance_sheet_cashflow"
        }
    ]

    selected = list({f.field_name: f for f in (selected + sorted(extra, key=field_score, reverse=True)[:40])}.values())

    for f in selected:
        name = f.field_name
        theme = f.economic_theme or ""

        base_templates = [
            (
                f"group_rank(ts_rank(ts_backfill({name}, 252), 252), industry)",
                "fundamental_level_ts_rank",
                "low"
            ),
            (
                f"group_zscore(winsorize(ts_backfill({name}, 252), std=4), subindustry)",
                "fundamental_group_zscore",
                "low"
            ),
        ]

        for expr, family, turnover in base_templates:
            created += add_candidate(
                session=session,
                expression=expr,
                family=family,
                fields_used=name,
                hypothesis=f"Use slow-moving fundamental field {name} as {theme}; rank/standardize within industry.",
                expected_turnover=turnover,
                expected_risk=f"coverage={f.coverage}; missing_risk={f.missing_risk}"
            )

        # Ratio templates
        if name not in {"assets", "cap", "enterprise_value"}:
            ratio_templates = [
                (
                    f"group_rank(ts_rank(ts_backfill(divide({name}, assets), 252), 252), industry)",
                    "fundamental_scaled_by_assets",
                    "low"
                ),
                (
                    f"group_rank(ts_rank(ts_backfill(divide({name}, cap), 252), 252), industry)",
                    "fundamental_scaled_by_cap",
                    "low"
                ),
            ]

            for expr, family, turnover in ratio_templates:
                created += add_candidate(
                    session=session,
                    expression=expr,
                    family=family,
                    fields_used=f"{name},assets,cap",
                    hypothesis=f"Scale {name} by assets/cap to make fundamental values comparable across firms.",
                    expected_turnover=turnover,
                    expected_risk=f"coverage={f.coverage}; ratio_signal=True"
                )

        # Direction adjustment for leverage
        if theme == "leverage_balance_sheet":
            expr = f"group_rank(ts_rank(reverse(ts_backfill(divide({name}, assets), 252)), 252), industry)"
            created += add_candidate(
                session=session,
                expression=expr,
                family="low_leverage_quality",
                fields_used=f"{name},assets",
                hypothesis=f"Lower {name}/assets may indicate lower financial risk; reverse leverage signal.",
                expected_turnover="low",
                expected_risk=f"coverage={f.coverage}; leverage_direction_reversed=True"
            )

    return created


def generate_relationship_candidates(session, fields: list[Field]) -> int:
    created = 0

    rel_fields = [
        f for f in fields
        if not is_bad_field(f)
        and f.dataset_name == "Relationship Data for Equity"
        and (
            f.field_name.startswith("rel_ret")
            or f.field_name.startswith("rel_num")
            or "competitor" in (f.description or "").lower()
            or "customer" in (f.description or "").lower()
            or "partner" in (f.description or "").lower()
        )
    ]

    rel_fields = sorted(rel_fields, key=field_score, reverse=True)[:30]

    for f in rel_fields:
        name = f.field_name

        templates = [
            (
                f"group_rank(ts_rank({name}, 60), industry)",
                "relationship_ts_rank",
                "medium"
            ),
            (
                f"group_neutralize(rank({name}), industry)",
                "relationship_industry_neutral",
                "medium"
            ),
        ]

        for expr, family, turnover in templates:
            created += add_candidate(
                session=session,
                expression=expr,
                family=family,
                fields_used=name,
                hypothesis=f"Use relationship field {name} as network/peer signal.",
                expected_turnover=turnover,
                expected_risk=f"coverage={f.coverage}; relationship_data=True"
            )

    return created


def generate_candidates():
    Session = make_session()

    with Session() as session:
        # Xóa candidates cũ vì generator cũ chất lượng thấp
        session.execute(delete(AlphaCandidate))
        session.commit()

        fields = session.execute(select(Field)).scalars().all()

        created = 0
        created += generate_model_candidates(session, fields)
        created += generate_fundamental_candidates(session, fields)
        created += generate_relationship_candidates(session, fields)

        session.commit()

        print(f"Generated {created} improved alpha candidates.")


if __name__ == "__main__":
    generate_candidates()