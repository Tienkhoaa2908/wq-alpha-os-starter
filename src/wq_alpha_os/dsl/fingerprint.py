from __future__ import annotations

import hashlib
from dataclasses import dataclass
from difflib import SequenceMatcher

from .nodes import Call, Identifier, Node, render, walk
from .parser import parse
from .specs import GROUP_IDENTIFIERS, LITERALS


@dataclass(frozen=True)
class Fingerprint:
    canonical: str
    exact_hash: str
    structural_hash: str
    abstract_structure: str
    fields: tuple[str, ...]
    operators: tuple[str, ...]


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def fingerprint(expression: str, known_fields: set[str] | None = None) -> Fingerprint:
    root = parse(expression)
    operator_names = sorted({n.name.lower() for n in walk(root) if isinstance(n, Call)})
    all_identifiers = {n.name.lower() for n in walk(root) if isinstance(n, Identifier)}
    if known_fields is None:
        fields = sorted(all_identifiers - GROUP_IDENTIFIERS - LITERALS)
    else:
        fields = sorted(
            (all_identifiers & {x.lower() for x in known_fields})
            - GROUP_IDENTIFIERS
            - LITERALS
        )
    field_set = set(fields)
    canonical = render(root)
    structural = render(root, structural=True)
    abstract_structure = render(root, structural=True, abstract_fields=field_set)
    return Fingerprint(
        canonical=canonical,
        exact_hash=_sha256(canonical),
        structural_hash=_sha256(structural),
        abstract_structure=abstract_structure,
        fields=tuple(fields),
        operators=tuple(operator_names),
    )


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    return len(left & right) / len(left | right)


def similarity(left: Fingerprint, right: Fingerprint) -> float:
    if left.exact_hash == right.exact_hash:
        return 1.0
    if left.structural_hash == right.structural_hash:
        return 0.98
    field_score = _jaccard(set(left.fields), set(right.fields))
    operator_score = _jaccard(set(left.operators), set(right.operators))
    tree_score = SequenceMatcher(
        None, left.abstract_structure, right.abstract_structure
    ).ratio()
    return round(0.45 * field_score + 0.25 * operator_score + 0.30 * tree_score, 6)
