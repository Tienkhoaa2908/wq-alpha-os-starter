from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from .fingerprint import Fingerprint, fingerprint
from .nodes import Binary, Call, Identifier, Node, Number, String, Unary, node_count, node_depth, walk
from .parser import ParseError, parse
from .specs import GROUP_IDENTIFIERS, LITERALS, SPECS


class ValueType(str, Enum):
    MATRIX = "MATRIX"
    VECTOR = "VECTOR"
    GROUP = "GROUP"
    BOOLEAN = "BOOLEAN"
    SCALAR = "SCALAR"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    code: str
    message: str


@dataclass(frozen=True)
class ValidationReport:
    valid: bool
    issues: tuple[ValidationIssue, ...]
    fingerprint: Fingerprint | None
    node_count: int
    depth: int

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        if self.fingerprint:
            result["fingerprint"] = asdict(self.fingerprint)
        return result


def load_field_types(connection: sqlite3.Connection) -> dict[str, ValueType]:
    rows = connection.execute("SELECT name,data_type FROM fields").fetchall()
    result: dict[str, ValueType] = {}
    for row in rows:
        raw_type = str(row[1] or "").upper()
        result[str(row[0]).lower()] = (
            ValueType(raw_type) if raw_type in ValueType._value2member_map_ else ValueType.UNKNOWN
        )
    return result


def _infer_type(
    node: Node,
    field_types: dict[str, ValueType],
    issues: list[ValidationIssue],
) -> ValueType:
    if isinstance(node, Number) or isinstance(node, String):
        return ValueType.SCALAR
    if isinstance(node, Identifier):
        name = node.name.lower()
        if name in {"true", "false"}:
            return ValueType.BOOLEAN
        if name in GROUP_IDENTIFIERS:
            return ValueType.GROUP
        if name in LITERALS:
            return ValueType.SCALAR
        if name not in field_types:
            issues.append(
                ValidationIssue("error", "unknown_field", f"Không có trường dữ liệu: {node.name}")
            )
            return ValueType.UNKNOWN
        return field_types[name]
    if isinstance(node, Unary):
        return _infer_type(node.operand, field_types, issues)
    if isinstance(node, Binary):
        left = _infer_type(node.left, field_types, issues)
        right = _infer_type(node.right, field_types, issues)
        if node.operator in {">", ">=", "<", "<=", "==", "!="}:
            return ValueType.BOOLEAN
        if ValueType.VECTOR in {left, right}:
            issues.append(
                ValidationIssue(
                    "error", "vector_not_reduced", "Trường Vector phải qua vec_avg hoặc vec_sum"
                )
            )
        return left if left != ValueType.SCALAR else right
    if isinstance(node, Call):
        name = node.name.lower()
        argument_types = [_infer_type(arg, field_types, issues) for arg in node.args]
        for _, value in node.kwargs:
            _infer_type(value, field_types, issues)
        operator_spec = SPECS.get(name)
        if operator_spec is None:
            issues.append(
                ValidationIssue("error", "unknown_operator", f"Toán tử chưa được cho phép: {node.name}")
            )
        else:
            count = len(node.args)
            maximum = operator_spec.maximum_args
            if count < operator_spec.minimum_args or (maximum is not None and count > maximum):
                upper = "không giới hạn" if maximum is None else str(maximum)
                issues.append(
                    ValidationIssue(
                        "error",
                        "operator_arity",
                        f"{node.name} nhận {operator_spec.minimum_args}..{upper} tham số vị trí, đang có {count}",
                    )
                )
            allowed = operator_spec.allowed_kwargs
            for key, _ in node.kwargs:
                if key.lower() not in allowed:
                    issues.append(
                        ValidationIssue(
                            "error", "unknown_keyword", f"{node.name} không nhận tham số {key}"
                        )
                    )
            for position in operator_spec.group_positions:
                if position >= len(argument_types) or argument_types[position] != ValueType.GROUP:
                    issues.append(
                        ValidationIssue(
                            "error",
                            "group_type",
                            f"Tham số {position + 1} của {node.name} phải là trường Group",
                        )
                    )
        if name in {"and", "or", "not", "is_nan"}:
            return ValueType.BOOLEAN
        if name in {"vec_avg", "vec_sum"}:
            if argument_types and argument_types[0] != ValueType.VECTOR:
                issues.append(
                    ValidationIssue(
                        "warning", "unnecessary_vector_reduce", f"{name} đang nhận trường không phải Vector"
                    )
                )
            return ValueType.MATRIX
        if name in {"bucket", "densify"}:
            return ValueType.GROUP
        if name in {"if_else", "trade_when"} and len(argument_types) >= 2:
            return argument_types[1]
        if argument_types:
            first_non_scalar = next(
                (kind for kind in argument_types if kind not in {ValueType.SCALAR, ValueType.BOOLEAN}),
                argument_types[0],
            )
            return first_non_scalar
        return ValueType.UNKNOWN
    return ValueType.UNKNOWN


def validate_expression(
    expression: str,
    connection: sqlite3.Connection,
    *,
    max_nodes: int = 80,
    max_depth: int = 20,
) -> ValidationReport:
    issues: list[ValidationIssue] = []
    try:
        root = parse(expression)
    except ParseError as exc:
        return ValidationReport(
            False,
            (ValidationIssue("error", "parse_error", str(exc)),),
            None,
            0,
            0,
        )
    fields = load_field_types(connection)
    _infer_type(root, fields, issues)
    nodes = node_count(root)
    depth = node_depth(root)
    if nodes > max_nodes:
        issues.append(
            ValidationIssue("error", "too_many_nodes", f"Biểu thức có {nodes} nút, giới hạn {max_nodes}")
        )
    if depth > max_depth:
        issues.append(
            ValidationIssue("error", "too_deep", f"Độ sâu {depth}, giới hạn {max_depth}")
        )
    operators = {n.name.lower() for n in walk(root) if isinstance(n, Call)}
    if not operators & {"rank", "normalize", "group_rank", "group_zscore", "group_neutralize"}:
        issues.append(
            ValidationIssue(
                "warning",
                "no_cross_sectional_control",
                "Chưa thấy chuẩn hóa hoặc kiểm soát chéo theo nhóm",
            )
        )
    known_fields = set(fields)
    fp = fingerprint(expression, known_fields)
    valid = not any(issue.severity == "error" for issue in issues)
    return ValidationReport(valid, tuple(issues), fp, nodes, depth)
