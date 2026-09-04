from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass

from ..config import load_defaults
from ..dsl.specs import SPECS
from .scheduler import choose_family, mutation_hint


PROMPT_VERSION = "research-v1"


@dataclass(frozen=True)
class PromptPacket:
    system: str
    user: str
    prompt_hash: str


def _field_rows(connection: sqlite3.Connection, limit: int = 36) -> list[dict[str, object]]:
    minimum_coverage = float(load_defaults()["research"]["min_field_coverage"])
    rows = connection.execute(
        """SELECT name,dataset_name,description,data_type,coverage,semantic_theme,semantic_direction
           FROM fields WHERE upper(coalesce(data_type,'MATRIX')) IN ('MATRIX','VECTOR')
             AND (coverage IS NULL OR coverage>=?)
           ORDER BY CASE WHEN semantic_theme='generic' THEN 1 ELSE 0 END,coalesce(coverage,0) DESC,name LIMIT 800""",
        (minimum_coverage,),
    ).fetchall()
    selected: list[dict[str, object]] = []
    theme_counts: dict[str, int] = {}
    dataset_counts: dict[str, int] = {}
    for row in rows:
        item = dict(row)
        theme = str(item.get("semantic_theme") or "generic")
        dataset = str(item.get("dataset_name") or "unknown")
        if theme_counts.get(theme, 0) >= 12 or dataset_counts.get(dataset, 0) >= 16:
            continue
        selected.append(item)
        theme_counts[theme] = theme_counts.get(theme, 0) + 1
        dataset_counts[dataset] = dataset_counts.get(dataset, 0) + 1
        if len(selected) >= limit:
            break
    return selected


def build_prompt(connection: sqlite3.Connection, count: int) -> PromptPacket:
    winners = [dict(row) for row in connection.execute(
        """SELECT family,canonical_expression,best_reward FROM alpha_artifacts
           WHERE status IN ('promoted','tested') ORDER BY best_reward DESC LIMIT 12"""
    ).fetchall()]
    rejected = [dict(row) for row in connection.execute(
        "SELECT expression,reason FROM rejected_candidates ORDER BY created_at DESC LIMIT 20"
    ).fetchall()]
    existing = [row[0] for row in connection.execute(
        "SELECT canonical_expression FROM alpha_artifacts ORDER BY created_at DESC LIMIT 80"
    ).fetchall()]
    operator_contract = {
        name: {"min": item.minimum_args, "max": item.maximum_args, "kwargs": sorted(item.allowed_kwargs)}
        for name, item in SPECS.items()
    }
    latest_run = connection.execute(
        """SELECT r.sharpe,r.fitness,r.turnover FROM simulation_runs r
           WHERE r.platform_status='COMPLETE' ORDER BY r.finished_at DESC LIMIT 1"""
    ).fetchone()
    system = (
        "Bạn là nhà nghiên cứu alpha định lượng. Chỉ tạo biểu thức FASTEXPR từ đúng danh mục đã cho. "
        "Không bịa trường hoặc toán tử. Mỗi đề xuất bắt đầu từ cơ chế kinh tế, chỉ thay một ý tưởng chính, "
        "và không suy diễn rằng alpha tốt khi chưa có mô phỏng. Trả về duy nhất JSON hợp lệ."
    )
    context = {
        "count": count,
        "selected_family": choose_family(connection),
        "evidence_based_mutation_hint": mutation_hint(latest_run) if latest_run else None,
        "output_schema": {"proposals": [{"expression": "string", "family": "snake_case", "rationale": "Vietnamese", "mutation": "string or null", "parent_id": "string or null"}]},
        "requirements": [
            "Mỗi biểu thức phải có kiểm soát chéo như group_rank, group_neutralize, rank hoặc normalize.",
            "Ưu tiên giả thuyết đơn giản, có thể bác bỏ; dùng tối đa 3 trường dữ liệu.",
            "Không chép hoặc chỉ đổi hằng số của biểu thức đã có, trừ khi ghi mutation bắt đầu bằng sensitivity: và có parent_id.",
            "VECTOR phải qua vec_avg hoặc vec_sum trước toán tử chuỗi thời gian hay chéo.",
            "Không dùng kết quả mô phỏng giả định trong rationale.",
        ],
        "fields": _field_rows(connection),
        "operators": operator_contract,
        "verified_or_tested": winners,
        "recent_rejections": rejected,
        "do_not_duplicate": existing,
    }
    user = json.dumps(context, ensure_ascii=False, indent=2)
    digest = hashlib.sha256((system + "\n" + user).encode()).hexdigest()
    return PromptPacket(system, user, digest)
