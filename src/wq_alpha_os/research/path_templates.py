from __future__ import annotations

"""Canonical research paths for deterministic alpha compilation.

A path template is a research motif, not a finished alpha.  It constrains the
sequence of roles and the field semantics that make the path meaningful.
"""

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .field_profiles import FieldProfile


@dataclass(frozen=True)
class PathTemplate:
    id: str
    label: str
    purpose: str
    input_kinds: tuple[str, ...]
    preferred_themes: tuple[str, ...]
    preferred_forms: tuple[str, ...]
    ordered_roles: tuple[str, ...]
    min_fields: int
    max_fields: int
    novelty_class: str
    enabled_by_default: bool
    hard_rules: tuple[str, ...]
    diagnostic_failure_modes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key, item in tuple(value.items()):
            if isinstance(item, tuple):
                value[key] = list(item)
        return value


PATH_TEMPLATES: tuple[PathTemplate, ...] = (
    PathTemplate(
        "slow_level_peer", "Slow level relative to peers",
        "Convert a slow level/ratio into historical position, then compare inside a peer group.",
        ("MATRIX",), ("value", "profitability", "quality", "growth", "leverage", "model_score"),
        ("level", "ratio", "score", "flow"),
        ("field", "repair?", "historical_position", "peer_control", "direction?", "turnover?", "output"),
        1, 1, "core", True,
        ("Use slow/very-slow horizons; do not add a second field until the single-field diagnostic is understood.",),
        ("low_fitness", "high_self_correlation"),
    ),
    PathTemplate(
        "slow_change_peer", "Cadence-aware change relative to peers",
        "Measure a real update/change before peer comparison.",
        ("MATRIX",), ("analyst_revision", "earnings_surprise", "growth", "profitability", "quality"),
        ("forecast", "level", "flow", "score"),
        ("field", "change", "smoothing?", "peer_control", "direction?", "output"),
        1, 1, "core", True,
        ("Change window must respect update cadence; prefer previous-distinct-value logic for stepwise fields when needed.",),
        ("flat_signal", "negative_sharpe", "high_turnover"),
    ),
    PathTemplate(
        "relative_ratio", "Economically comparable spread or ratio",
        "Create a spread/ratio from two comparable quantities before temporal and peer transforms.",
        ("MATRIX",), ("value", "profitability", "quality", "growth", "options", "volume_liquidity"),
        ("ratio", "level", "flow", "forecast", "price", "volume"),
        ("field_a", "field_b", "relative_arithmetic", "time_normalize?", "peer_control", "output"),
        2, 2, "cross_field", True,
        ("The two fields must have compatible units or explicit ratio semantics; denominator near-zero policy is mandatory for divide.",),
        ("validation_failed", "tail_instability"),
    ),
    PathTemplate(
        "vector_event_intensity", "Vector event intensity",
        "Reduce vector events into activity/intensity, accumulate or decay, then compare peers.",
        ("VECTOR",), ("sentiment_news", "insider", "relationship"),
        ("vector_count", "vector_event", "vector_score"),
        ("vector_field", "vector_reduce", "repair?", "accumulation_or_decay", "peer_control", "output"),
        1, 1, "event", True,
        ("VECTOR must be reduced before any MATRIX operator; vec_sum and vec_avg are chosen by field meaning, not randomly.",),
        ("flat_signal", "high_turnover", "low_coverage"),
    ),
    PathTemplate(
        "vector_event_novelty", "Vector event novelty",
        "Reduce vector events and measure novelty versus the field's own recent history.",
        ("VECTOR",), ("sentiment_news", "insider", "relationship"),
        ("vector_count", "vector_event", "vector_score"),
        ("vector_field", "vector_reduce", "repair?", "historical_anomaly", "peer_control", "output"),
        1, 1, "event", True,
        ("Use short/event horizons; do not backfill so far that old news becomes a current signal.",),
        ("high_turnover", "annual_instability"),
    ),
    PathTemplate(
        "extremum_recency", "Recency of an extreme",
        "Use time since a local maximum/minimum rather than magnitude of the extreme.",
        ("MATRIX",), ("price", "volume_liquidity", "sentiment_news", "risk_volatility"),
        ("price", "volume", "score", "level"),
        ("field", "extremum_recency", "peer_control", "direction", "output"),
        1, 1, "timing", True,
        ("The hypothesis must specify maximum versus minimum and the economic sign.",),
        ("negative_sharpe", "low_fitness"),
    ),
    PathTemplate(
        "information_staleness", "Information staleness",
        "Measure how long a slow/event field has remained unchanged and compare that freshness across peers.",
        ("MATRIX",), ("analyst_revision", "profitability", "quality", "growth", "insider", "relationship"),
        ("forecast", "level", "event", "score"),
        ("field", "staleness", "peer_control", "direction", "output"),
        1, 1, "timing", True,
        ("Only use on fields whose unchanged state reflects update cadence rather than continuously varying market data.",),
        ("flat_signal", "negative_sharpe"),
    ),
    PathTemplate(
        "two_series_correlation", "Rolling relation between two series",
        "Measure co-movement between two economically related fields.",
        ("MATRIX",), ("price", "volume_liquidity", "risk_volatility", "options", "relationship"),
        ("price", "return", "volume", "ratio", "score", "level"),
        ("field_x", "field_y", "rolling_relation", "peer_control?", "direction?", "output"),
        2, 2, "relation", True,
        ("Two fields require an explicit relational mechanism; random pair search is forbidden.",),
        ("low_fitness", "high_self_correlation"),
    ),
    PathTemplate(
        "regression_residual", "Rolling regression residual",
        "Remove an explanatory relation and trade the residual component.",
        ("MATRIX",), ("price", "risk_volatility", "options", "relationship"),
        ("return", "price", "score", "ratio"),
        ("dependent", "explanatory", "regression", "peer_control?", "output"),
        2, 2, "relation", False,
        ("Disabled by default until rettype semantics are explicitly verified from the active BRAIN definition.",),
        ("validation_failed", "semantic_uncertainty"),
    ),
    PathTemplate(
        "risk_dispersion", "Rolling risk/dispersion",
        "Turn a return/risk series into a dispersion feature, then place it historically and across peers.",
        ("MATRIX",), ("risk_volatility", "price", "options", "analyst_revision"),
        ("return", "price", "dispersion", "forecast"),
        ("field", "rolling_dispersion", "historical_position?", "peer_control", "direction", "output"),
        1, 1, "risk", True,
        ("Direction is a hypothesis; low-risk and risk-premium stories imply different signs.",),
        ("negative_sharpe", "annual_instability"),
    ),
    PathTemplate(
        "peer_residual", "Peer residual",
        "Remove a peer-group component before optional historical normalization.",
        ("MATRIX",), ("value", "profitability", "quality", "growth", "leverage", "analyst_revision"),
        ("level", "ratio", "forecast", "score", "flow"),
        ("field", "peer_residualize", "historical_position?", "direction?", "output"),
        1, 1, "peer", True,
        ("Use group_neutralize OR an explicit group_mean residual construction, not both in the same path.",),
        ("high_self_correlation", "sector_concentration"),
    ),
    PathTemplate(
        "state_gated_core", "Independent state-gated core",
        "Gate a previously promising core alpha using an independent regime/event condition.",
        ("MATRIX",), (), (),
        ("independent_condition", "proven_core", "trade_when", "output?"),
        2, 3, "control", False,
        ("Disabled for blind generation; the core must already have evidence and the condition must use an independent information source.",),
        ("high_turnover", "regime_instability"),
    ),
    PathTemplate(
        "multi_horizon_consensus", "Multi-horizon consensus",
        "Combine the same mechanism at two horizon buckets to test robustness, not novelty.",
        ("MATRIX",), ("value", "profitability", "quality", "model_score", "analyst_revision"),
        ("level", "ratio", "score", "forecast"),
        ("field", "same_mechanism_two_horizons", "peer_control", "weighted_combine", "output"),
        1, 1, "robustness", True,
        ("This path is tagged robustness/sensitivity; it must never count as semantic novelty.",),
        ("low_fitness", "robustness_check"),
    ),
    PathTemplate(
        "orthogonal_confirmation", "Orthogonal confirmation",
        "Combine two independently interpretable mechanisms after each branch is normalized/peer-controlled.",
        ("MATRIX",), (), (),
        ("branch_a", "branch_b", "branch_normalize", "weighted_combine", "output"),
        2, 2, "diversity", True,
        ("Branches should differ in economic theme or mechanism; same-field window changes belong to multi_horizon_consensus instead.",),
        ("high_self_correlation", "near_threshold_fitness"),
    ),
)

TEMPLATE_BY_ID = {item.id: item for item in PATH_TEMPLATES}


def _matches(profile: FieldProfile, template: PathTemplate) -> bool:
    if profile.data_type not in template.input_kinds:
        return False
    theme_ok = not template.preferred_themes or profile.economic_theme in template.preferred_themes
    form_ok = not template.preferred_forms or profile.semantic_form in template.preferred_forms
    return theme_ok and form_ok


def _pair_compatible(profiles: list[FieldProfile], template: PathTemplate) -> bool:
    if len(profiles) < 2:
        return True
    first, second = profiles[:2]
    if template.id == "relative_ratio":
        units_match = first.unit_family == second.unit_family and first.unit_family != "unknown"
        explicit_ratio = first.semantic_form == second.semantic_form == "ratio"
        return units_match or explicit_ratio
    if template.id in {"orthogonal_confirmation", "state_gated_core"}:
        return (
            first.economic_theme != second.economic_theme
            or first.semantic_form != second.semantic_form
        )
    return True


def eligible_templates(profiles: Iterable[FieldProfile], *, include_experimental: bool = False) -> list[PathTemplate]:
    items = list(profiles)
    if not items:
        return []
    result: list[PathTemplate] = []
    for template in PATH_TEMPLATES:
        if not template.enabled_by_default and not include_experimental:
            continue
        if not template.min_fields <= len(items) <= template.max_fields:
            continue
        if all(_matches(profile, template) for profile in items) and _pair_compatible(items, template):
            result.append(template)
    return result


def compact_payload(profiles: Iterable[FieldProfile], *, include_experimental: bool = False) -> list[dict[str, Any]]:
    return [
        {
            "id": template.id,
            "purpose": template.purpose,
            "ordered_roles": list(template.ordered_roles),
            "novelty_class": template.novelty_class,
            "hard_rules": list(template.hard_rules),
        }
        for template in eligible_templates(profiles, include_experimental=include_experimental)
    ]


__all__ = ["PATH_TEMPLATES", "TEMPLATE_BY_ID", "PathTemplate", "compact_payload", "eligible_templates"]
