from __future__ import annotations

import re
import sqlite3

from .artifacts import IngestResult, ingest_candidate


def evidence_mutations(connection: sqlite3.Connection, limit: int = 4) -> list[IngestResult]:
    rows = connection.execute(
        """SELECT a.id,a.family,a.expression,r.sharpe,r.fitness,r.turnover
           FROM alpha_artifacts a JOIN simulation_runs r ON r.artifact_id=a.id
           WHERE r.platform_status='COMPLETE' AND NOT EXISTS(
             SELECT 1 FROM alpha_artifacts child WHERE child.parent_id=a.id AND child.generator='evidence_mutation')
           ORDER BY r.finished_at DESC LIMIT ?""", (limit,),
    ).fetchall()
    results: list[IngestResult] = []
    for row in rows:
        expression = str(row["expression"])
        if row["turnover"] is not None and float(row["turnover"]) > 0.7:
            mutated = f"hump({expression}, hump=0.01)"
            mutation = "sensitivity:evidence_high_turnover_hump"
            rationale = "Vòng quay đã đo được quá cao; chỉ thêm giới hạn thay đổi vị thế để kiểm tra nguyên nhân."
        elif row["sharpe"] is not None and float(row["sharpe"]) < 0:
            mutated = f"reverse({expression})"
            mutation = "sensitivity:evidence_reverse_direction"
            rationale = "Sharpe đã đo được âm; chỉ đảo hướng để kiểm tra dấu của giả thuyết kinh tế."
        elif row["fitness"] is not None and float(row["fitness"]) < 1 and re.search(r"\b252\b", expression):
            mutated = re.sub(r"\b252\b", "504", expression, count=1)
            mutation = "sensitivity:evidence_longer_horizon"
            rationale = "Fitness đã đo được thấp; chỉ kéo dài một khung thời gian để kiểm tra độ nhiễu."
        else:
            continue
        results.append(ingest_candidate(
            connection, expression=mutated, family=row["family"], rationale=rationale,
            generator="evidence_mutation", parent_id=row["id"], mutation=mutation,
            prompt_version="evidence-v1",
        ))
    return results
