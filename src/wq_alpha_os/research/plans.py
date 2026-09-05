from __future__ import annotations

"""High-level AlphaPlan schema and deterministic FASTEXPR compiler.

LLMs are allowed to choose a hypothesis/template and high-level intents.  They
are not allowed to author FASTEXPR strings.  This module resolves those intents
using field semantics and canonical parameter priors, then compiles the result
reproducibly.
"""

from dataclasses import asdict, dataclass, field
import json
import sqlite3
import uuid
from typing import Any

from ..db import json_dumps, utc_now
from .field_profiles import FieldProfile, stored_profile
from .path_templates import TEMPLATE_BY_ID, eligible_templates


HORIZON_BUCKETS: dict[str, tuple[int, ...]] = {
    "event": (5, 20),
    "short": (20, 42, 63),
    "medium": (63, 126),
    "long": (126, 252),
    "very_slow": (252, 504, 756),
}

ALLOWED_GROUPS = {"market", "sector", "industry", "subindustry", "country", "exchange", "currency"}


@dataclass(frozen=True)
class PlanRequest:
    template_id: str
    field_names: tuple[str, ...]
    horizon_bucket: str
    direction: str = "prior"
    group: str = "industry"
    relative_mode: str = "spread"
    extremum: str = "max"
    turnover_control: bool = False
    output_control: str = "standardize"
    branch_weights: tuple[float, float] | None = None
    rationale: str = ""
    manual: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PlanRequest":
        fields = tuple(str(item).strip() for item in value.get("field_names", []) if str(item).strip())
        raw_weights = value.get("branch_weights")
        weights: tuple[float, float] | None = None
        if isinstance(raw_weights, (list, tuple)) and len(raw_weights) == 2:
            try:
                weights = (float(raw_weights[0]), float(raw_weights[1]))
            except (TypeError, ValueError):
                weights = None
        return cls(
            template_id=str(value.get("template_id") or "").strip(),
            field_names=fields,
            horizon_bucket=str(value.get("horizon_bucket") or "medium").strip().lower(),
            direction=str(value.get("direction") or "prior").strip().lower(),
            group=str(value.get("group") or "industry").strip().lower(),
            relative_mode=str(value.get("relative_mode") or "spread").strip().lower(),
            extremum=str(value.get("extremum") or "max").strip().lower(),
            turnover_control=bool(value.get("turnover_control", False)),
            output_control=str(value.get("output_control") or "standardize").strip().lower(),
            branch_weights=weights,
            rationale=" ".join(str(value.get("rationale") or "").split()),
            manual=dict(value.get("manual") or {}) if isinstance(value.get("manual"), dict) else {},
        )


@dataclass(frozen=True)
class AlphaPlan:
    id: str
    family: str
    hypothesis_id: str | None
    card_id: str | None
    template_id: str
    field_names: tuple[str, ...]
    field_themes: tuple[str, ...]
    horizon_bucket: str
    windows: tuple[int, ...]
    direction: str
    group: str
    operators: dict[str, str]
    parameters: dict[str, Any]
    novelty_class: str
    rationale: str
    compiler_version: str = "alpha-plan-compiler-v2"

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["field_names"] = list(self.field_names)
        value["field_themes"] = list(self.field_themes)
        value["windows"] = list(self.windows)
        return value


class PlanError(ValueError):
    pass


def _window(profile: FieldProfile, bucket: str) -> int:
    if bucket not in HORIZON_BUCKETS:
        raise PlanError(f"Unknown horizon bucket: {bucket}")
    candidates = [value for value in HORIZON_BUCKETS[bucket] if value in profile.horizon_prior]
    if not candidates:
        # Pick the closest canonical value to the profile's own prior while
        # preserving the requested coarse horizon as much as possible.
        target = HORIZON_BUCKETS[bucket][len(HORIZON_BUCKETS[bucket]) // 2]
        candidates = list(profile.horizon_prior)
        if not candidates:
            candidates = list(HORIZON_BUCKETS[bucket])
        return min(candidates, key=lambda value: abs(value - target))
    return candidates[-1] if bucket in {"long", "very_slow"} else candidates[0]


def _two_windows(profile: FieldProfile, bucket: str) -> tuple[int, int]:
    pool = sorted(set(profile.horizon_prior))
    if len(pool) < 2:
        pool = sorted(set(pool) | set(HORIZON_BUCKETS.get(bucket, (63, 126))))
    target = HORIZON_BUCKETS.get(bucket, (63, 126))
    ranked = sorted(pool, key=lambda value: min(abs(value - item) for item in target))
    selected = sorted(set(ranked[:2]), reverse=True)
    if len(selected) < 2:
        raise PlanError("Need two distinct canonical windows for multi-horizon consensus")
    return selected[0], selected[1]


def _direction(profile: FieldProfile, requested: str) -> str:
    if requested in {"positive", "negative"}:
        return requested
    return profile.direction_prior if profile.direction_prior in {"positive", "negative"} else "positive"


def _peer_operator(profile: FieldProfile) -> str:
    # Rank is safer for high peer dependence and unknown/heavy-tailed units;
    # z-score keeps magnitude when the field already has a well-defined scale.
    return "group_rank" if profile.peer_dependence == "high" or profile.unit_family == "unknown" else "group_zscore"


def _branch_time_operator(profile: FieldProfile) -> str:
    if profile.update_cadence == "slow":
        return "ts_rank"
    if profile.economic_theme == "risk_volatility" or profile.semantic_form == "dispersion":
        return "ts_std_dev"
    if profile.update_cadence == "event":
        return "ts_zscore"
    return "ts_delta"


def _vector_reducer(profile: FieldProfile) -> str:
    return "vec_sum" if profile.semantic_form in {"vector_count", "vector_event"} else "vec_avg"


def resolve_request(
    connection: sqlite3.Connection,
    request: PlanRequest,
    *,
    family: str,
    hypothesis_id: str | None = None,
    card_id: str | None = None,
    include_experimental: bool = False,
) -> AlphaPlan:
    template = TEMPLATE_BY_ID.get(request.template_id)
    if template is None:
        raise PlanError(f"Unknown template: {request.template_id}")
    if not template.enabled_by_default and not include_experimental:
        raise PlanError(f"Template {template.id} is experimental/disabled by default")
    if request.group not in ALLOWED_GROUPS:
        raise PlanError(f"Invalid group: {request.group}")
    if not template.min_fields <= len(request.field_names) <= template.max_fields:
        raise PlanError(f"Template {template.id} requires {template.min_fields}..{template.max_fields} fields")
    profiles: list[FieldProfile] = []
    for name in request.field_names:
        profile = stored_profile(connection, name)
        if profile is None:
            raise PlanError(f"Field not found: {name}")
        profiles.append(profile)
    eligible = {item.id for item in eligible_templates(profiles, include_experimental=include_experimental)}
    if template.id not in eligible and template.id not in {"state_gated_core"}:
        raise PlanError(f"Template {template.id} is not semantically eligible for the selected fields")

    primary = profiles[0]
    windows: tuple[int, ...] = (_window(primary, request.horizon_bucket),)
    operators: dict[str, str] = {}
    parameters: dict[str, Any] = {
        "turnover_control": request.turnover_control,
        "output_control": request.output_control,
        "relative_mode": request.relative_mode,
        "extremum": request.extremum,
    }

    if template.id == "slow_level_peer":
        operators.update(time="ts_rank", peer=_peer_operator(primary), output="normalize")
    elif template.id == "slow_change_peer":
        operators.update(
            time="last_diff_change" if primary.semantic_form == "forecast" or primary.sparsity_class == "slow_stepwise" else "ts_delta",
            peer=_peer_operator(primary), output="normalize",
        )
    elif template.id == "relative_ratio":
        secondary = profiles[1]
        if request.relative_mode == "ratio":
            if secondary.signedness != "nonnegative":
                raise PlanError("Automatic divide is blocked because the denominator has no nonnegative-domain guarantee")
            operators["relative"] = "divide"
        else:
            if primary.unit_family != secondary.unit_family and "unknown" not in {primary.unit_family, secondary.unit_family}:
                raise PlanError("Spread requires compatible unit families")
            operators["relative"] = "subtract"
        operators.update(time="ts_rank", peer=_peer_operator(primary), output="normalize")
    elif template.id == "vector_event_intensity":
        operators.update(reduce=_vector_reducer(primary), time="ts_sum" if primary.semantic_form in {"vector_count", "vector_event"} else "ts_decay_linear", peer=_peer_operator(primary), output="normalize")
    elif template.id == "vector_event_novelty":
        operators.update(reduce=_vector_reducer(primary), time="ts_zscore", peer=_peer_operator(primary), output="normalize")
    elif template.id == "extremum_recency":
        if request.extremum not in {"max", "min"}:
            raise PlanError("extremum must be max or min")
        operators.update(time="ts_arg_max" if request.extremum == "max" else "ts_arg_min", peer=_peer_operator(primary), output="normalize")
    elif template.id == "information_staleness":
        operators.update(time="days_from_last_change", peer=_peer_operator(primary), output="normalize")
    elif template.id == "two_series_correlation":
        operators.update(relation="ts_corr", peer=_peer_operator(primary), output="normalize")
    elif template.id == "regression_residual":
        if "verified_rettype" not in request.manual:
            raise PlanError("ts_regression is blocked until verified_rettype is explicitly supplied")
        operators.update(relation="ts_regression", peer=_peer_operator(primary), output="normalize")
        parameters["verified_rettype"] = int(request.manual["verified_rettype"])
    elif template.id == "risk_dispersion":
        operators.update(time="ts_std_dev", historical="ts_rank", peer=_peer_operator(primary), output="normalize")
    elif template.id == "peer_residual":
        operators.update(peer="group_neutralize", historical="ts_rank", output="normalize")
    elif template.id == "state_gated_core":
        for required in ("condition_expression", "core_expression", "exit_expression"):
            if required not in request.manual:
                raise PlanError(f"state_gated_core requires manual.{required}")
        operators.update(gate="trade_when", output="normalize")
        parameters.update({key: str(request.manual[key]) for key in ("condition_expression", "core_expression", "exit_expression")})
    elif template.id == "multi_horizon_consensus":
        windows = _two_windows(primary, request.horizon_bucket)
        operators.update(time="ts_rank", peer=_peer_operator(primary), output="normalize")
        parameters["weights"] = request.branch_weights or (0.7, 0.3)
    elif template.id == "orthogonal_confirmation":
        secondary = profiles[1]
        operators.update(
            time_a=_branch_time_operator(primary), peer_a=_peer_operator(primary),
            time_b=_branch_time_operator(secondary), peer_b=_peer_operator(secondary), output="normalize",
        )
        parameters["weights"] = request.branch_weights or (0.5, 0.5)
        parameters["window_b"] = _window(secondary, request.horizon_bucket)
    else:
        raise PlanError(f"No resolver for template: {template.id}")

    weights = parameters.get("weights")
    if weights is not None:
        a, b = float(weights[0]), float(weights[1])
        if a <= 0 or b <= 0 or abs((a + b) - 1.0) > 1e-6:
            raise PlanError("Branch weights must be positive and sum to 1")
        parameters["weights"] = (round(a, 6), round(b, 6))

    return AlphaPlan(
        id=str(uuid.uuid4()), family=family, hypothesis_id=hypothesis_id, card_id=card_id,
        template_id=template.id, field_names=tuple(profile.name for profile in profiles),
        field_themes=tuple(profile.economic_theme for profile in profiles),
        horizon_bucket=request.horizon_bucket, windows=windows,
        direction=_direction(primary, request.direction), group=request.group,
        operators=operators, parameters=parameters, novelty_class=template.novelty_class,
        rationale=request.rationale,
    )


def _peer(expr: str, operator: str, group: str) -> str:
    if operator in {"group_rank", "group_zscore", "group_neutralize", "group_scale"}:
        return f"{operator}({expr}, {group})"
    if operator in {"rank", "zscore", "normalize", "scale"}:
        return f"{operator}({expr})"
    raise PlanError(f"Unsupported peer operator: {operator}")


def _direction_expr(expr: str, direction: str) -> str:
    return f"reverse({expr})" if direction == "negative" else expr


def _finish(expr: str, plan: AlphaPlan) -> str:
    if bool(plan.parameters.get("turnover_control")):
        expr = f"hump({expr}, hump=0.01)"
    if plan.parameters.get("output_control") == "none":
        return expr
    return f"normalize({expr}, useStd=true, limit=3)"


def _branch(field_name: str, profile: FieldProfile, operator: str, window: int, peer_operator: str, group: str, direction: str) -> str:
    if operator == "ts_rank":
        expr = f"ts_rank({field_name}, {window})"
    elif operator == "ts_zscore":
        expr = f"ts_zscore({field_name}, {window})"
    elif operator == "ts_delta":
        expr = f"ts_delta({field_name}, {window})"
    elif operator == "ts_std_dev":
        expr = f"ts_std_dev({field_name}, {window})"
    elif operator == "ts_decay_linear":
        expr = f"ts_decay_linear({field_name}, {window})"
    else:
        raise PlanError(f"Unsupported branch time operator: {operator}")
    return _direction_expr(_peer(expr, peer_operator, group), direction)


def compile_plan(connection: sqlite3.Connection, plan: AlphaPlan) -> str:
    profiles = [stored_profile(connection, name) for name in plan.field_names]
    if any(profile is None for profile in profiles):
        raise PlanError("A plan references a field that no longer exists")
    typed_profiles = [profile for profile in profiles if profile is not None]
    field_a = plan.field_names[0]
    window = plan.windows[0]
    template = plan.template_id

    if template == "slow_level_peer":
        expr = _peer(f"ts_rank({field_a}, {window})", plan.operators["peer"], plan.group)
        return _finish(_direction_expr(expr, plan.direction), plan)
    if template == "slow_change_peer":
        if plan.operators["time"] == "last_diff_change":
            expr = f"subtract({field_a}, last_diff_value({field_a}, {window}))"
        else:
            expr = f"ts_delta({field_a}, {window})"
        expr = _peer(expr, plan.operators["peer"], plan.group)
        return _finish(_direction_expr(expr, plan.direction), plan)
    if template == "relative_ratio":
        field_b = plan.field_names[1]
        if plan.operators["relative"] == "divide":
            relative = f"divide({field_a}, add({field_b}, 0.0001))"
        else:
            relative = f"subtract({field_a}, {field_b})"
        expr = f"ts_rank({relative}, {window})"
        expr = _peer(expr, plan.operators["peer"], plan.group)
        return _finish(_direction_expr(expr, plan.direction), plan)
    if template in {"vector_event_intensity", "vector_event_novelty"}:
        base = f"{plan.operators['reduce']}({field_a})"
        time_op = plan.operators["time"]
        expr = f"{time_op}({base}, {window})"
        expr = _peer(expr, plan.operators["peer"], plan.group)
        return _finish(_direction_expr(expr, plan.direction), plan)
    if template == "extremum_recency":
        expr = f"{plan.operators['time']}({field_a}, {window})"
        expr = _peer(expr, plan.operators["peer"], plan.group)
        return _finish(_direction_expr(expr, plan.direction), plan)
    if template == "information_staleness":
        expr = f"days_from_last_change({field_a})"
        expr = _peer(expr, plan.operators["peer"], plan.group)
        return _finish(_direction_expr(expr, plan.direction), plan)
    if template == "two_series_correlation":
        field_b = plan.field_names[1]
        expr = f"ts_corr({field_a}, {field_b}, {window})"
        expr = _peer(expr, plan.operators["peer"], plan.group)
        return _finish(_direction_expr(expr, plan.direction), plan)
    if template == "regression_residual":
        field_b = plan.field_names[1]
        rettype = int(plan.parameters["verified_rettype"])
        expr = f"ts_regression({field_a}, {field_b}, {window}, lag=0, rettype={rettype})"
        expr = _peer(expr, plan.operators["peer"], plan.group)
        return _finish(_direction_expr(expr, plan.direction), plan)
    if template == "risk_dispersion":
        expr = f"ts_std_dev({field_a}, {window})"
        expr = f"ts_rank({expr}, {window})"
        expr = _peer(expr, plan.operators["peer"], plan.group)
        return _finish(_direction_expr(expr, plan.direction), plan)
    if template == "peer_residual":
        expr = f"group_neutralize({field_a}, {plan.group})"
        expr = f"ts_rank({expr}, {window})"
        return _finish(_direction_expr(expr, plan.direction), plan)
    if template == "state_gated_core":
        p = plan.parameters
        expr = f"trade_when({p['condition_expression']}, {p['core_expression']}, {p['exit_expression']})"
        return _finish(expr, plan)
    if template == "multi_horizon_consensus":
        w_slow, w_fast = plan.windows
        branch_slow = _direction_expr(_peer(f"ts_rank({field_a}, {w_slow})", plan.operators["peer"], plan.group), plan.direction)
        branch_fast = _direction_expr(_peer(f"ts_rank({field_a}, {w_fast})", plan.operators["peer"], plan.group), plan.direction)
        a, b = plan.parameters["weights"]
        expr = f"add(multiply({a}, {branch_slow}), multiply({b}, {branch_fast}), filter=true)"
        return _finish(expr, plan)
    if template == "orthogonal_confirmation":
        field_b = plan.field_names[1]
        profile_a, profile_b = typed_profiles
        window_b = int(plan.parameters["window_b"])
        branch_a = _branch(field_a, profile_a, plan.operators["time_a"], window, plan.operators["peer_a"], plan.group, plan.direction)
        direction_b = profile_b.direction_prior if profile_b.direction_prior in {"positive", "negative"} else "positive"
        branch_b = _branch(field_b, profile_b, plan.operators["time_b"], window_b, plan.operators["peer_b"], plan.group, direction_b)
        a, b = plan.parameters["weights"]
        expr = f"add(multiply({a}, {branch_a}), multiply({b}, {branch_b}), filter=true)"
        return _finish(expr, plan)
    raise PlanError(f"No compiler for template: {template}")


def store_plan(connection: sqlite3.Connection, plan: AlphaPlan, *, request: PlanRequest, artifact_id: str | None = None, status: str = "compiled") -> None:
    connection.execute(
        """INSERT INTO alpha_plans(
            id,hypothesis_id,card_id,family,template_id,request_json,resolved_json,compiler_version,status,artifact_id,created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            plan.id, plan.hypothesis_id, plan.card_id, plan.family, plan.template_id,
            json_dumps(asdict(request)), json_dumps(plan.to_dict()), plan.compiler_version,
            status, artifact_id, utc_now(),
        ),
    )


def update_plan_artifact(connection: sqlite3.Connection, plan_id: str, artifact_id: str | None, status: str) -> None:
    connection.execute("UPDATE alpha_plans SET artifact_id=?,status=? WHERE id=?", (artifact_id, status, plan_id))


__all__ = [
    "ALLOWED_GROUPS",
    "AlphaPlan",
    "HORIZON_BUCKETS",
    "PlanError",
    "PlanRequest",
    "compile_plan",
    "resolve_request",
    "store_plan",
    "update_plan_artifact",
]
