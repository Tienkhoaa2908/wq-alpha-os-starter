from __future__ import annotations

"""Multi-level novelty fingerprints for alpha research artifacts.

`legacy_unverified` artifacts are historical debris only. They are retained in
SQLite for provenance but are deliberately excluded from novelty, subtree and
empirical research memory so old bulk Gemini generations cannot bias v2.
"""

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import sqlite3
from typing import Any

from ..db import json_dumps, utc_now
from ..dsl.fingerprint import fingerprint
from ..dsl.nodes import Binary, Call, Identifier, Node, Number, String, Unary, render, walk
from ..dsl.parser import parse
from .field_profiles import stored_profile
from .operator_kb import SEMANTICS


LEGACY_EXCLUDED_STATUS = "legacy_unverified"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _role(name: str) -> str:
    return str(SEMANTICS.get(name.lower(), {}).get("role", f"operator:{name.lower()}"))


def _number_bucket(raw: str) -> str:
    try:
        value = float(Decimal(raw))
    except (InvalidOperation, ValueError):
        return "NUM"
    absolute = abs(value)
    if absolute <= 1:
        if absolute < 0.1:
            return "SMALL_WEIGHT_OR_EPS"
        if absolute < 0.4:
            return "LOW_WEIGHT"
        if absolute < 0.7:
            return "MID_WEIGHT"
        return "HIGH_WEIGHT"
    if absolute <= 20:
        return "EVENT_OR_SMALL_PARAM"
    if absolute <= 63:
        return "SHORT_HORIZON"
    if absolute <= 126:
        return "MEDIUM_HORIZON"
    if absolute <= 252:
        return "LONG_HORIZON"
    return "VERY_SLOW_HORIZON"


def _normalized_node(node: Node) -> str:
    if isinstance(node, Number):
        return _number_bucket(node.raw)
    if isinstance(node, Identifier):
        return node.name.lower()
    if isinstance(node, String):
        return "STR"
    if isinstance(node, Unary):
        return f"{node.operator}{_normalized_node(node.operand)}"
    if isinstance(node, Binary):
        left = _normalized_node(node.left)
        right = _normalized_node(node.right)
        if node.operator in {"+", "*", "==", "!="} and right < left:
            left, right = right, left
        return f"({left}{node.operator}{right})"
    if isinstance(node, Call):
        name = node.name.lower()
        args = [_normalized_node(item) for item in node.args]
        if name in {"add", "multiply", "max", "min"}:
            args.sort()
        kwargs = [f"{key.lower()}={_normalized_node(value)}" for key, value in sorted(node.kwargs, key=lambda item: item[0].lower())]
        return f"{name}({','.join(args + kwargs)})"
    raise TypeError(f"Unsupported node type: {type(node)!r}")


def _parameter_normalized(expression: str) -> str:
    # AST-aware normalization prevents digits inside field identifiers such as
    # mdl177_2 from being mistaken for tunable constants.
    return _normalized_node(parse(expression))


@dataclass(frozen=True)
class MotifFingerprint:
    role_motif_hash: str
    semantic_hash: str
    parameter_hash: str
    role_path: tuple[str, ...]
    field_themes: tuple[str, ...]
    field_forms: tuple[str, ...]
    subtree_hashes: tuple[str, ...]
    parameter_normalized: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key, item in tuple(value.items()):
            if isinstance(item, tuple):
                value[key] = list(item)
        return value


def motif_fingerprint(connection: sqlite3.Connection, expression: str) -> MotifFingerprint:
    fp = fingerprint(expression)
    root = parse(expression)
    role_path = tuple(_role(item.name) for item in walk(root) if isinstance(item, Call))
    themes: list[str] = []
    forms: list[str] = []
    for name in fp.fields:
        profile = stored_profile(connection, name)
        themes.append(profile.economic_theme if profile else "unknown")
        forms.append(profile.semantic_form if profile else "unknown")
    field_set = set(fp.fields)
    subtree_hashes = tuple(sorted({
        _sha(render(item, structural=True, abstract_fields=field_set))
        for item in walk(root) if isinstance(item, Call)
    }))
    role_text = ">".join(role_path)
    semantic_text = "|".join((",".join(sorted(themes)), ",".join(sorted(forms)), role_text))
    normalized = _parameter_normalized(expression)
    return MotifFingerprint(
        role_motif_hash=_sha(role_text),
        semantic_hash=_sha(semantic_text),
        parameter_hash=_sha(normalized),
        role_path=role_path,
        field_themes=tuple(themes),
        field_forms=tuple(forms),
        subtree_hashes=subtree_hashes,
        parameter_normalized=normalized,
    )


def _active_motif_count(connection: sqlite3.Connection, column: str, value: str) -> int:
    if column not in {"semantic_hash", "role_motif_hash", "parameter_hash"}:
        raise ValueError(f"Unsupported motif column: {column}")
    row = connection.execute(
        f"""SELECT count(*)
            FROM artifact_motifs m
            JOIN alpha_artifacts a ON a.id=m.artifact_id
            WHERE m.{column}=? AND a.status<>?""",
        (value, LEGACY_EXCLUDED_STATUS),
    ).fetchone()
    return int(row[0])


def novelty_diagnostics(connection: sqlite3.Connection, motif: MotifFingerprint) -> dict[str, Any]:
    semantic_count = _active_motif_count(connection, "semantic_hash", motif.semantic_hash)
    role_count = _active_motif_count(connection, "role_motif_hash", motif.role_motif_hash)
    parameter_count = _active_motif_count(connection, "parameter_hash", motif.parameter_hash)
    subtree_counts: list[int] = []
    for subtree in motif.subtree_hashes:
        row = connection.execute("SELECT artifact_count FROM subtree_stats WHERE subtree_hash=?", (subtree,)).fetchone()
        subtree_counts.append(int(row[0]) if row else 0)
    max_subtree = max(subtree_counts, default=0)
    # A soft score: frequent motifs/subtrees reduce novelty but never ban a
    # profitable research motif. Semantic similarity is context, not a hard ban.
    penalty = 0.42 * math.log1p(role_count) + 0.38 * math.log1p(max_subtree) + 0.20 * math.log1p(parameter_count)
    novelty = round(max(0.0, 1.0 / (1.0 + penalty)), 6)
    return {
        "semantic_duplicate_count": semantic_count,
        "role_motif_count": role_count,
        "parameter_bucket_count": parameter_count,
        "max_subtree_count": max_subtree,
        "novelty_score": novelty,
    }


def store_artifact_motif(connection: sqlite3.Connection, artifact_id: str, expression: str) -> dict[str, Any]:
    status_row = connection.execute("SELECT status FROM alpha_artifacts WHERE id=?", (artifact_id,)).fetchone()
    if status_row is not None and str(status_row[0]) == LEGACY_EXCLUDED_STATUS:
        raise ValueError("legacy_unverified artifacts are excluded from v2 research memory")

    motif = motif_fingerprint(connection, expression)
    diagnostics = novelty_diagnostics(connection, motif)
    connection.execute(
        """INSERT OR REPLACE INTO artifact_motifs(
            artifact_id,role_motif_hash,semantic_hash,parameter_hash,role_path_json,field_themes_json,
            field_forms_json,subtree_hashes_json,parameter_normalized,novelty_score,created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            artifact_id, motif.role_motif_hash, motif.semantic_hash, motif.parameter_hash,
            json_dumps(motif.role_path), json_dumps(motif.field_themes), json_dumps(motif.field_forms),
            json_dumps(motif.subtree_hashes), motif.parameter_normalized, diagnostics["novelty_score"], utc_now(),
        ),
    )
    for subtree in motif.subtree_hashes:
        connection.execute(
            """INSERT INTO subtree_stats(subtree_hash,artifact_count,last_artifact_id,updated_at)
               VALUES(?,1,?,?) ON CONFLICT(subtree_hash) DO UPDATE SET
               artifact_count=subtree_stats.artifact_count+1,last_artifact_id=excluded.last_artifact_id,
               updated_at=excluded.updated_at""",
            (subtree, artifact_id, utc_now()),
        )
    return {"motif": motif.to_dict(), "diagnostics": diagnostics}


def backfill_motifs(connection: sqlite3.Connection) -> dict[str, int]:
    """Rebuild derived motif memory from research-eligible artifacts only.

    Motif tables are caches, not source evidence. Rebuilding them makes the
    exclusion policy deterministic and removes any old Gemini bulk-generation
    contamination that may already have been materialized.
    """
    excluded_legacy = int(connection.execute(
        "SELECT count(*) FROM alpha_artifacts WHERE status=?", (LEGACY_EXCLUDED_STATUS,)
    ).fetchone()[0])
    connection.execute("DELETE FROM artifact_motifs")
    connection.execute("DELETE FROM subtree_stats")

    rows = connection.execute(
        """SELECT id,expression FROM alpha_artifacts
           WHERE status<>?
           ORDER BY created_at""",
        (LEGACY_EXCLUDED_STATUS,),
    ).fetchall()
    completed = failed = 0
    for row in rows:
        try:
            store_artifact_motif(connection, row["id"], row["expression"])
            completed += 1
        except Exception:
            failed += 1
    return {
        "materialized": completed,
        "failed": failed,
        "excluded_legacy": excluded_legacy,
    }


__all__ = [
    "LEGACY_EXCLUDED_STATUS",
    "MotifFingerprint",
    "backfill_motifs",
    "motif_fingerprint",
    "novelty_diagnostics",
    "store_artifact_motif",
]
