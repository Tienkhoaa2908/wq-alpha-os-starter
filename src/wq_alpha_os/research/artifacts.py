from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any

from ..config import load_defaults
from ..db import json_dumps, utc_now
from ..dsl.fingerprint import Fingerprint, similarity
from ..dsl.validator import validate_expression


@dataclass(frozen=True)
class IngestResult:
    accepted: bool
    artifact_id: str | None
    reason: str
    similarity: float = 0.0


def _existing_fingerprints(connection: sqlite3.Connection) -> list[tuple[str, Fingerprint]]:
    rows = connection.execute(
        "SELECT id,canonical_expression,exact_hash,structural_hash,field_names_json,operator_names_json FROM alpha_artifacts"
    ).fetchall()
    result = []
    for row in rows:
        fields = tuple(json.loads(row[4]))
        operators = tuple(json.loads(row[5]))
        # The abstract structure is recalculated only when needed by parsing the canonical form.
        from ..dsl.fingerprint import fingerprint
        parsed = fingerprint(row[1], set(fields))
        result.append((row[0], Fingerprint(row[1], row[2], row[3], parsed.abstract_structure, fields, operators)))
    return result


def _reject(connection: sqlite3.Connection, expression: str, family: str, reason: str,
            details: dict[str, Any], generator: str) -> IngestResult:
    connection.execute(
        "INSERT INTO rejected_candidates VALUES(?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), expression, family, reason, json_dumps(details), generator, utc_now()),
    )
    return IngestResult(False, None, reason, float(details.get("similarity", 0)))


def ingest_candidate(
    connection: sqlite3.Connection,
    *, expression: str, family: str, rationale: str, generator: str,
    model_name: str | None = None, prompt_hash: str | None = None,
    prompt_version: str = "v1", parent_id: str | None = None,
    hypothesis_id: str | None = None, mutation: str | None = None,
) -> IngestResult:
    limits = load_defaults()["research"]
    report = validate_expression(
        expression, connection, max_nodes=int(limits["max_expression_nodes"]),
        max_depth=int(limits["max_expression_depth"]),
    )
    if not report.valid or report.fingerprint is None:
        return _reject(connection, expression, family, "validation_failed", report.to_dict(), generator)
    fp = report.fingerprint
    nearest_id: str | None = None
    nearest = 0.0
    for artifact_id, other in _existing_fingerprints(connection):
        score = similarity(fp, other)
        if score > nearest:
            nearest, nearest_id = score, artifact_id
    if nearest == 1.0:
        return _reject(connection, expression, family, "exact_duplicate", {"similarity": nearest, "nearest_id": nearest_id}, generator)
    threshold = float(limits["near_duplicate_threshold"])
    controlled_test = bool(
        parent_id and mutation and mutation.lower().startswith(("sensitivity:", "ablation:"))
    )
    if nearest >= threshold and not controlled_test:
        return _reject(connection, expression, family, "near_duplicate", {"similarity": nearest, "nearest_id": nearest_id}, generator)
    artifact_id = str(uuid.uuid4())
    connection.execute(
        """INSERT INTO alpha_artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (artifact_id, parent_id, hypothesis_id, family, expression, fp.canonical, fp.exact_hash,
         fp.structural_hash, json_dumps(fp.fields), json_dumps(fp.operators), rationale, mutation,
         generator, model_name, prompt_hash, prompt_version, json_dumps(report.to_dict()),
         report.node_count, report.depth, "validated", None, utc_now()),
    )
    connection.execute(
        "INSERT INTO research_events(artifact_id,event_type,payload_json,created_at) VALUES(?,?,?,?)",
        (artifact_id, "candidate_ingested", json_dumps({"family": family, "nearest_similarity": nearest}), utc_now()),
    )
    return IngestResult(True, artifact_id, "accepted", nearest)
