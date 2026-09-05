from __future__ import annotations

"""Semantic knowledge base for active WorldQuant BRAIN operators.

The live BRAIN snapshot is the source of truth for *availability*.  This module
adds research semantics: what an operator does, where it belongs in an alpha
pipeline, what information it destroys, and which combinations deserve hard
or soft restrictions.  It deliberately does not claim that an operator is
profitable; profitability is learned from simulation evidence elsewhere.
"""

from dataclasses import asdict, dataclass
import sqlite3
from typing import Any, Iterable

from ..operator_registry import active_brain_operator_rows


@dataclass(frozen=True)
class OperatorKnowledge:
    name: str
    category: str
    definition: str
    description: str
    primary_role: str
    secondary_roles: tuple[str, ...]
    stage: str
    state_class: str
    input_kind: str
    output_kind: str
    unit_effect: str
    information_loss: str
    tail_sensitivity: str
    coverage_effect: str
    turnover_tendency: str
    preferred_field_forms: tuple[str, ...]
    discouraged_field_forms: tuple[str, ...]
    hard_rules: tuple[str, ...]
    soft_rules: tuple[str, ...]
    parameter_policy: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key, item in tuple(value.items()):
            if isinstance(item, tuple):
                value[key] = list(item)
        return value


# Explicit semantic roles for every operator in the 66-operator active snapshot.
# Definitions/signatures remain live and are merged from active_brain_operators.
SEMANTICS: dict[str, dict[str, Any]] = {
    "abs": dict(role="magnitude_only", stage="feature", loss="high", unit="preserve", tail="neutral", forms=("dispersion", "risk", "surprise"), soft=("Use only when sign is not economically meaningful.",)),
    "add": dict(role="additive_composition", stage="composition", loss="low", unit="requires_compatible", tail="amplify", soft=("Inputs should share units or already be dimensionless/standardized.",)),
    "and": dict(role="logical_conjunction", stage="condition", loss="high", unit="boolean", tail="neutral"),
    "bucket": dict(role="group_builder", stage="group_construction", loss="high", unit="group", tail="neutral", forms=("size", "liquidity", "volatility"), hard=("Output is a GROUP and should feed group operators, not numeric time-series operators.",)),
    "days_from_last_change": dict(role="information_staleness", stage="time_feature", loss="moderate", unit="days", tail="neutral", forms=("level", "forecast", "event")),
    "densify": dict(role="group_compaction", stage="group_construction", loss="moderate", unit="group", tail="neutral", hard=("Treat as GROUP-related only; do not use as a generic numeric transform.",)),
    "divide": dict(role="ratio", stage="feature", loss="low", unit="ratio", tail="high", hard=("Denominator must have economic meaning and a documented near-zero policy.",)),
    "equal": dict(role="comparison_equal", stage="condition", loss="high", unit="boolean", tail="neutral"),
    "greater": dict(role="comparison_greater", stage="condition", loss="high", unit="boolean", tail="neutral"),
    "greater_equal": dict(role="comparison_greater_equal", stage="condition", loss="high", unit="boolean", tail="neutral"),
    "group_backfill": dict(role="peer_missing_repair", stage="preparation", loss="moderate", unit="preserve", tail="reduce", coverage="increase", soft=("Use only when peer similarity is defensible; peer imputation can create artificial similarity.",)),
    "group_mean": dict(role="peer_benchmark", stage="peer_feature", loss="moderate", unit="preserve", tail="reduce", soft=("Prefer as a benchmark in a residual/spread, not as an automatic terminal signal.",)),
    "group_neutralize": dict(role="peer_residualize", stage="peer_control", loss="moderate", unit="preserve", tail="reduce"),
    "group_rank": dict(role="peer_ordinal", stage="peer_control", loss="high", unit="dimensionless", tail="reduce"),
    "group_scale": dict(role="peer_sizing", stage="output_control", loss="moderate", unit="dimensionless", tail="reduce"),
    "group_zscore": dict(role="peer_standardize", stage="peer_control", loss="moderate", unit="dimensionless", tail="medium"),
    "hump": dict(role="position_change_limiter", stage="turnover_control", loss="moderate", unit="preserve", tail="reduce", turnover="reduce", soft=("Add after a core signal exists or turnover is a measured failure mode; it is not equivalent to ts_decay_linear.",)),
    "if_else": dict(role="conditional_select", stage="condition", loss="moderate", unit="branch_dependent", tail="neutral", soft=("Every additional condition increases trial complexity and overfit burden.",)),
    "inverse": dict(role="reciprocal_nonlinear", stage="feature", loss="low", unit="reciprocal", tail="high", hard=("Input must have a near-zero policy. inverse is not a direction flip.",)),
    "is_nan": dict(role="missingness_condition", stage="condition", loss="high", unit="boolean", tail="neutral"),
    "kth_element": dict(role="historical_value_selector", stage="preparation", loss="moderate", unit="preserve", tail="neutral", soft=("Use primarily for explicit backfill/history-selection hypotheses, not generic signal extraction.",)),
    "last_diff_value": dict(role="previous_distinct_value", stage="time_feature", loss="moderate", unit="preserve", tail="neutral", forms=("forecast", "level", "event")),
    "less": dict(role="comparison_less", stage="condition", loss="high", unit="boolean", tail="neutral"),
    "less_equal": dict(role="comparison_less_equal", stage="condition", loss="high", unit="boolean", tail="neutral"),
    "log": dict(role="positive_log_compression", stage="preparation", loss="low", unit="log", tail="reduce", hard=("Input domain must be positive.",), forms=("size", "volume", "positive_level")),
    "max": dict(role="upper_envelope", stage="composition", loss="moderate", unit="requires_compatible", tail="medium", soft=("Inputs should share units/semantics.",)),
    "min": dict(role="lower_envelope", stage="composition", loss="moderate", unit="requires_compatible", tail="medium", soft=("Inputs should share units/semantics.",)),
    "multiply": dict(role="interaction_or_weighting", stage="composition", loss="low", unit="product", tail="high", soft=("Prefer bounded/normalized inputs unless multiplicative units are the hypothesis.",)),
    "normalize": dict(role="market_standardize_and_clip", stage="output_control", loss="moderate", unit="dimensionless", tail="reduce", soft=("Usually terminal; do not stack with equivalent standardizers without a reason.",)),
    "not": dict(role="logical_negation", stage="condition", loss="high", unit="boolean", tail="neutral"),
    "not_equal": dict(role="comparison_not_equal", stage="condition", loss="high", unit="boolean", tail="neutral"),
    "or": dict(role="logical_disjunction", stage="condition", loss="high", unit="boolean", tail="neutral"),
    "power": dict(role="unsigned_curvature", stage="feature", loss="moderate", unit="power", tail="high", hard=("Non-integer powers can lose sign; prefer signed_power for signed signals.",), soft=("Do not grid-search exponents.",)),
    "quantile": dict(role="cross_section_distribution_map", stage="cross_section", loss="high", unit="dimensionless", tail="reduce", soft=("Use only when distribution shaping is part of the hypothesis; it is more complex than rank/zscore.",)),
    "rank": dict(role="market_ordinal", stage="cross_section", loss="high", unit="dimensionless", tail="reduce"),
    "reverse": dict(role="polarity_flip", stage="direction", loss="none", unit="preserve", tail="neutral", soft=("May be used once as a diagnostic when the economic sign is uncertain or measured Sharpe is negative.",)),
    "scale": dict(role="portfolio_sizing", stage="output_control", loss="moderate", unit="scaled", tail="neutral"),
    "sign": dict(role="sign_discretization", stage="feature", loss="very_high", unit="dimensionless", tail="reduce", soft=("Use only for genuinely binary sign hypotheses; it discards magnitude.",)),
    "signed_power": dict(role="signed_curvature", stage="feature", loss="moderate", unit="power", tail="configurable", soft=("Use a small canonical exponent set only when curvature is justified.",)),
    "sqrt": dict(role="positive_sqrt_compression", stage="preparation", loss="low", unit="sqrt", tail="reduce", hard=("Input domain must be non-negative; use signed_power(x,0.5) when sign must survive.",)),
    "subtract": dict(role="spread_or_residual", stage="feature", loss="low", unit="requires_compatible", tail="medium", soft=("Inputs should have comparable units or already be normalized.",)),
    "trade_when": dict(role="stateful_trade_gate", stage="turnover_control", loss="moderate", unit="preserve", tail="neutral", turnover="reduce", soft=("Do not use to rescue a weak core signal; condition should be economically independent from the core.",)),
    "ts_arg_max": dict(role="maximum_recency", stage="time_feature", loss="high", unit="days", tail="reduce"),
    "ts_arg_min": dict(role="minimum_recency", stage="time_feature", loss="high", unit="days", tail="reduce"),
    "ts_av_diff": dict(role="local_mean_deviation", stage="time_feature", loss="low", unit="preserve", tail="medium"),
    "ts_backfill": dict(role="time_missing_repair", stage="preparation", loss="moderate", unit="preserve", tail="neutral", coverage="increase", soft=("Lookback must respect update cadence; backfill can turn stale data into an apparently active signal.",)),
    "ts_corr": dict(role="rolling_correlation", stage="relation_feature", loss="moderate", unit="dimensionless", tail="reduce", hard=("Two source series require an explicit relational hypothesis.",)),
    "ts_count_nans": dict(role="missingness_intensity", stage="diagnostic_feature", loss="high", unit="count", tail="reduce", soft=("Default to diagnostics; promote to signal only if information availability itself is hypothesized.",)),
    "ts_covariance": dict(role="rolling_covariance", stage="relation_feature", loss="low", unit="product", tail="high", hard=("Two source series require an explicit relational hypothesis.",), soft=("Prefer ts_corr when scale is not economically meaningful.",)),
    "ts_decay_linear": dict(role="recency_weighted_smoothing", stage="time_feature", loss="moderate", unit="preserve", tail="reduce", turnover="reduce", soft=("This smooths history; it is not interchangeable with hump, which limits position changes.",)),
    "ts_delay": dict(role="historical_anchor", stage="helper", loss="none", unit="preserve", tail="neutral", soft=("Use inside a change/ratio/trend construction; lag alone is not a research mechanism.",)),
    "ts_delta": dict(role="absolute_change", stage="time_feature", loss="low", unit="preserve", tail="medium", forms=("forecast", "price", "level", "flow")),
    "ts_mean": dict(role="rolling_mean_or_baseline", stage="time_feature", loss="moderate", unit="preserve", tail="reduce"),
    "ts_product": dict(role="rolling_product_compound", stage="time_feature", loss="low", unit="compound", tail="very_high", hard=("Use only when multiplicative/compounding meaning is explicit.",)),
    "ts_quantile": dict(role="historical_distribution_map", stage="time_feature", loss="high", unit="dimensionless", tail="reduce", soft=("Higher complexity than ts_rank; require a distribution-shaping rationale.",)),
    "ts_rank": dict(role="historical_position_ordinal", stage="time_feature", loss="high", unit="dimensionless", tail="reduce", forms=("ratio", "level", "score", "valuation")),
    "ts_regression": dict(role="rolling_regression", stage="relation_feature", loss="moderate", unit="rettype_dependent", tail="medium", hard=("rettype semantics must come from the live BRAIN definition or an explicitly verified local rule before automated use.",)),
    "ts_scale": dict(role="historical_minmax_scale", stage="time_feature", loss="moderate", unit="dimensionless", tail="medium", soft=("Rolling extremes can dominate the scale until they leave the window.",)),
    "ts_std_dev": dict(role="rolling_dispersion", stage="time_feature", loss="moderate", unit="preserve", tail="medium", forms=("return", "risk", "price", "forecast")),
    "ts_step": dict(role="time_index_helper", stage="helper", loss="none", unit="days", tail="neutral", soft=("Helper for trend/regression/periodic logic, not a standalone predictive feature.",)),
    "ts_sum": dict(role="rolling_accumulation", stage="time_feature", loss="low", unit="sum", tail="medium", forms=("count", "flow", "volume", "event")),
    "ts_zscore": dict(role="historical_anomaly_standardized", stage="time_feature", loss="moderate", unit="dimensionless", tail="medium", forms=("level", "ratio", "score", "sentiment")),
    "vec_avg": dict(role="vector_average_reduce", stage="preparation", loss="moderate", unit="preserve", tail="reduce", forms=("vector_score", "vector_sentiment"), hard=("Input must be VECTOR; output is MATRIX.",)),
    "vec_sum": dict(role="vector_sum_reduce", stage="preparation", loss="low", unit="sum", tail="medium", forms=("vector_count", "vector_activity", "vector_event"), hard=("Input must be VECTOR; output is MATRIX.",)),
    "winsorize": dict(role="cross_section_tail_control", stage="pre_cross_section", loss="moderate", unit="preserve", tail="reduce", soft=("May legitimately precede zscore/group_zscore; it is not itself a standardizer.",)),
    "zscore": dict(role="market_standardize", stage="cross_section", loss="moderate", unit="dimensionless", tail="medium"),
}


def _get(item: dict[str, Any], key: str, default: Any) -> Any:
    return item[key] if key in item else default


def profile_from_live_row(row: sqlite3.Row | dict[str, Any]) -> OperatorKnowledge:
    name = str(row["name"]).lower()
    base = SEMANTICS.get(name, {})
    return OperatorKnowledge(
        name=name,
        category=str(row["category"] or ""),
        definition=str(row["signature"] if "signature" in row.keys() else row.get("definition", "") or ""),
        description=str(row["description"] or ""),
        primary_role=str(_get(base, "role", "unclassified")),
        secondary_roles=tuple(_get(base, "secondary", ())),
        stage=str(_get(base, "stage", "unclassified")),
        state_class="stateful" if name in {"hump", "trade_when"} else ("rolling" if name.startswith("ts_") else "stateless"),
        input_kind="VECTOR" if name in {"vec_avg", "vec_sum"} else ("GROUP" if name == "densify" else "MATRIX_OR_SCALAR"),
        output_kind="GROUP" if name in {"bucket", "densify"} else ("BOOLEAN" if name in {"and", "or", "not", "is_nan", "equal", "not_equal", "greater", "greater_equal", "less", "less_equal"} else "MATRIX"),
        unit_effect=str(_get(base, "unit", "preserve")),
        information_loss=str(_get(base, "loss", "unknown")),
        tail_sensitivity=str(_get(base, "tail", "unknown")),
        coverage_effect=str(_get(base, "coverage", "neutral")),
        turnover_tendency=str(_get(base, "turnover", "unknown")),
        preferred_field_forms=tuple(_get(base, "forms", ())),
        discouraged_field_forms=tuple(_get(base, "discouraged", ())),
        hard_rules=tuple(_get(base, "hard", ())),
        soft_rules=tuple(_get(base, "soft", ())),
        parameter_policy=(
            "window_from_field_horizon_prior_no_dense_scan" if name.startswith("ts_") and name not in {"ts_step"}
            else "canonical_small_set_only" if name in {"power", "signed_power", "winsorize", "hump", "quantile", "normalize"}
            else "hypothesis_defined"
        ),
    )


def active_operator_knowledge(connection: sqlite3.Connection) -> dict[str, OperatorKnowledge]:
    rows = active_brain_operator_rows(connection)
    return {str(row["name"]).lower(): profile_from_live_row(row) for row in rows}


def operator_profile(connection: sqlite3.Connection, name: str) -> OperatorKnowledge | None:
    return active_operator_knowledge(connection).get(name.strip().lower())


def assert_semantic_coverage(connection: sqlite3.Connection) -> dict[str, Any]:
    live = active_operator_knowledge(connection)
    unclassified = sorted(name for name, profile in live.items() if profile.primary_role == "unclassified")
    return {
        "active": len(live),
        "semantically_profiled": len(live) - len(unclassified),
        "unclassified": unclassified,
        "complete": not unclassified,
    }


def prompt_payload(connection: sqlite3.Connection, names: Iterable[str] | None = None) -> list[dict[str, Any]]:
    profiles = active_operator_knowledge(connection)
    selected = set(str(name).lower() for name in names) if names is not None else set(profiles)
    result = []
    for name in sorted(selected & set(profiles)):
        profile = profiles[name]
        result.append({
            "name": profile.name,
            "role": profile.primary_role,
            "stage": profile.stage,
            "input_kind": profile.input_kind,
            "output_kind": profile.output_kind,
            "unit_effect": profile.unit_effect,
            "hard_rules": list(profile.hard_rules),
            "parameter_policy": profile.parameter_policy,
        })
    return result


__all__ = [
    "OperatorKnowledge",
    "SEMANTICS",
    "active_operator_knowledge",
    "assert_semantic_coverage",
    "operator_profile",
    "prompt_payload",
    "profile_from_live_row",
]
