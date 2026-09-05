from __future__ import annotations

"""Semantic validation above the syntactic/type DSL validator.

This layer does not predict alpha quality.  It rejects combinations that are
known to be ill-defined from the live BRAIN catalog or from field/operator
semantics, and emits warnings for suspicious but potentially meaningful forms.
"""

from dataclasses import asdict, dataclass
import sqlite3
from typing import Any

from ..dsl.nodes import Binary, Call, Identifier, Node, Number, Unary, walk
from ..dsl.parser import ParseError, parse
from ..operator_registry import active_brain_operator_names
from .field_profiles import FieldProfile, stored_profile
from .operator_kb import SEMANTICS


@dataclass(frozen=True)
class SemanticIssue:
    severity: str
    code: str
    message: str
    operator: str | None = None


@dataclass(frozen=True)
class SemanticReport:
    valid: bool
    issues: tuple[SemanticIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "issues": [asdict(item) for item in self.issues]}


def _issue(issues: list[SemanticIssue], severity: str, code: str, message: str, operator: str | None = None) -> None:
    issues.append(SemanticIssue(severity, code, message, operator))


def _identifier_profile(connection: sqlite3.Connection, node: Node) -> FieldProfile | None:
    if isinstance(node, Identifier):
        return stored_profile(connection, node.name)
    return None


def _contains_protection(node: Node) -> bool:
    # Accept add(denominator, epsilon) as an explicit near-zero policy.  This
    # does not claim the epsilon is economically optimal; it only prevents the
    # expression from silently dividing by literal zero.
    if isinstance(node, Call) and node.name.lower() == "add":
        return any(isinstance(child, Number) for child in node.args)
    return False


def _walk_semantics(connection: sqlite3.Connection, node: Node, issues: list[SemanticIssue]) -> None:
    if isinstance(node, Call):
        name = node.name.lower()
        first = node.args[0] if node.args else None
        first_profile = _identifier_profile(connection, first) if first is not None else None

        if name == "log":
            if first_profile is not None and first_profile.signedness != "nonnegative":
                _issue(issues, "error", "log_domain_unknown", f"log({first_profile.name}) lacks a positive-domain guarantee.", name)
        elif name == "sqrt":
            if first_profile is not None and first_profile.signedness != "nonnegative":
                _issue(issues, "error", "sqrt_domain_unknown", f"sqrt({first_profile.name}) lacks a non-negative-domain guarantee.", name)
        elif name == "inverse":
            if first is not None and not _contains_protection(first):
                _issue(issues, "warning", "inverse_near_zero", "inverse is unstable near zero; require an explicit economic/domain justification or protection.", name)
        elif name == "divide" and len(node.args) >= 2:
            denominator = node.args[1]
            denominator_profile = _identifier_profile(connection, denominator)
            if not _contains_protection(denominator):
                if denominator_profile is None or denominator_profile.signedness != "nonnegative":
                    _issue(issues, "error", "divide_near_zero", "divide denominator has no explicit near-zero policy/domain guarantee.", name)
                else:
                    _issue(issues, "warning", "divide_unprotected", "Positive-domain denominator is not guaranteed to be bounded away from zero.", name)
        elif name == "ts_product":
            if first_profile is not None and first_profile.semantic_form not in {"return", "growth_rate"}:
                _issue(issues, "warning", "ts_product_semantics", "ts_product should be reserved for explicit multiplicative/compounding mechanisms.", name)
        elif name == "densify":
            if isinstance(first, Identifier):
                _issue(issues, "warning", "densify_group_only", "densify should operate on grouping data; a raw numeric field is suspicious.", name)
        elif name == "hump":
            if isinstance(first, Identifier):
                _issue(issues, "warning", "hump_on_raw_field", "hump is a position-change limiter and should usually follow signal extraction.", name)
        elif name == "sign":
            _issue(issues, "warning", "sign_information_loss", "sign discards magnitude; use only for a genuinely binary sign hypothesis.", name)
        elif name in {"power", "signed_power"}:
            _issue(issues, "warning", "curvature_overfit_risk", "Power exponents must come from a small canonical set, not dense tuning.", name)
        elif name == "ts_step":
            _issue(issues, "warning", "ts_step_helper_only", "ts_step is a helper/time-index, not a standalone predictive mechanism.", name)
        elif name == "ts_count_nans":
            _issue(issues, "warning", "missingness_signal_requires_hypothesis", "Missingness should be diagnostic unless information availability itself is the hypothesis.", name)

        # Detect a few semantically redundant nests.  These are warnings, not
        # blanket bans, because ablation/sensitivity experiments can be valid.
        if isinstance(first, Call):
            child = first.name.lower()
            standardizers = {"rank", "zscore", "normalize", "group_rank", "group_zscore", "group_scale", "scale", "quantile"}
            if name in standardizers and child in standardizers:
                _issue(issues, "warning", "stacked_standardizers", f"{name} is stacked over {child}; justify the second standardization.", name)
            if name == "group_neutralize" and child == "group_mean":
                _issue(issues, "warning", "redundant_peer_control", "group_mean and group_neutralize should not be stacked as equivalent peer controls.", name)

    for child in node.children():
        _walk_semantics(connection, child, issues)


def validate_semantics(expression: str, connection: sqlite3.Connection) -> SemanticReport:
    try:
        root = parse(expression)
    except ParseError as exc:
        return SemanticReport(False, (SemanticIssue("error", "parse_error", str(exc)),))
    issues: list[SemanticIssue] = []

    # If an active BRAIN snapshot exists, it is the availability truth.  This
    # blocks registry-only operators such as `std` without breaking isolated
    # unit tests/databases that intentionally have no BRAIN snapshot.
    active = active_brain_operator_names(connection)
    if active:
        for item in walk(root):
            if isinstance(item, Call):
                name = item.name.lower()
                if name not in active:
                    _issue(issues, "error", "inactive_brain_operator", f"Operator {name} is not active in the latest BRAIN snapshot.", name)

    _walk_semantics(connection, root, issues)
    return SemanticReport(not any(item.severity == "error" for item in issues), tuple(issues))


__all__ = ["SemanticIssue", "SemanticReport", "validate_semantics"]
