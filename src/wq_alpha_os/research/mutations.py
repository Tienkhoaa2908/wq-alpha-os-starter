from __future__ import annotations

import sqlite3

from ..db import json_dumps, utc_now
from .artifacts import IngestResult, ingest_candidate
from .scheduler import diagnose_run


def evidence_mutations(connection: sqlite3.Connection, limit: int = 4) -> list[IngestResult]:
    """Create only low-risk diagnostic children that code can justify itself.

    Semantic branching, field replacement and near-threshold refinements are
    intentionally NOT synthesized by string editing.  Those decisions return
    to the hypothesis/AlphaPlan workflow.  This prevents the old behaviour of
    repeatedly changing 252->504 and manufacturing highly correlated clones.
    """
    rows = connection.execute(
        """SELECT a.id,a.family,a.expression,r.*
           FROM alpha_artifacts a JOIN simulation_runs r ON r.artifact_id=a.id
           WHERE r.platform_status='COMPLETE' AND NOT EXISTS(
             SELECT 1 FROM alpha_artifacts child
             WHERE child.parent_id=a.id AND child.generator='evidence_diagnostic_v2')
           ORDER BY r.finished_at DESC LIMIT ?""", (limit,),
    ).fetchall()
    results: list[IngestResult] = []
    for row in rows:
        diagnosis = diagnose_run(row)
        expression = str(row["expression"])
        if diagnosis.action == "TURNOVER_INTERVENTION":
            mutated = f"hump({expression}, hump=0.01)"
            mutation = "diagnostic:evidence_high_turnover_hump"
            rationale = "Measured turnover is too high; only add a position-change limiter to isolate turnover as the failure mode."
        elif diagnosis.action == "DIRECTION_DIAGNOSTIC":
            mutated = f"reverse({expression})"
            mutation = "diagnostic:evidence_reverse_direction"
            rationale = "Measured Sharpe is negative; only flip polarity once to test the economic sign."
        else:
            connection.execute(
                "INSERT INTO research_events(artifact_id,event_type,payload_json,created_at) VALUES(?,?,?,?)",
                (
                    row["id"], "automatic_mutation_skipped",
                    json_dumps({"action": diagnosis.action, "reason": diagnosis.rationale,
                                "required_change": diagnosis.allowed_change}), utc_now(),
                ),
            )
            continue
        results.append(ingest_candidate(
            connection, expression=mutated, family=row["family"], rationale=rationale,
            generator="evidence_diagnostic_v2", parent_id=row["id"], mutation=mutation,
            prompt_version="evidence-v2",
        ))
    return results
