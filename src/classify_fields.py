from __future__ import annotations
import re


def has_any(text: str, words: list[str]) -> bool:
    """
    Match theo word/subword có kiểm soát, tránh lỗi kiểu:
    returns -> return_equity
    flow -> low
    """
    text = text.lower()
    tokens = set(re.split(r"[^a-zA-Z0-9_]+", text))

    for w in words:
        w = w.lower()
        if w in tokens:
            return True
        if f"_{w}" in text or f"{w}_" in text:
            return True

    return False


def contains_any(text: str, words: list[str]) -> bool:
    text = text.lower()
    return any(w.lower() in text for w in words)


def classify_field(field_name: str, description: str, category: str | None, field_type: str) -> dict:
    name = (field_name or "").lower()
    desc = (description or "").lower()
    cat = (category or "").lower()
    text = f"{name} {desc}"

    # 1. Group/Symbol không dùng làm core signal
    if field_type == "Group":
        return {
            "field_role": "group_control",
            "economic_theme": "grouping",
            "alpha_family": "neutralization_control",
            "expected_turnover": "low",
            "missing_risk": "low",
            "recommended_operators": "group_rank,group_neutralize,group_zscore,group_backfill",
            "notes": "Use as grouping/control, not core signal."
        }

    if field_type == "Symbol":
        return {
            "field_role": "identifier",
            "economic_theme": "identifier",
            "alpha_family": "not_used_for_signal",
            "expected_turnover": "low",
            "missing_risk": "low",
            "recommended_operators": "",
            "notes": "Identifier; avoid as alpha signal."
        }

    if field_type == "Vector":
        return {
            "field_role": "vector_signal",
            "economic_theme": "vector_event_or_aggregate",
            "alpha_family": "vector_signal",
            "expected_turnover": "medium",
            "missing_risk": "medium",
            "recommended_operators": "vec_avg,vec_sum,ts_rank,rank,group_neutralize",
            "notes": "Vector field; summarize first with vec_avg or vec_sum."
        }

    # 2. Price Volume exact fields
    price_fields = {"open", "high", "low", "close", "vwap"}
    if name in price_fields:
        return {
            "field_role": "price_signal",
            "economic_theme": "price_action",
            "alpha_family": "reversal,momentum,intraday_pressure",
            "expected_turnover": "high",
            "missing_risk": "low",
            "recommended_operators": "rank,ts_delta,ts_rank,ts_mean,ts_corr,ts_decay_linear",
            "notes": "Use mainly for timing/filter; high turnover if core signal."
        }

    if name == "returns":
        return {
            "field_role": "price_signal",
            "economic_theme": "returns",
            "alpha_family": "reversal,momentum,volatility",
            "expected_turnover": "high",
            "missing_risk": "low",
            "recommended_operators": "rank,ts_sum,ts_mean,ts_std_dev,ts_zscore,ts_rank",
            "notes": "Do not classify as profitability. This is daily return."
        }

    if name in {"volume", "adv20"}:
        return {
            "field_role": "liquidity_filter",
            "economic_theme": "liquidity_volume",
            "alpha_family": "volume_filter,liquidity_shock",
            "expected_turnover": "high",
            "missing_risk": "low",
            "recommended_operators": "divide,ts_rank,ts_mean,trade_when,rank",
            "notes": "Best used as filter/confirmation, not core signal."
        }

    if name in {"cap", "sharesout"} or "market capitalization" in desc:
        return {
            "field_role": "scale_or_control",
            "economic_theme": "size",
            "alpha_family": "size_control,valuation_scaling",
            "expected_turnover": "medium",
            "missing_risk": "low",
            "recommended_operators": "rank,bucket,densify,group_neutralize,divide",
            "notes": "Use to scale fundamental fields or create size buckets."
        }

    # 3. Model fields
    if cat == "model" or "model" in name or "factor" in name or "score" in name or "rank" in name:
        if contains_any(text, ["risk", "beta", "volatility", "variance", "residual", "idiosyncratic"]):
            return {
                "field_role": "risk_signal",
                "economic_theme": "risk_model",
                "alpha_family": "risk_control,risk_premium",
                "expected_turnover": "medium",
                "missing_risk": "low",
                "recommended_operators": "rank,ts_rank,group_rank,group_neutralize",
                "notes": "Model risk metric; can be used as risk premium or control."
            }

        if contains_any(text, ["analyst", "revision", "estimate", "earnings", "momentum", "growth", "value", "quality"]):
            return {
                "field_role": "model_signal",
                "economic_theme": "model_alpha_signal",
                "alpha_family": "model_signal,analyst_revision,earnings_momentum",
                "expected_turnover": "medium",
                "missing_risk": "medium",
                "recommended_operators": "rank,ts_rank,ts_delta,group_rank,group_neutralize,trade_when",
                "notes": "Model-derived signal; prioritize as core signal."
            }

        return {
            "field_role": "model_signal",
            "economic_theme": "model_alpha_signal",
            "alpha_family": "model_signal",
            "expected_turnover": "medium",
            "missing_risk": "medium",
            "recommended_operators": "rank,ts_rank,group_rank,group_neutralize",
            "notes": "Generic model-derived signal."
        }

    # 4. Fundamental themes
    if has_any(text, ["sales", "revenue", "turnover"]):
        return {
            "field_role": "fundamental_signal",
            "economic_theme": "growth",
            "alpha_family": "growth,sales_momentum",
            "expected_turnover": "low",
            "missing_risk": "medium",
            "recommended_operators": "ts_backfill,group_backfill,ts_rank,ts_delta,group_rank,winsorize",
            "notes": "Fundamental growth/sales field."
        }

    if has_any(text, ["income", "profit", "margin", "earnings", "eps", "ebit", "ebitda", "roe", "roa"]):
        return {
            "field_role": "fundamental_signal",
            "economic_theme": "quality_profitability",
            "alpha_family": "quality,profitability,earnings",
            "expected_turnover": "low",
            "missing_risk": "medium",
            "recommended_operators": "ts_backfill,group_backfill,winsorize,ts_rank,group_rank,group_zscore",
            "notes": "Fundamental quality/profitability field."
        }

    if has_any(text, ["debt", "liabilities", "liability", "leverage"]):
        return {
            "field_role": "fundamental_signal",
            "economic_theme": "leverage_balance_sheet",
            "alpha_family": "leverage,financial_risk",
            "expected_turnover": "low",
            "missing_risk": "medium",
            "recommended_operators": "ts_backfill,group_backfill,winsorize,group_zscore,group_rank",
            "notes": "Usually lower leverage is better; often use reverse/negative."
        }

    if has_any(text, ["assets", "equity", "book", "cashflow", "cash", "capital", "capex"]):
        return {
            "field_role": "fundamental_signal",
            "economic_theme": "balance_sheet_cashflow",
            "alpha_family": "value,quality,cashflow",
            "expected_turnover": "low",
            "missing_risk": "medium",
            "recommended_operators": "ts_backfill,group_backfill,winsorize,divide,ts_rank,group_rank",
            "notes": "Use as denominator or core value/quality signal."
        }

    # 5. Relationship data
    if name.startswith("rel_") or contains_any(text, ["competitor", "customer", "supplier", "partner", "overlapped"]):
        return {
            "field_role": "relationship_signal",
            "economic_theme": "relationship_network",
            "alpha_family": "supply_chain,peer_relation,customer_supplier",
            "expected_turnover": "medium",
            "missing_risk": "medium",
            "recommended_operators": "rank,ts_rank,group_rank,group_neutralize,ts_mean",
            "notes": "Relationship/peer network signal."
        }

    return {
        "field_role": "unknown",
        "economic_theme": "unknown",
        "alpha_family": "unknown",
        "expected_turnover": "medium",
        "missing_risk": "medium",
        "recommended_operators": "",
        "notes": ""
    }