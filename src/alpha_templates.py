from dataclasses import dataclass


@dataclass
class AlphaTemplate:
    name: str
    family: str
    expression: str
    required_themes: list[str]
    expected_turnover: str
    notes: str


TEMPLATES = [
    AlphaTemplate(
        name="fundamental_ts_rank_industry_rank",
        family="quality_value_growth",
        expression="group_rank(ts_rank(ts_backfill({field}, 252), 252), industry)",
        required_themes=["quality_profitability", "growth", "leverage_balance_sheet"],
        expected_turnover="low",
        notes="Good for low-frequency fundamental signals."
    ),
    AlphaTemplate(
        name="fundamental_scaled_by_cap",
        family="valuation",
        expression="group_rank(ts_rank(ts_backfill(divide({field}, cap), 252), 252), industry)",
        required_themes=["quality_profitability", "growth"],
        expected_turnover="low",
        notes="Scale accounting value by market cap."
    ),
    AlphaTemplate(
        name="fundamental_group_zscore",
        family="quality_value",
        expression="group_zscore(winsorize(ts_backfill({field}, 252), std=4), subindustry)",
        required_themes=["quality_profitability", "growth", "leverage_balance_sheet"],
        expected_turnover="low",
        notes="Normalize within subindustry; useful for comparable accounting fields."
    ),
    AlphaTemplate(
        name="model_signal_industry_neutral",
        family="model_signal",
        expression="group_neutralize(rank(ts_rank({field}, 60)), industry)",
        required_themes=["unknown"],
        expected_turnover="medium",
        notes="Generic model-derived signal template."
    ),
    AlphaTemplate(
        name="analyst_revision",
        family="analyst_revision",
        expression="group_rank(ts_delta(ts_backfill({field}, 252), 20), industry)",
        required_themes=["analyst_revision"],
        expected_turnover="medium",
        notes="Detect forecast or estimate revisions."
    ),
    AlphaTemplate(
        name="sentiment_event",
        family="sentiment_event",
        expression="trade_when(ts_rank({field}, 60) > 0.7, rank(ts_decay_linear({field}, 5)), -1)",
        required_themes=["sentiment_event"],
        expected_turnover="medium_high",
        notes="Use only when sentiment/news coverage is acceptable."
    ),
    AlphaTemplate(
        name="price_volume_reversal",
        family="price_volume",
        expression="trade_when(volume > adv20, multiply(rank(-ts_delta(close, 5)), rank(ts_rank(divide(volume, adv20), 20)), filter=true), -1)",
        required_themes=["price_action", "liquidity_volume"],
        expected_turnover="high",
        notes="Benchmark Price Volume template; often high turnover."
    ),
]
