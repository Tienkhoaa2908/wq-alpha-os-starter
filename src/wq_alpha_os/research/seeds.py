from __future__ import annotations

import sqlite3
import uuid

from ..db import utc_now
from ..dsl.fingerprint import fingerprint
from .artifacts import IngestResult, ingest_candidate


FAMILY = "value_cashflow_multihorizon"


def expressions(field: str) -> list[tuple[str, str, str | None]]:
    core = f"reverse(group_rank(ts_rank({field}, 504), industry))"
    return [
        (
            f"normalize(add(multiply(0.75, hump({core}, hump=0.01)), "
            f"multiply(0.25, reverse(group_rank(ts_rank({field}, 252), industry))), filter=true), useStd=true, limit=3)",
            "Mẫu gốc: giá trị tương đối theo ngành ở hai khung 504/252 ngày; nhánh dài được hãm thay đổi.", None,
        ),
        (f"normalize(hump({core}, hump=0.01), useStd=true, limit=3)",
         "Tách riêng nhánh 504 ngày để đo đóng góp của phối hợp nhiều khung.", "ablation:remove_252_sleeve"),
        (f"normalize(reverse(group_rank(ts_rank({field}, 252), industry)), useStd=true, limit=3)",
         "Tách riêng nhánh 252 ngày để đo vai trò của khung dài.", "ablation:remove_504_sleeve"),
        (f"normalize(add(multiply(0.6, hump({core}, hump=0.01)), multiply(0.4, reverse(group_rank(ts_rank({field}, 252), industry))), filter=true), useStd=true, limit=3)",
         "Thử độ nhạy trọng số 60/40, giữ nguyên cơ chế kinh tế.", "sensitivity:weights_60_40"),
        (f"normalize(add(multiply(0.85, hump({core}, hump=0.01)), multiply(0.15, reverse(group_rank(ts_rank({field}, 252), industry))), filter=true), useStd=true, limit=3)",
         "Thử độ nhạy trọng số 85/15, ưu tiên tín hiệu chậm.", "sensitivity:weights_85_15"),
        (f"normalize(add(multiply(0.75, hump({core}, hump=0.005)), multiply(0.25, reverse(group_rank(ts_rank({field}, 252), industry))), filter=true), useStd=true, limit=3)",
         "Thử hãm thay đổi mạnh hơn để kiểm soát vòng quay.", "sensitivity:hump_0005"),
        (f"normalize(add(multiply(0.75, hump({core}, hump=0.02)), multiply(0.25, reverse(group_rank(ts_rank({field}, 252), industry))), filter=true), useStd=true, limit=3)",
         "Thử hãm thay đổi nhẹ hơn để đo đánh đổi độ trễ và vòng quay.", "sensitivity:hump_002"),
        (f"normalize(add(multiply(0.75, hump(reverse(group_rank(ts_rank({field}, 756), industry)), hump=0.01)), multiply(0.25, reverse(group_rank(ts_rank({field}, 252), industry))), filter=true), useStd=true, limit=3)",
         "Thử độ nhạy khung dài 756 ngày.", "sensitivity:long_window_756"),
    ]


def seed_family(connection: sqlite3.Connection, field: str) -> list[IngestResult]:
    existing_hypothesis = connection.execute(
        "SELECT id FROM hypotheses WHERE family=? AND source='user_validated_seed' LIMIT 1", (FAMILY,)
    ).fetchone()
    hypothesis_id = existing_hypothesis[0] if existing_hypothesis else str(uuid.uuid4())
    if not existing_hypothesis:
        connection.execute(
            "INSERT INTO hypotheses VALUES(?,?,?,?,?,?,?)",
            (hypothesis_id, FAMILY,
             "Doanh nghiệp rẻ theo dòng tiền có xu hướng sinh lợi vượt trội sau khi so tương đối trong ngành.",
             "Xếp hạng theo thời gian làm ổn định mức định giá; xếp hạng trong ngành loại bớt khác biệt cấu trúc; đảo dấu biến mức rẻ thành vị thế mua.",
             "reverse", "user_validated_seed", utc_now()),
        )
    results: list[IngestResult] = []
    parent_id: str | None = None
    for index, (expression, rationale, mutation) in enumerate(expressions(field)):
        exact_hash = fingerprint(expression).exact_hash
        existing = connection.execute(
            "SELECT id FROM alpha_artifacts WHERE exact_hash=?", (exact_hash,)
        ).fetchone()
        if existing:
            result = IngestResult(False, existing[0], "already_seeded", 1.0)
            results.append(result)
            if index == 0:
                parent_id = existing[0]
            continue
        result = ingest_candidate(
            connection, expression=expression, family=FAMILY, rationale=rationale,
            generator="deterministic_seed", hypothesis_id=hypothesis_id,
            parent_id=parent_id if index else None, mutation=mutation, prompt_version="seed-v1",
        )
        results.append(result)
        if index == 0 and result.accepted:
            parent_id = result.artifact_id
    return results
