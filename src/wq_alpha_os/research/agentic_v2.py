from __future__ import annotations

"""Agentic research v2: LLM reasoning -> AlphaPlan -> deterministic compiler.

The language model never writes FASTEXPR in this workflow.  It selects a
hypothesis-compatible path and high-level intents; local code resolves
operators/windows, compiles, validates, fingerprints and ingests the candidate.
"""

import json
import sqlite3
from typing import Any

from ..config import Settings
from ..providers import CompletionProvider, provider_for
from .agentic import (
    _gemini_settings,
    _model_name,
    _parse_object,
    _write_exchange,
    discover,
    packet,
)
from .artifacts import ingest_candidate
from .field_profiles import compact_payload as compact_field_payload
from .field_profiles import stored_profile
from .path_templates import compact_payload as compact_template_payload
from .plans import PlanError, PlanRequest, compile_plan, resolve_request, store_plan, update_plan_artifact


AGENT_V2_VERSION = "semantic-plan-agent-v2"


def _design_system() -> str:
    return """Bạn là tác nhân thiết kế thí nghiệm alpha định lượng. Ở bước này TUYỆT ĐỐI KHÔNG viết FASTEXPR,
không viết tên toán tử cụ thể, không bịa kết quả mô phỏng. Chỉ chọn một khuôn nghiên cứu được cấp và mô tả
ý định cấp cao để bộ biên dịch cục bộ quyết định toán tử/cửa sổ hợp lệ.

Trả về duy nhất JSON có khóa plans. Mỗi plan gồm:
- template_id: đúng một id từ allowed_templates;
- field_names: 1-2 tên đúng từ allowed_fields;
- horizon_bucket: event|short|medium|long|very_slow;
- direction: prior|positive|negative;
- group: market|sector|industry|subindustry|country|exchange|currency;
- relative_mode: spread|ratio (chỉ quan trọng với relative_ratio);
- extremum: max|min (chỉ quan trọng với extremum_recency);
- turnover_control: boolean;
- output_control: standardize|none;
- branch_weights: null hoặc hai số dương tổng bằng 1;
- rationale: lý do kinh tế ngắn, có thể bác bỏ.

Không được thêm khóa expression/formula/operator/operator_name. Không tối ưu hằng số. Multi-horizon chỉ là kiểm tra
độ bền, không được mô tả như novelty. Hai nhánh orthogonal_confirmation phải khác cơ chế/chủ đề thật."""


def _critic_system() -> str:
    return """Bạn là phản biện độc lập của AlphaPlan cấp cao. Không viết FASTEXPR và không sửa plan.
Đánh giá: plan có kiểm tra đúng giả thuyết không, field có phù hợp semantic không, template có hợp lý không,
đây có phải clone tham số của họ cũ không, và thí nghiệm có thể bác bỏ không.
Trả về JSON duy nhất: {\"decisions\":[{\"index\":0,\"verdict\":\"accept\"|\"reject\",\"reasons\":[\"...\"]}]}.
Chỉ accept khi plan tối giản và có cơ chế rõ."""


def _card_context(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    names = [str(name) for name in json.loads(row["field_names_json"] or "[]")]
    profiles = [profile for name in names if (profile := stored_profile(connection, name)) is not None]
    return {
        "card_id": row["id"],
        "family": row["family"],
        "statement": row["statement"],
        "mechanism": row["mechanism"],
        "expected_direction": row["expected_direction"],
        "horizon": row["horizon"],
        "falsifier": row["falsifier"],
        "allowed_fields": compact_field_payload(profiles),
        "allowed_templates": compact_template_payload(profiles),
        "rules": [
            "No FASTEXPR and no operator names in model output.",
            "One plan tests one economic mechanism.",
            "Do not use dense parameter search.",
            "High-correlation families require semantic/field branching rather than window tweaks.",
        ],
    }


def _decisions(answer: str, count: int) -> dict[int, dict[str, Any]]:
    data = _parse_object(answer)
    raw = data.get("decisions")
    if not isinstance(raw, list):
        raise ValueError("Critic response has no decisions list")
    result: dict[int, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        verdict = str(item.get("verdict") or "").lower()
        if isinstance(index, int) and 0 <= index < count and verdict in {"accept", "reject"}:
            result[index] = {
                "verdict": verdict,
                "reasons": [str(reason) for reason in item.get("reasons", []) if str(reason).strip()][:4],
            }
    return result


def _validate_request_shape(raw: Any, allowed_fields: set[str], allowed_templates: set[str]) -> PlanRequest:
    if not isinstance(raw, dict):
        raise PlanError("plan_not_object")
    forbidden = {"expression", "formula", "operator", "operator_name", "operators"}
    if forbidden & {str(key).lower() for key in raw}:
        raise PlanError("model_attempted_expression_or_operator_selection")
    request = PlanRequest.from_dict(raw)
    if request.template_id not in allowed_templates:
        raise PlanError("template_outside_card")
    if not request.field_names or not set(name.lower() for name in request.field_names).issubset(allowed_fields):
        raise PlanError("field_outside_card")
    return request


def design(
    connection: sqlite3.Connection,
    limit: int = 4,
    *,
    per_card: int = 2,
    settings: Settings | None = None,
    provider: CompletionProvider | None = None,
) -> dict[str, Any]:
    settings = _gemini_settings(settings or Settings.from_env())
    if limit <= 0 or per_card <= 0:
        return {"cards": [], "accepted": 0, "rejected": 0}
    rows = connection.execute(
        "SELECT * FROM hypothesis_cards WHERE status='discovered' ORDER BY created_at LIMIT ?", (limit,)
    ).fetchall()
    model = provider or provider_for(settings)
    card_results: list[dict[str, Any]] = []
    accepted_total = rejected_total = 0

    for row in rows:
        card = _card_context(connection, row)
        allowed_fields = {str(item["name"]).lower() for item in card["allowed_fields"]}
        allowed_templates = {str(item["id"]) for item in card["allowed_templates"]}
        if not allowed_templates:
            connection.execute("UPDATE hypothesis_cards SET status='design_rejected' WHERE id=?", (row["id"],))
            card_results.append({"card_id": row["id"], "accepted": [], "rejected": [{"reason": "no_eligible_template"}]})
            rejected_total += 1
            continue

        design_system = _design_system()
        design_user = json.dumps({"version": AGENT_V2_VERSION, "requested_plans": per_card, "hypothesis_card": card}, ensure_ascii=False)
        answer = model.complete(design_system, design_user)
        design_evidence, design_hash = _write_exchange(settings, "plan_design_v2", design_system, design_user, answer)
        payload = _parse_object(answer)
        raw_plans = payload.get("plans")
        if not isinstance(raw_plans, list):
            raise ValueError("Plan designer response has no plans list")
        raw_plans = [item for item in raw_plans if isinstance(item, dict)][:per_card]

        critic_system = _critic_system()
        critic_user = json.dumps({"hypothesis_card": card, "plans": raw_plans}, ensure_ascii=False)
        critic_answer = model.complete(critic_system, critic_user)
        critic_evidence, _ = _write_exchange(settings, "plan_critic_v2", critic_system, critic_user, critic_answer)
        decisions = _decisions(critic_answer, len(raw_plans))

        accepted_here: list[dict[str, Any]] = []
        rejected_here: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_plans):
            decision = decisions.get(index, {"verdict": "reject", "reasons": ["missing_valid_critic_decision"]})
            if decision["verdict"] != "accept":
                rejected_here.append({"index": index, "reason": "critic_reject", "details": decision["reasons"]})
                continue
            try:
                request = _validate_request_shape(raw, allowed_fields, allowed_templates)
                plan = resolve_request(
                    connection, request, family=row["family"], hypothesis_id=row["hypothesis_id"], card_id=row["id"]
                )
                expression = compile_plan(connection, plan)
                store_plan(connection, plan, request=request, status="compiled")
                result = ingest_candidate(
                    connection,
                    expression=expression,
                    family=row["family"],
                    rationale=(request.rationale + " " if request.rationale else "") + f"AlphaPlan {plan.id}; compiled deterministically from {plan.template_id}.",
                    generator="semantic_plan_agent_v2",
                    model_name=_model_name(settings),
                    prompt_hash=design_hash,
                    prompt_version=AGENT_V2_VERSION,
                    hypothesis_id=row["hypothesis_id"],
                    mutation=f"plan:{plan.template_id}",
                )
                update_plan_artifact(connection, plan.id, result.artifact_id, "validated" if result.accepted else "ingest_rejected")
                if result.accepted:
                    accepted_here.append({"plan_id": plan.id, "artifact_id": result.artifact_id, "template_id": plan.template_id})
                else:
                    rejected_here.append({"index": index, "reason": result.reason, "plan_id": plan.id, "similarity": result.similarity})
            except (PlanError, ValueError) as exc:
                rejected_here.append({"index": index, "reason": "plan_validation", "details": str(exc)})

        status = "designed" if accepted_here else "design_rejected"
        connection.execute("UPDATE hypothesis_cards SET status=? WHERE id=?", (status, row["id"]))
        accepted_total += len(accepted_here)
        rejected_total += len(rejected_here)
        card_results.append({
            "card_id": row["id"], "family": row["family"], "accepted": accepted_here, "rejected": rejected_here,
            "design_evidence": str(design_evidence), "critic_evidence": str(critic_evidence),
        })
    return {"version": AGENT_V2_VERSION, "cards": card_results, "accepted": accepted_total, "rejected": rejected_total}


def run_cycle(
    connection: sqlite3.Connection,
    count: int = 4,
    *,
    per_card: int = 2,
    settings: Settings | None = None,
    provider: CompletionProvider | None = None,
) -> dict[str, Any]:
    discovered = discover(connection, count, settings=settings, provider=provider)
    designed = design(connection, count, per_card=per_card, settings=settings, provider=provider)
    return {"version": AGENT_V2_VERSION, "discovery": discovered, "design": designed, "simulated": 0}


__all__ = ["AGENT_V2_VERSION", "design", "discover", "packet", "run_cycle"]
