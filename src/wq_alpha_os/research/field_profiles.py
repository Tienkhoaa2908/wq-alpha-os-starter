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
    ("value", ("value", "cash flow", "cashflow", "cfp", "book to", "earnings yield", "price to", "yield")),
    ("profitability", ("profit", "margin", "roa", "roe", "return on asset", "return on equity")),
    ("quality", ("quality", "accrual", "balance sheet", "earnings quality")),
    ("analyst_revision", ("revision", "analyst", "estimate", "recommendation", "target price", "consensus")),
    ("earnings_surprise", ("surprise", "unexpected earnings", "earnings surprise")),
    ("growth", ("growth", "cagr", "yoy", "year over year")),
    ("leverage", ("leverage", "debt", "liabilit", "interest coverage")),
    ("risk_volatility", ("volatility", "vol", "beta", "drawdown", "risk", "variance")),
    ("options", ("option", "implied volatility", "put call", "put/call", "skew")),
    ("sentiment_news", ("sentiment", "news", "headline", "social", "buzz", "ravenpack")),
    ("short_interest", ("short interest", "short ratio", "days to cover")),
    ("insider", ("insider", "director", "officer transaction")),
    ("relationship", ("relationship", "supplier", "customer", "network", "peer link")),
    ("price", ("close", "open", "high", "low", "price", "return")),
    ("volume_liquidity", ("volume", "turnover", "liquidity", "vwap", "spread")),
    ("model_score", ("model", "factor", "score", "signal")),
)

FORM_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ratio", ("ratio", "yield", "margin", "per share", "to price", "price to", "cfp", "roe", "roa")),
    ("count", ("count", "number of", "num ", "frequency", "buzz")),
    ("forecast", ("forecast", "estimate", "consensus", "target price", "expected")),
    ("dispersion", ("dispersion", "std", "standard deviation", "variance", "uncertainty")),
    ("probability", ("probability", "likelihood", "chance")),
    ("flow", ("flow", "cash flow", "cashflow", "inflow", "outflow")),
    ("return", ("return", "ret ", "returns")),
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
    return " ".join(str(part or "") for part in parts).lower().replace("_", " ")


def _theme(text: str, existing: str) -> tuple[str, tuple[str, ...], float]:
    hits: list[str] = []
    for theme, needles in THEME_KEYWORDS:
        if any(needle in text for needle in needles):
            hits.append(theme)
    normalized_existing = (existing or "").strip().lower()
    legacy_map = {
        "value_cashflow": "value",
        "profitability_quality": "profitability",
        "risk": "risk_volatility",
        "price_volume": "price",
        "sentiment": "sentiment_news",
    }
    if normalized_existing and normalized_existing not in {"generic", "unknown"}:
        mapped = legacy_map.get(normalized_existing, normalized_existing)
        if mapped not in hits:
            hits.insert(0, mapped)
    if not hits:
        return "generic", (), 0.35
    primary = hits[0]
    return primary, tuple(hits[1:3]), min(0.95, 0.62 + 0.08 * len(hits))


def _form(text: str, data_type: str) -> str:
    if data_type == "VECTOR":
        if any(token in text for token in ("count", "volume", "buzz", "number")):
            return "vector_count"
        if any(token in text for token in ("sentiment", "score", "probability")):
            return "vector_score"
        return "vector_event"
    for form, needles in FORM_KEYWORDS:
        if any(needle in text for needle in needles):
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


def _direction(existing: str, theme: str) -> tuple[str, str]:
    value = (existing or "").strip().lower()
    if value in {"reverse", "negative", "-1"}:
        return "negative", "medium"
    if value in {"positive", "+1"}:
        return "positive", "medium"
    if theme in {"value", "leverage", "short_interest"}:
        # Prior only; the system still allows one sign diagnostic.
        return "negative", "low"
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
    text = _text(name, description, dataset_name)
    theme, secondary, confidence = _theme(text, str(get("semantic_theme", "") or ""))
    form = _form(text, data_type)
    cadence = _cadence(theme, form)
    direction, direction_confidence = _direction(str(get("semantic_direction", "") or ""), theme)
    signedness = "nonnegative" if any(token in text for token in ("count", "volume", "market cap", "assets", "sales")) else "unknown"
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
        classification_source="deterministic_v2",
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
