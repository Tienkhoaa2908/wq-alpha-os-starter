from __future__ import annotations

"""Agentic research v2: hypothesis -> AlphaPlan -> deterministic compiler.

The language model never writes FASTEXPR or selects concrete operator names in
this workflow. It reasons about economic hypotheses and high-level research
paths. Local code resolves operators/windows, compiles, validates, fingerprints
and ingests candidates.
"""

from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import json
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from ..config import Settings
from ..db import json_dumps, utc_now
from ..providers import CompletionProvider, provider_for
from .artifacts import ingest_candidate
from .discovery_v2 import build_discovery_context
from .field_profiles import compact_payload as compact_field_payload
from .field_profiles import stored_profile
from .path_templates import compact_payload as compact_template_payload
from .plans import PlanError, PlanRequest, compile_plan, resolve_request, store_plan, update_plan_artifact


AGENT_V2_VERSION = "semantic-plan-agent-v2"
_FAMILY_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")


def _gemini_settings(settings: Settings) -> Settings:
    return settings if settings.llm_provider.lower() == "gemini" else replace(settings, llm_provider="gemini")


def _model_name(settings: Settings) -> str:
    return settings.gemini_model if settings.llm_provider.lower() == "gemini" else settings.llm_model


def _parse_object(text: str) -> dict[str, Any]:
    clean = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", clean, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        clean = fenced.group(1).strip()
    try:
        value = json.loads(clean)
    except json.JSONDecodeError:
        start, end = clean.find("{"), clean.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("Model did not return a JSON object") from None
        value = json.loads(clean[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("Model response must be a JSON object")
    return value


def _write_exchange(settings: Settings, stage: str, system: str, user: str, answer: str) -> tuple[Path, str]:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    path = settings.evidence_dir / "agent_v2" / stage / f"{stamp}-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=False)
    prompt_hash = hashlib.sha256((system + "\n" + user).encode("utf-8")).hexdigest()
    (path / "request.json").write_text(
        json_dumps({"version": AGENT_V2_VERSION, "prompt_hash": prompt_hash, "system": system, "user": user}),
        encoding="utf-8",
    )
    (path / "response.txt").write_text(answer, encoding="utf-8")
    return path, prompt_hash


def _discovery_system() -> str:
    return """Bạn là tác nhân khám phá giả thuyết alpha định lượng. TUYỆT ĐỐI không viết FASTEXPR, công thức,
tên toán tử hay kết quả mô phỏng. Chỉ dùng đúng field trong candidate_fields. Mỗi giả thuyết phải có một
cơ chế kinh tế duy nhất, khác các họ đã bão hòa, có thể bác bỏ, và nếu kế thừa một parent tương quan cao thì
phải đổi field hoặc cơ chế chứ không đổi cửa sổ/hằng số.

Trả duy nhất JSON có khóa hypotheses. Mỗi phần tử gồm:
- family: snake_case mới;
- statement;
- mechanism;
- expected_direction: positive|negative|ambiguous;
- horizon_bucket: event|short|medium|long|very_slow;
- field_names: 1 hoặc 2 tên chính xác từ candidate_fields;
- falsifier;
- novelty: giải thích vì sao khác họ/cơ chế đã thử.

Không được có expression, formula, operator, operator_roles hay parameters."""


def _validate_hypothesis(raw: Any, allowed_fields: set[str], existing_families: set[str]) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(raw, dict):
        return None, "not_object"
    lowered_keys = {str(key).lower() for key in raw}
    if lowered_keys & {"expression", "formula", "operator", "operators", "operator_roles", "parameters"}:
        return None, "forbidden_formula_content"
    family = str(raw.get("family") or "").strip().lower()
    if not _FAMILY_RE.fullmatch(family):
        return None, "invalid_family"
    if family in existing_families:
        return None, "existing_family"
    text_fields = {}
    for key in ("statement", "mechanism", "falsifier", "novelty"):
        value = " ".join(str(raw.get(key) or "").split())
        if not value:
            return None, f"missing_{key}"
        text_fields[key] = value
    direction = str(raw.get("expected_direction") or "ambiguous").strip().lower()
    if direction not in {"positive", "negative", "ambiguous"}:
        return None, "invalid_direction"
    horizon = str(raw.get("horizon_bucket") or "medium").strip().lower()
    if horizon not in {"event", "short", "medium", "long", "very_slow"}:
        return None, "invalid_horizon"
    fields = [str(item).strip() for item in raw.get("field_names", []) if str(item).strip()]
    fields = list(dict.fromkeys(fields))
    if not 1 <= len(fields) <= 2 or not set(name.lower() for name in fields).issubset(allowed_fields):
        return None, "field_outside_packet"
    return {
        "family": family,
        **text_fields,
        "expected_direction": direction,
        "horizon_bucket": horizon,
        "field_names": fields,
    }, None


def discover(
    connection: sqlite3.Connection,
    count: int = 6,
    *,
    settings: Settings | None = None,
    provider: CompletionProvider | None = None,
) -> dict[str, Any]:
    settings = _gemini_settings(settings or Settings.from_env())
    context = build_discovery_context(connection, count=count)
    system = _discovery_system()
    user = json_dumps(context)
    answer = (provider or provider_for(settings)).complete(system, user)
    evidence, prompt_hash = _write_exchange(settings, "discovery", system, user, answer)
    payload = _parse_object(answer)
    raw_items = payload.get("hypotheses")
    if not isinstance(raw_items, list):
        raise ValueError("Hypothesis response has no hypotheses list")
    allowed_fields = {str(item["name"]).lower() for item in context["candidate_fields"]}
    existing_families = {str(row[0]).lower() for row in connection.execute("SELECT family FROM hypotheses")}
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for raw in raw_items[: max(count * 2, count)]:
        card, reason = _validate_hypothesis(raw, allowed_fields, existing_families)
        if card is None:
            rejected.append({"reason": reason})
            continue
        hypothesis_id = str(uuid.uuid4())
        card_id = str(uuid.uuid4())
        connection.execute(
            "INSERT INTO hypotheses VALUES(?,?,?,?,?,?,?)",
            (hypothesis_id, card["family"], card["statement"], card["mechanism"], card["expected_direction"], "semantic_discovery_v2", utc_now()),
        )
        connection.execute(
            """INSERT INTO hypothesis_cards VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                card_id, hypothesis_id, card["family"], card["statement"], card["mechanism"], card["expected_direction"],
                card["horizon_bucket"], json_dumps([]), json_dumps(card["field_names"]), json_dumps([]),
                card["falsifier"], json_dumps({"statement": card["novelty"]}), "discovered", "semantic_discovery_v2",
                _model_name(settings), prompt_hash, str(evidence), utc_now(),
            ),
        )
        existing_families.add(card["family"])
        accepted.append({"card_id": card_id, "family": card["family"], "field_names": card["field_names"], "horizon_bucket": card["horizon_bucket"]})
        if len(accepted) >= count:
            break
    return {"version": AGENT_V2_VERSION, "evidence_path": str(evidence), "accepted": accepted, "rejected": rejected}


def packet(connection: sqlite3.Connection, count: int = 6) -> dict[str, Any]:
    return build_discovery_context(connection, count=count)


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
        design_user = json_dumps({"version": AGENT_V2_VERSION, "requested_plans": per_card, "hypothesis_card": card})
        answer = model.complete(design_system, design_user)
        design_evidence, design_hash = _write_exchange(settings, "plan_design", design_system, design_user, answer)
        payload = _parse_object(answer)
        raw_plans = payload.get("plans")
        if not isinstance(raw_plans, list):
            raise ValueError("Plan designer response has no plans list")
        raw_plans = [item for item in raw_plans if isinstance(item, dict)][:per_card]

        critic_system = _critic_system()
        critic_user = json_dumps({"hypothesis_card": card, "plans": raw_plans})
        critic_answer = model.complete(critic_system, critic_user)
        critic_evidence, _ = _write_exchange(settings, "plan_critic", critic_system, critic_user, critic_answer)
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
    count: int = 6,
    *,
    per_card: int = 1,
    settings: Settings | None = None,
    provider: CompletionProvider | None = None,
) -> dict[str, Any]:
    discovered = discover(connection, count, settings=settings, provider=provider)
    designed = design(connection, count, per_card=per_card, settings=settings, provider=provider)
    return {"version": AGENT_V2_VERSION, "discovery": discovered, "design": designed, "simulated": 0}


__all__ = ["AGENT_V2_VERSION", "design", "discover", "packet", "run_cycle"]
