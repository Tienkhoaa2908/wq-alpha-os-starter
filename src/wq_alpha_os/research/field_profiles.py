from __future__ import annotations

"""Deterministic semantic profiler for BRAIN data fields.

The first pass must be cheap, reproducible and local.  LLM classification is
reserved for ambiguous/high-value fields later; this module produces the
stable priors that constrain operator/path search.
"""

from dataclasses import asdict, dataclass
import json
import re
import sqlite3
from typing import Any, Iterable

from ..db import json_dumps, utc_now
from .taxonomy import normalize_theme


@dataclass(frozen=True)
class FieldProfile:
    field_key: str
    name: str
    dataset_name: str
    data_type: str
    economic_theme: str
    secondary_themes: tuple[str, ...]
    semantic_form: str
    update_cadence: str
    signedness: str
    unit_family: str
    sparsity_class: str
    peer_dependence: str
    direction_prior: str
    direction_confidence: str
    horizon_prior: tuple[int, ...]
    preferred_roles: tuple[str, ...]
    discouraged_roles: tuple[str, ...]
    classification_source: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key, item in tuple(value.items()):
            if isinstance(item, tuple):
                value[key] = list(item)
        return value


THEME_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sentiment_news", ("sentiment", "news", "headline", "social", "buzz", "ravenpack", "novelty")),
    ("options", ("option", "implied volatility", "put call", "put/call", "pcr", "skew")),
    ("earnings_surprise", ("earnings surprise", "unexpected earnings", "surprise", "estimate dispersion")),
    ("analyst_revision", ("estimate revision", "earnings revision", "analyst revision", "recommendation", "target price", "consensus estimate", "forecast revision")),
    ("volume_liquidity", ("volume", "turnover", "liquidity", "illiquidity", "liquidityriskfactor", "vwap", "bid ask spread", "trading activity")),
    ("risk_volatility", ("volatility", "stddev", "standard deviation", "variance", "beta", "drawdown", "idiosyncratic risk", "liquidity risk", "true range", "atr")),
    ("price", ("price momentum", "opricemomentumfactor", "momentum", "price change", "open close", "close open", "stock return", "market return", "benchmark performance")),
    ("value", ("valuation", "value factor", "cash flow to price", "cash flow yield", "cashflow yield", "cfp", "book to price", "earnings yield", "price to earnings", "price earnings", "pe ratio")),
    ("profitability", ("profit", "margin", "roa", "roe", "return on asset", "return on equity")),
    ("quality", ("quality", "accrual", "balance sheet", "earnings quality")),
    ("growth", ("growth", "cagr", "year over year", "yoy change")),
    ("leverage", ("leverage", "net debt", "debt ratio", "liability", "interest coverage")),
    ("short_interest", ("short interest", "short ratio", "days to cover")),
    ("insider", ("insider", "director", "officer transaction")),
    ("relationship", ("relationship", "supplier", "customer", "network", "peer link")),
    ("model_score", ("model score", "factor score", "composite score", "signal score")),
)

FORM_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ratio", ("ratio", "yield", "margin", "per share", "to price", "price to", "cfp", "roe", "roa")),
    ("count", ("count", "number of", "num ", "frequency", "buzz")),
    ("forecast", ("forecast", "estimate", "consensus", "target price", "expected")),
    ("dispersion", ("dispersion", "std", "stddev", "standard deviation", "variance", "uncertainty")),
    ("probability", ("probability", "likelihood", "chance")),
    ("flow", ("flow", "cash flow", "cashflow", "inflow", "outflow")),
    ("return", ("return", "returns", "change", "delta", "momentum", "opricemomentumfactor", "performance")),
    ("volume", ("volume", "shares traded", "turnover")),
    ("price", ("price", "close", "open", "high", "low", "vwap")),
    ("event", ("event", "announcement", "filing", "transaction", "news")),
    ("score", ("score", "factor", "signal", "sentiment")),
)

HORIZONS: dict[str, tuple[int, ...]] = {
    "event": (5, 20, 63),
    "fast": (5, 20, 63),
    "medium": (20, 63, 126),
    "slow": (126, 252, 504, 756),
}


def _text(*parts: object) -> str:
    raw = " ".join(str(part or "") for part in parts).lower().replace("_", " ")
    return " ".join(re.findall(r"[a-z0-9]+", raw))


def _has_phrase(text: str, phrase: str) -> bool:
    normalized = _text(phrase)
    return bool(normalized and re.search(rf"(?:^| )({re.escape(normalized)})(?: |$)", text))


def _hits(text: str, needles: tuple[str, ...]) -> bool:
    return any(_has_phrase(text, needle) for needle in needles)


def _theme_hits(text: str) -> list[str]:
    hits: list[str] = []
    for theme, needles in THEME_KEYWORDS:
        if _hits(text, needles):
            hits.append(theme)
    return hits


def _theme(name_text: str, description_text: str, existing: str) -> tuple[str, tuple[str, ...], float]:
    name_hits = _theme_hits(name_text)
    description_hits = [item for item in _theme_hits(description_text) if item not in name_hits]
    hits = name_hits + description_hits
    if hits:
        base = 0.90 if name_hits else 0.82
        return hits[0], tuple(hits[1:3]), min(0.96, base + 0.03 * (len(hits) - 1))
    legacy = normalize_theme(existing)
    if legacy != "generic":
        return legacy, (), 0.52
    return "generic", (), 0.35


def _dataset_fallback(dataset_name: str) -> str:
    text = _text(dataset_name)
    priors = (
        ("options", ("options analytics",)),
        ("risk_volatility", ("volatility data", "systematic risk")),
        ("sentiment_news", ("news data", "ravenpack", "sentiment data", "social media")),
        ("relationship", ("relationship data",)),
        ("price", ("price volume data",)),
        ("analyst_revision", ("analyst estimate data",)),
        ("model_score", ("analysts factor model", "fundamental scores")),
    )
    return next((theme for theme, names in priors if _hits(text, names)), "generic")


def _form(name_text: str, description_text: str, data_type: str) -> str:
    if data_type == "VECTOR":
        if _hits(name_text, ("change", "delta", "return", "momentum", "performance")):
            return "vector_event"
        if _hits(name_text, ("count", "volume", "buzz", "number")):
            return "vector_count"
        if _hits(name_text, ("sentiment", "score", "probability")):
            return "vector_score"
        if _hits(description_text, ("count", "volume", "buzz", "number")):
            return "vector_count"
        if _hits(description_text, ("sentiment", "score", "probability")):
            return "vector_score"
        return "vector_event"
    for text in (name_text, description_text):
        for form, needles in FORM_KEYWORDS:
            if _hits(text, needles):
                return form
    return "level"


def _cadence(theme: str, form: str) -> str:
    if form in {"event", "vector_count", "vector_score", "vector_event"} or theme in {"sentiment_news", "insider", "relationship"}:
        return "event"
    if theme in {"price", "volume_liquidity", "risk_volatility", "options"}:
        return "fast"
    if theme in {"analyst_revision", "earnings_surprise", "short_interest"} or form in {"forecast", "dispersion"}:
        return "medium"
    return "slow"


def _direction(text: str) -> tuple[str, str]:
    if _hits(text, ("earnings yield", "cash flow yield", "return on assets", "return on equity", "profit margin")):
        return "positive", "medium"
    if _hits(text, ("price to earnings", "price earnings", "pe ratio", "leverage", "debt ratio", "volatility", "drawdown", "idiosyncratic risk")):
        return "negative", "medium"
    return "ambiguous", "low"


def _unit_family(theme: str, form: str) -> str:
    if form in {"ratio", "probability", "score", "vector_score"}:
        return "dimensionless_or_ratio"
    if form == "price":
        return "currency_price"
    if form == "return":
        return "return"
    if form in {"count", "vector_count"}:
        return "count"
    if form == "volume":
        return "volume"
    if form == "flow":
        return "currency_flow"
    if theme == "risk_volatility":
        return "risk_measure"
    return "unknown"


def _roles(theme: str, form: str, cadence: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    preferred: list[str] = []
    discouraged: list[str] = []
    if form.startswith("vector_"):
        preferred.append("vector_reduce")
    if cadence == "slow":
        preferred.extend(("historical_position_ordinal", "historical_anomaly_standardized", "peer_ordinal"))
        discouraged.extend(("very_short_change", "event_gate"))
    elif cadence == "event":
        preferred.extend(("rolling_accumulation", "recency_weighted_smoothing", "historical_anomaly_standardized"))
        discouraged.append("very_slow_position")
    elif cadence == "fast":
        preferred.extend(("absolute_change", "local_mean_deviation", "rolling_dispersion", "peer_ordinal"))
    else:
        preferred.extend(("absolute_change", "previous_distinct_value", "peer_ordinal"))
    if theme == "analyst_revision":
        preferred.extend(("previous_distinct_value", "absolute_change"))
    if theme == "risk_volatility":
        preferred.extend(("rolling_dispersion", "rolling_correlation"))
    if form in {"count", "flow", "volume", "vector_count"}:
        preferred.append("rolling_accumulation")
    return tuple(dict.fromkeys(preferred)), tuple(dict.fromkeys(discouraged))


def profile_row(row: sqlite3.Row | dict[str, Any]) -> FieldProfile:
    keys = set(row.keys())
    get = lambda key, default=None: row[key] if key in keys else default
    name = str(get("name", ""))
    description = str(get("description", "") or "")
    dataset_name = str(get("dataset_name", "") or "")
    data_type = str(get("data_type", "MATRIX") or "MATRIX").upper()
    name_text = _text(name)
    description_text = _text(description)
    text = _text(name, description)
    theme, secondary, confidence = _theme(name_text, description_text, str(get("semantic_theme", "") or ""))
    if theme == "generic":
        fallback = _dataset_fallback(dataset_name)
        if fallback != "generic":
            theme, confidence = fallback, 0.5
    form = _form(name_text, description_text, data_type)
    cadence = _cadence(theme, form)
    direction, direction_confidence = _direction(text)
    signed_markers = (
        "change", "delta", "return", "revision", "growth", "momentum", "opricemomentumfactor", "surprise", "spread",
    )
    nonnegative_markers = ("count", "volume", "market cap", "assets", "sales", "price")
    if _hits(text, signed_markers):
        signedness = "signed"
    elif _hits(text, nonnegative_markers):
        signedness = "nonnegative"
    else:
        signedness = "unknown"
    sparsity = "event_sparse" if cadence == "event" else ("slow_stepwise" if cadence == "slow" else "dense")
    peer_dependence = "high" if theme in {"value", "profitability", "quality", "growth", "leverage", "analyst_revision"} else "medium"
    preferred, discouraged = _roles(theme, form, cadence)
    return FieldProfile(
        field_key=str(get("field_key", name)),
        name=name,
        dataset_name=dataset_name,
        data_type=data_type,
        economic_theme=theme,
        secondary_themes=secondary,
        semantic_form=form,
        update_cadence=cadence,
        signedness=signedness,
        unit_family=_unit_family(theme, form),
        sparsity_class=sparsity,
        peer_dependence=peer_dependence,
        direction_prior=direction,
        direction_confidence=direction_confidence,
        horizon_prior=HORIZONS[cadence],
        preferred_roles=preferred,
        discouraged_roles=discouraged,
        classification_source="deterministic_v3",
        confidence=round(confidence, 3),
    )


def profile_for_name(connection: sqlite3.Connection, name: str) -> FieldProfile | None:
    row = connection.execute(
        "SELECT * FROM fields WHERE lower(name)=lower(?) ORDER BY updated_at DESC LIMIT 1", (name,)
    ).fetchone()
    return profile_row(row) if row is not None else None


def materialize_field_profiles(connection: sqlite3.Connection, *, only_missing: bool = False) -> dict[str, int]:
    rows = connection.execute("SELECT * FROM fields ORDER BY name").fetchall()
    inserted = skipped = 0
    for row in rows:
        profile = profile_row(row)
        if only_missing and connection.execute("SELECT 1 FROM field_profiles WHERE field_key=?", (profile.field_key,)).fetchone():
            skipped += 1
            continue
        connection.execute(
            """INSERT INTO field_profiles(
                field_key,name,dataset_name,data_type,economic_theme,secondary_themes_json,semantic_form,
                update_cadence,signedness,unit_family,sparsity_class,peer_dependence,direction_prior,
                direction_confidence,horizon_prior_json,preferred_roles_json,discouraged_roles_json,
                classification_source,confidence,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(field_key) DO UPDATE SET
                name=excluded.name,dataset_name=excluded.dataset_name,data_type=excluded.data_type,
                economic_theme=excluded.economic_theme,secondary_themes_json=excluded.secondary_themes_json,
                semantic_form=excluded.semantic_form,update_cadence=excluded.update_cadence,
                signedness=excluded.signedness,unit_family=excluded.unit_family,
                sparsity_class=excluded.sparsity_class,peer_dependence=excluded.peer_dependence,
                direction_prior=excluded.direction_prior,direction_confidence=excluded.direction_confidence,
                horizon_prior_json=excluded.horizon_prior_json,preferred_roles_json=excluded.preferred_roles_json,
                discouraged_roles_json=excluded.discouraged_roles_json,
                classification_source=excluded.classification_source,confidence=excluded.confidence,updated_at=excluded.updated_at""",
            (
                profile.field_key, profile.name, profile.dataset_name, profile.data_type, profile.economic_theme,
                json_dumps(profile.secondary_themes), profile.semantic_form, profile.update_cadence, profile.signedness,
                profile.unit_family, profile.sparsity_class, profile.peer_dependence, profile.direction_prior,
                profile.direction_confidence, json_dumps(profile.horizon_prior), json_dumps(profile.preferred_roles),
                json_dumps(profile.discouraged_roles), profile.classification_source, profile.confidence, utc_now(),
            ),
        )
        inserted += 1
    return {"profiled": inserted, "skipped": skipped, "total_fields": len(rows)}


def stored_profile(connection: sqlite3.Connection, name: str) -> FieldProfile | None:
    row = connection.execute(
        "SELECT * FROM field_profiles WHERE lower(name)=lower(?) ORDER BY updated_at DESC LIMIT 1", (name,)
    ).fetchone()
    if row is None:
        return profile_for_name(connection, name)
    return FieldProfile(
        field_key=row["field_key"], name=row["name"], dataset_name=row["dataset_name"] or "",
        data_type=row["data_type"], economic_theme=row["economic_theme"],
        secondary_themes=tuple(json.loads(row["secondary_themes_json"] or "[]")), semantic_form=row["semantic_form"],
        update_cadence=row["update_cadence"], signedness=row["signedness"], unit_family=row["unit_family"],
        sparsity_class=row["sparsity_class"], peer_dependence=row["peer_dependence"],
        direction_prior=row["direction_prior"], direction_confidence=row["direction_confidence"],
        horizon_prior=tuple(int(x) for x in json.loads(row["horizon_prior_json"] or "[]")),
        preferred_roles=tuple(json.loads(row["preferred_roles_json"] or "[]")),
        discouraged_roles=tuple(json.loads(row["discouraged_roles_json"] or "[]")),
        classification_source=row["classification_source"], confidence=float(row["confidence"] or 0),
    )


def compact_payload(profiles: Iterable[FieldProfile]) -> list[dict[str, Any]]:
    return [
        {
            "name": p.name,
            "data_type": p.data_type,
            "theme": p.economic_theme,
            "form": p.semantic_form,
            "cadence": p.update_cadence,
            "direction_prior": p.direction_prior,
            "horizon_prior": list(p.horizon_prior),
            "preferred_roles": list(p.preferred_roles),
            "confidence": p.confidence,
        }
        for p in profiles
    ]


__all__ = [
    "FieldProfile",
    "HORIZONS",
    "compact_payload",
    "materialize_field_profiles",
    "profile_for_name",
    "profile_row",
    "stored_profile",
]
