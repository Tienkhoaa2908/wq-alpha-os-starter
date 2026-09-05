from __future__ import annotations

"""Canonical economic-theme taxonomy shared by the v2 research pipeline."""


ECONOMIC_THEMES = frozenset({
    "value",
    "profitability",
    "quality",
    "analyst_revision",
    "earnings_surprise",
    "growth",
    "leverage",
    "risk_volatility",
    "options",
    "sentiment_news",
    "short_interest",
    "insider",
    "relationship",
    "price",
    "volume_liquidity",
    "model_score",
    "generic",
})


THEME_ALIASES = {
    "value_cashflow": "value",
    "profitability_quality": "profitability",
    "earnings_dispersion": "earnings_surprise",
    "risk": "risk_volatility",
    "price_volume": "price",
    "sentiment": "sentiment_news",
}


def normalize_theme(value: object) -> str:
    name = str(value or "").strip().lower()
    name = THEME_ALIASES.get(name, name)
    return name if name in ECONOMIC_THEMES else "generic"


__all__ = ["ECONOMIC_THEMES", "THEME_ALIASES", "normalize_theme"]
