"""Vòng tác nhân Gemini: giả thuyết -> thiết kế -> phản biện -> cổng cục bộ.

Mô-đun này cố ý không gọi BRAIN và không tự mô phỏng.  Gemini chỉ được dùng
để đề xuất giả thuyết rồi thiết kế một số biểu thức chẩn đoán nhỏ; SQLite và
bộ kiểm tra cục bộ giữ trạng thái, bằng chứng và quyết định chống trùng.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..config import Settings
from ..db import json_dumps, utc_now
from ..dsl.validator import validate_expression
from ..providers import CompletionProvider, provider_for
from .artifacts import IngestResult, ingest_candidate
from .knowledge import build_discovery_context
from .operator_graph import catalog_field_types, graph_payload, inspect_expression


AGENT_VERSION = "gemini-hypothesis-agent-v1"
_FAMILY_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_ALLOWED_ROLES = {
    "missing_data", "time_position", "time_change", "time_smoothing",
    "time_dispersion", "time_relation", "cross_section_rank",
    "cross_section_standardize", "group_control", "direction",
    "turnover_control", "arithmetic", "conditional",
}


def _model_name(settings: Settings) -> str:
    return settings.gemini_model if settings.llm_provider.lower() == "gemini" else settings.llm_model


def _gemini_settings(settings: Settings) -> Settings:
    """Tác nhân này dùng Gemini rõ ràng, không phụ thuộc cấu hình cũ của Qwen/Ollama."""
    return settings if settings.llm_provider.lower() == "gemini" else replace(settings, llm_provider="gemini")


def _new_evidence(settings: Settings, stage: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    path = settings.evidence_dir / "agent" / stage / f"{stamp}-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def _prompt_hash(system: str, user: str) -> str:
    return hashlib.sha256((system + "\n" + user).encode("utf-8")).hexdigest()


def _parse_object(text: str) -> dict[str, Any]:
    clean = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", clean, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        clean = fenced.group(1).strip()
    try:
        data = json.loads(clean)
    except json.JSONDecodeError:
        start, end = clean.find("{"), clean.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("Gemini không trả về đối tượng JSON hợp lệ.") from None
        data = json.loads(clean[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("Gemini phải trả về một đối tượng JSON.")
    return data


def _write_exchange(settings: Settings, stage: str, system: str, user: str, answer: str) -> tuple[Path, str]:
    evidence = _new_evidence(settings, stage)
    digest = _prompt_hash(system, user)
    (evidence / "request.json").write_text(
        json_dumps({"version": AGENT_VERSION, "prompt_hash": digest, "system": system, "user": user}),
        encoding="utf-8",
    )
    (evidence / "response.txt").write_text(answer, encoding="utf-8")
    return evidence, digest


def _catalog_rows(connection: sqlite3.Connection) -> tuple[list[sqlite3.Row], dict[str, sqlite3.Row]]:
    rows = connection.execute(
        """SELECT name,dataset_name,description,data_type,coverage,semantic_theme,semantic_direction
           FROM fields WHERE name IS NOT NULL"""
    ).fetchall()
    return rows, {str(row["name"]).lower(): row for row in rows}


def _operator_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute("SELECT name,category,signature FROM operators WHERE name IS NOT NULL").fetchall()


def _discovery_graph(operators: list[sqlite3.Row]) -> dict[str, Any]:
    """Giữ cho bước khám phá chỉ thấy vai trò, không thấy bảng toán tử dài.

    Khám phá chưa được phép viết biểu thức, nên gửi chữ ký của hàng chục toán
    tử ở đây vừa tốn ngữ cảnh vừa khuyến khích mô hình nhảy ngay sang công
    thức. Bước thiết kế bên dưới mới nhận danh sách tên toán tử cụ thể.
    """
    graph = graph_payload(operators, compact=True)
    paths = []
    for path in graph["paths"]:
        paths.append({
            "id": path["id"],
            "input_kind": path["input_kind"],
            "ordered_roles": path["ordered_roles"],
            "slots": [
                {
                    key: slot[key]
                    for key in ("name", "role", "min_select", "max_select", "cluster")
                }
                for slot in path["slots"]
            ],
            "independence_rule": path["independence_rule"],
        })
    return {
        "version": graph["version"],
        "scope": graph["scope"],
        "hard_constraints": graph["hard_constraints"],
        "parameter_guidance": graph["parameter_guidance"],
        "paths": paths,
    }


def _design_graph(operators: list[sqlite3.Row], input_kind: str) -> dict[str, Any]:
    """Cấp đúng bảng toán tử cho một thẻ, thay vì cả danh mục cho mọi thẻ."""
    full_graph = graph_payload(operators, compact=True)
    paths = [path for path in full_graph["paths"] if path["input_kind"] == input_kind]
    allowed_names = {
        operator
        for path in paths
        for slot in path["slots"]
        for operator in slot["operators"]
    }
    # Các khuôn hai nhánh cần nhân với trọng số rõ ràng, dù phép nhân không
    # phải lúc nào cũng hiện trong một vị trí lựa chọn của khuôn.
    allowed_names.update({"multiply"})
    narrowed = graph_payload(operators, compact=True, operator_names=allowed_names)
    return {
        "version": narrowed["version"],
        "scope": narrowed["scope"],
        "hard_constraints": narrowed["hard_constraints"],
        "parameter_guidance": narrowed["parameter_guidance"],
        "operators": narrowed["operators"],
        "clusters": narrowed["clusters"],
        "paths": [path for path in narrowed["paths"] if path["input_kind"] == input_kind],
    }


def _candidate_fields(context: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for card in context.get("hypothesis_cards", []):
        if not isinstance(card, dict):
            continue
        for field in card.get("field_candidates", []):
            if isinstance(field, dict) and field.get("name"):
                names.add(str(field["name"]).lower())
    return names


def _discovery_system() -> str:
    return """Bạn là tác nhân khám phá giả thuyết alpha định lượng. Bạn không được tạo biểu thức alpha ở bước này.
Mỗi giả thuyết phải khác cơ chế của các họ đã thử, dùng đúng tên trường được cấp, có thể bác bỏ,
và chỉ chọn một cơ chế kinh tế. Không bịa trường, toán tử, số liệu hay kết quả mô phỏng.
Trả về duy nhất JSON có khóa hypotheses. Mỗi phần tử gồm family, statement, mechanism,
expected_direction, horizon, data_themes, field_names, operator_roles, falsifier, novelty.
family dùng snake_case; field_names có 1 hoặc 2 tên trường chính xác; operator_roles chỉ mô tả vai trò,
không viết tên biểu thức hay công thức."""


def _validate_card(
    item: Any,
    *,
    allowed_fields: set[str],
    existing_families: set[str],
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(item, dict):
        return None, "card_not_object"
    family = str(item.get("family") or "").strip().lower()
    if not _FAMILY_RE.fullmatch(family):
        return None, "invalid_family"
    if family in existing_families:
        return None, "existing_family"
    text_keys = ("statement", "mechanism", "expected_direction", "horizon", "falsifier", "novelty")
    values = {key: " ".join(str(item.get(key) or "").split()) for key in text_keys}
    if any(not value for value in values.values()):
        return None, "missing_card_content"
    fields = [str(value).strip().lower() for value in item.get("field_names", []) if str(value).strip()]
    fields = list(dict.fromkeys(fields))
    if not 1 <= len(fields) <= 2 or any(field not in allowed_fields for field in fields):
        return None, "field_outside_research_packet"
    themes = [str(value).strip().lower() for value in item.get("data_themes", []) if str(value).strip()]
    roles = [str(value).strip().lower() for value in item.get("operator_roles", []) if str(value).strip()]
    if not themes or not roles or any(role not in _ALLOWED_ROLES for role in roles):
        return None, "invalid_roles_or_themes"
    if "expression" in item or "formula" in item:
        return None, "expression_not_allowed_in_discovery"
    return {
        "family": family,
        **values,
        "field_names": fields,
        "data_themes": list(dict.fromkeys(themes))[:4],
        "operator_roles": list(dict.fromkeys(roles))[:5],
    }, None


def discover(
    connection: sqlite3.Connection,
    count: int = 4,
    *,
    settings: Settings | None = None,
    provider: CompletionProvider | None = None,
) -> dict[str, Any]:
    """Gọi Gemini để tạo thẻ giả thuyết, chưa tạo biểu thức hay mô phỏng."""
    settings = _gemini_settings(settings or Settings.from_env())
    context = build_discovery_context(connection, limit=max(2, count), max_chars=12000)
    operators = _operator_rows(connection)
    user_context = {
        **context,
        "operator_graph": _discovery_graph(operators),
        "allowed_operator_roles": sorted(_ALLOWED_ROLES),
        "requested_hypotheses": count,
    }
    system = _discovery_system()
    user = json_dumps(user_context)
    answer = (provider or provider_for(settings)).complete(system, user)
    evidence, prompt_hash = _write_exchange(settings, "discovery", system, user, answer)
    data = _parse_object(answer)
    raw_cards = data.get("hypotheses")
    if not isinstance(raw_cards, list):
        raise ValueError("Gemini không trả về danh sách hypotheses.")
    allowed_fields = _candidate_fields(context)
    existing_families = {
        str(row[0]).lower() for row in connection.execute("SELECT family FROM hypotheses").fetchall()
    }
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for item in raw_cards[: max(1, count * 2)]:
        card, reason = _validate_card(item, allowed_fields=allowed_fields, existing_families=existing_families)
        if card is None:
            rejected.append({"reason": str(reason)})
            continue
        hypothesis_id = str(uuid.uuid4())
        card_id = str(uuid.uuid4())
        connection.execute(
            "INSERT INTO hypotheses VALUES(?,?,?,?,?,?,?)",
            (hypothesis_id, card["family"], card["statement"], card["mechanism"], card["expected_direction"],
             "gemini_hypothesis_agent", utc_now()),
        )
        connection.execute(
            """INSERT INTO hypothesis_cards VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (card_id, hypothesis_id, card["family"], card["statement"], card["mechanism"],
             card["expected_direction"], card["horizon"], json_dumps(card["data_themes"]),
             json_dumps(card["field_names"]), json_dumps(card["operator_roles"]), card["falsifier"],
             json_dumps({"statement": card["novelty"]}), "discovered", settings.llm_provider,
             _model_name(settings), prompt_hash, str(evidence), utc_now()),
        )
        connection.execute(
            "INSERT INTO research_events(artifact_id,event_type,payload_json,created_at) VALUES(NULL,?,?,?)",
            ("agent_hypothesis_card", json_dumps({"card_id": card_id, **card}), utc_now()),
        )
        existing_families.add(card["family"])
        accepted.append({"card_id": card_id, "family": card["family"], "field_names": card["field_names"]})
        if len(accepted) >= count:
            break
    return {"evidence_path": str(evidence), "accepted": accepted, "rejected": rejected,
            "source_count": len(raw_cards), "prompt_hash": prompt_hash}


def _design_system() -> str:
    return """Bạn là tác nhân thiết kế thí nghiệm alpha. Chỉ tạo biểu thức FASTEXPR hợp lệ từ đúng
tên trường, toán tử và đường đi cấu trúc đã cấp. Mỗi biểu thức là thí nghiệm chẩn đoán nhỏ cho một
giả thuyết, không phải biến thể tham số của alpha cũ. Dùng tối đa hai trường, một cơ chế thời gian chính,
và không xếp chồng toán tử cùng cụm thay thế. Không nêu hay bịa kết quả mô phỏng.
Trả về duy nhất JSON có khóa proposals; mỗi phần tử gồm expression, rationale, design_note.
Không tự đặt family hay dùng trường ngoài thẻ giả thuyết."""


def _critic_system() -> str:
    return """Bạn là phản biện độc lập cho thiết kế alpha. Không sửa công thức, không tạo công thức mới.
Kiểm tra từng đề xuất theo giả thuyết, đường đi toán tử, nguy cơ clone và khả năng bác bỏ.
Trả về duy nhất JSON: {\"decisions\":[{\"index\":0,\"verdict\":\"accept\" hoặc \"reject\",\"reasons\":[\"...\"]}]}.
Chỉ accept khi biểu thức thật sự là thí nghiệm tối giản và đúng cơ chế."""


def _card_payload(row: sqlite3.Row, field_index: dict[str, sqlite3.Row], operators: list[sqlite3.Row]) -> dict[str, Any]:
    fields = json.loads(row["field_names_json"])
    selected = []
    for name in fields:
        field = field_index.get(str(name).lower())
        if field is not None:
            selected.append({
                "name": field["name"], "dataset": field["dataset_name"], "description": field["description"],
                "data_type": field["data_type"], "coverage": field["coverage"],
            })
    kinds = {str(item.get("data_type") or "MATRIX").upper() for item in selected}
    supported_kinds = sorted(kind for kind in kinds if kind in {"MATRIX", "VECTOR"}) or ["MATRIX"]
    if len(supported_kinds) == 1:
        graph: dict[str, Any] = _design_graph(operators, supported_kinds[0])
    else:
        graph = {
            "by_input_kind": {kind: _design_graph(operators, kind) for kind in supported_kinds},
            "mixed_field_rule": (
                "Không ghép trực tiếp MATRIX với VECTOR. Nếu chọn trường VECTOR, "
                "phải dùng đường đi VECTOR và vec_avg hoặc vec_sum trước mọi phép khác."
            ),
        }
    return {
        "card_id": row["id"], "family": row["family"], "statement": row["statement"],
        "mechanism": row["mechanism"], "expected_direction": row["expected_direction"],
        "horizon": row["horizon"], "field_names": fields,
        "operator_roles": json.loads(row["operator_roles_json"]), "falsifier": row["falsifier"],
        "fields": selected, "operator_graph": graph,
    }


def _critic_decisions(answer: str, count: int) -> dict[int, dict[str, Any]]:
    data = _parse_object(answer)
    decisions = data.get("decisions")
    if not isinstance(decisions, list):
        raise ValueError("Gemini phản biện không trả về decisions.")
    result: dict[int, dict[str, Any]] = {}
    for item in decisions:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        if not isinstance(index, int) or not 0 <= index < count:
            continue
        verdict = str(item.get("verdict") or "").lower()
        if verdict not in {"accept", "reject"}:
            continue
        reasons = [str(reason) for reason in item.get("reasons", []) if str(reason).strip()][:4]
        result[index] = {"verdict": verdict, "reasons": reasons}
    return result


def design(
    connection: sqlite3.Connection,
    limit: int = 4,
    *,
    per_card: int = 2,
    settings: Settings | None = None,
    provider: CompletionProvider | None = None,
) -> dict[str, Any]:
    """Thiết kế và phản biện alpha từ thẻ đã lưu; không mô phỏng."""
    settings = _gemini_settings(settings or Settings.from_env())
    if limit <= 0 or per_card <= 0:
        return {"cards": [], "accepted": 0, "rejected": 0}
    rows = connection.execute(
        "SELECT * FROM hypothesis_cards WHERE status='discovered' ORDER BY created_at LIMIT ?", (limit,)
    ).fetchall()
    catalog_rows, field_index = _catalog_rows(connection)
    operators = _operator_rows(connection)
    field_types = catalog_field_types(catalog_rows)
    model = provider or provider_for(settings)
    card_results: list[dict[str, Any]] = []
    total_accepted = total_rejected = 0
    for row in rows:
        card = _card_payload(row, field_index, operators)
        system = _design_system()
        user = json_dumps({"version": AGENT_VERSION, "requested_proposals": per_card, "hypothesis_card": card})
        answer = model.complete(system, user)
        design_evidence, design_hash = _write_exchange(settings, "design", system, user, answer)
        payload = _parse_object(answer)
        proposals = payload.get("proposals")
        if not isinstance(proposals, list):
            raise ValueError("Gemini thiết kế không trả về proposals.")
        proposals = [item for item in proposals if isinstance(item, dict)][:per_card]
        critic_system = _critic_system()
        critic_user = json_dumps({"hypothesis_card": card, "proposals": [
            {"index": index, "expression": item.get("expression"), "rationale": item.get("rationale")}
            for index, item in enumerate(proposals)
        ]})
        critic_answer = model.complete(critic_system, critic_user)
        critic_evidence, critic_hash = _write_exchange(settings, "critic", critic_system, critic_user, critic_answer)
        decisions = _critic_decisions(critic_answer, len(proposals))
        accepted_here: list[str] = []
        rejected_here: list[dict[str, Any]] = []
        allowed_fields = {str(name).lower() for name in card["field_names"]}
        for index, proposal in enumerate(proposals):
            decision = decisions.get(index, {"verdict": "reject", "reasons": ["Thiếu phản biện hợp lệ."]})
            expression = str(proposal.get("expression") or "").strip()
            if decision["verdict"] != "accept":
                rejected_here.append({"index": index, "reason": "critic_reject", "details": decision["reasons"]})
                continue
            report = validate_expression(expression, connection)
            if not report.valid or report.fingerprint is None:
                rejected_here.append({"index": index, "reason": "local_validation", "details": report.to_dict()})
                continue
            if not set(report.fingerprint.fields).issubset(allowed_fields):
                rejected_here.append({"index": index, "reason": "field_outside_card"})
                continue
            structure = inspect_expression(expression, field_types=field_types)
            if not structure["valid_structure"]:
                rejected_here.append({"index": index, "reason": "operator_graph", "details": structure["issues"]})
                continue
            if any(issue["code"] == "repeated_alternative_cluster" for issue in structure["issues"]):
                rejected_here.append({"index": index, "reason": "redundant_operator_cluster", "details": structure["issues"]})
                continue
            rationale = " ".join(str(proposal.get("rationale") or "").split())
            rationale = (rationale + " " if rationale else "") + f"Thẻ giả thuyết {row['id']}; phản biện độc lập đã chấp nhận."
            result: IngestResult = ingest_candidate(
                connection, expression=expression, family=row["family"], rationale=rationale,
                generator="gemini_agent_designer", model_name=_model_name(settings), prompt_hash=design_hash,
                prompt_version=AGENT_VERSION, hypothesis_id=row["hypothesis_id"],
                mutation=f"agentic:card:{row['id']}",
            )
            if result.accepted and result.artifact_id:
                accepted_here.append(result.artifact_id)
            else:
                rejected_here.append({"index": index, "reason": result.reason, "similarity": result.similarity})
        status = "designed" if accepted_here else "design_rejected"
        connection.execute("UPDATE hypothesis_cards SET status=? WHERE id=?", (status, row["id"]))
        connection.execute(
            "INSERT INTO research_events(artifact_id,event_type,payload_json,created_at) VALUES(NULL,?,?,?)",
            ("agent_design_result", json_dumps({"card_id": row["id"], "design_evidence": str(design_evidence),
                                                 "critic_evidence": str(critic_evidence), "design_hash": design_hash,
                                                 "critic_hash": critic_hash, "accepted": accepted_here,
                                                 "rejected": rejected_here}), utc_now()),
        )
        total_accepted += len(accepted_here)
        total_rejected += len(rejected_here)
        card_results.append({"card_id": row["id"], "family": row["family"], "accepted": accepted_here,
                             "rejected": rejected_here, "design_evidence": str(design_evidence),
                             "critic_evidence": str(critic_evidence)})
    return {"cards": card_results, "accepted": total_accepted, "rejected": total_rejected}


def packet(connection: sqlite3.Connection, count: int = 4) -> dict[str, Any]:
    """Xuất gói không gọi mạng để kiểm tra trước khi dùng Gemini."""
    return {
        "version": AGENT_VERSION,
        "discovery_context": build_discovery_context(connection, limit=max(2, count), max_chars=12000),
        "operator_graph": _discovery_graph(_operator_rows(connection)),
    }


def run_cycle(
    connection: sqlite3.Connection,
    count: int = 4,
    *,
    per_card: int = 2,
    settings: Settings | None = None,
    provider: CompletionProvider | None = None,
) -> dict[str, Any]:
    """Chạy một vòng không mô phỏng: khám phá, thiết kế, phản biện và nạp cục bộ."""
    discovered = discover(connection, count, settings=settings, provider=provider)
    designed = design(connection, count, per_card=per_card, settings=settings, provider=provider)
    return {"discovery": discovered, "design": designed, "simulated": 0}
