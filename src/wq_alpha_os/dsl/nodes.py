from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable, Iterator


class Node:
    def children(self) -> Iterable["Node"]:
        return ()


@dataclass(frozen=True)
class Number(Node):
    raw: str


@dataclass(frozen=True)
class String(Node):
    value: str


@dataclass(frozen=True)
class Identifier(Node):
    name: str


@dataclass(frozen=True)
class Unary(Node):
    operator: str
    operand: Node

    def children(self) -> Iterable[Node]:
        return (self.operand,)


@dataclass(frozen=True)
class Binary(Node):
    operator: str
    left: Node
    right: Node

    def children(self) -> Iterable[Node]:
        return (self.left, self.right)


@dataclass(frozen=True)
class Call(Node):
    name: str
    args: tuple[Node, ...]
    kwargs: tuple[tuple[str, Node], ...] = ()

    def children(self) -> Iterable[Node]:
        return (*self.args, *(value for _, value in self.kwargs))


def walk(node: Node) -> Iterator[Node]:
    yield node
    for child in node.children():
        yield from walk(child)


def node_count(node: Node) -> int:
    return sum(1 for _ in walk(node))


def node_depth(node: Node) -> int:
    children = list(node.children())
    return 1 if not children else 1 + max(node_depth(child) for child in children)


def _number_text(raw: str) -> str:
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return raw
    if value == value.to_integral():
        return str(value.quantize(Decimal(1)))
    text = format(value.normalize(), "f")
    if text.startswith("0."):
        return text
    if text.startswith("-0."):
        return "-" + text[2:]
    return text


def render(node: Node, *, structural: bool = False, abstract_fields: set[str] | None = None) -> str:
    if isinstance(node, Number):
        return "#" if structural else _number_text(node.raw)
    if isinstance(node, String):
        return "STR" if structural else json.dumps(node.value, ensure_ascii=False)
    if isinstance(node, Identifier):
        name = node.name.lower()
        if abstract_fields is not None and name in abstract_fields:
            return "FIELD" if structural else name
        return name
    if isinstance(node, Unary):
        return f"{node.operator}{render(node.operand, structural=structural, abstract_fields=abstract_fields)}"
    if isinstance(node, Binary):
        left = render(node.left, structural=structural, abstract_fields=abstract_fields)
        right = render(node.right, structural=structural, abstract_fields=abstract_fields)
        if structural and node.operator in {"+", "*", "==", "!="} and right < left:
            left, right = right, left
        return f"({left}{node.operator}{right})"
    if isinstance(node, Call):
        name = node.name.lower()
        args = [render(x, structural=structural, abstract_fields=abstract_fields) for x in node.args]
        if structural and name in {"add", "multiply", "max", "min"}:
            args.sort()
        kwargs = [
            f"{key.lower()}={render(value, structural=structural, abstract_fields=abstract_fields)}"
            for key, value in sorted(node.kwargs, key=lambda item: item[0].lower())
        ]
        return f"{name}({','.join(args + kwargs)})"
    raise TypeError(f"Unsupported node: {type(node)!r}")
