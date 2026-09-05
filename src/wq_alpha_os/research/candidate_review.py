from __future__ import annotations

"""Bounded Gemini adjudication for the discovery packet.

This stage reviews only the small, already-gated candidate packet. It never
creates alpha expressions and never receives PnL or simulation metrics.
"""

from collections import Counter
import json
import sqlite3
from typing import Any

from ..config import Settings
from ..db import json_dumps, utc_now
from ..providers import CompletionProvider, provider_for
from .agentic_v2 import _gemini_settings, _parse_object, _write_exchange
from .discovery_v2 import build_discovery_context
from .field_profiles import HORIZONS, _roles
from .field_review import CADENCES, DIRECTIONS, FORMS, SIGNEDNESS, THEMES, UNIT_FAMILIES


REVIEW_VERSION = "gemini_candidate_review_v3"
VERDICTS = {"accept", "correct", "reject_for_discovery"}
FORBIDDEN_KEYS = {"expression", "formula", "operator", "operators", "operator_name"}


def _system() -> str:
    return """Bạn kiểm định ngữ nghĩa của một tập field WorldQuant BRAIN đã được chọn sẵn cho nghiên cứu.
Không tạo alpha, không viết FASTEXPR, không nêu tên toán tử, không dự đoán Sharpe/Fitness và không dùng
kiến thức ngoài tên/mô tả/dataset/type được cấp để bịa ý nghĩa.

Với từng field, trả đúng một review:
- verdict: accept | correct | reject_for_discovery
- economic_theme
- secondary_themes
- semantic_form
- update_cadence
- signedness
- unit_family
- direction_prior
- confidence
- reason

Quy tắc:
- accept khi profile hiện tại phù hợp với mô tả;
- correct khi mô tả cho thấy profile hiện tại sai;
- reject_for_discovery khi mô tả không đủ để dùng an toàn trong vòng khám phá;
- direction_prior mặc định ambiguous nếu không có căn cứ trực tiếp;
- confidence trong [0,1], không được giả vờ chắc chắn;
- reason phải bám tên/mô tả.

Trả duy nhất JSON {"reviews":[...]} ."""


def _short(value: Any, limit: int = 260) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _packet_payload(connection: sqlite3.Connection, fields: list[dict[str, Any]]) -> dict[str, Any]:
    result = []
    for item in fields:
        row = connection.execute(
            """SELECT fp.field_key,fp.name,fp.dataset_name,fp.data_type,fp.economic_theme,
                      fp.secondary_themes_json,fp.semantic_form,fp.update_cadence,fp.signedness,
                      fp.unit_family,fp.direction_prior,fp.confidence,f.description,f.coverage
               FROM field_profiles fp JOIN fields f ON f.field_key=fp.field_key
               WHERE lower(fp.name)=lower(?) LIMIT 1""",
            (item["name"],),
        ).fetchone()
        if row is None:
            continue
        result.append({
            "name": row["name"],
            "description": _short(row["description"]),
            "dataset": row["dataset_name"],
            "data_type": row["data_type"],
            "current": {
                "economic_theme": row["economic_theme"],
                "secondary_themes": json.loads(row["secondary_themes_json"] or "[]"),
                "semantic_form": row["semantic_form"],
                "update_cadence": row["update_cadence"],
                "signedness": row["signedness"],
                "unit_family": row["unit_family"],
                "direction_prior": row["direction_prior"],
                "confidence": row["confidence"],
            },
            "coverage": row["coverage"],
        })
    return {
        "version": REVIEW_VERSION,
        "allowed": {
            "economic_theme": sorted(THEMES),
            "semantic_form": sorted(FORMS),
            "update_cadence": sorted(CADENCES),
            "signedness": sorted(SIGNEDNESS),
            "unit_family": sorted(UNIT_FAMILIES),
            "direction_prior": sorted(DIRECTIONS),
            "verdict": sorted(VERDICTS),
        },
        "fields": result,
    }


def _validated(item: Any, allowed_names: set[str]) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(item, dict):
        return None, "not_object"
    if FORBIDDEN_KEYS & {str(key).lower() for key in item}:
        return None, "forbidden_formula_content"
    name = str(item.get("name") or "").strip()
    if name.lower() not in allowed_names:
        return None, "field_outside_packet"
    verdict = str(item.get("verdict") or "").strip().lower()
    if verdict not in VERDICTS:
        return None, "invalid_verdict"
    if verdict == "reject_for_discovery":
        return {
            "name": name,
            "verdict": verdict,
            "reason": _short(item.get("reason"), 320),
            "confidence": 0.0,
        }, None

    theme = str(item.get("economic_theme") or "").strip().lower()
    form = str(item.get("semantic_form") or "").strip().lower()
    cadence = str(item.get("update_cadence") or "").strip().lower()
    signedness = str(item.get("signedness") or "").strip().lower()
    unit_family = str(item.get("unit_family") or "").strip().lower()
    direction = str(item.get("direction_prior") or "").strip().lower()
    secondary = [
        str(value).strip().lower()
        for value in item.get("secondary_themes", [])
        if str(value).strip().lower() in THEMES and str(value).strip().lower() != theme
    ][:3]
    try:
        confidence = float(item.get("confidence"))
    except (TypeError, ValueError):
        return None, "invalid_confidence"
    valid = (
        theme in THEMES
        and form in FORMS
        and cadence in CADENCES
        and signedness in SIGNEDNESS
        and unit_family in UNIT_FAMILIES
        and direction in DIRECTIONS
        and 0 <= confidence <= 1
    )
    if not valid:
        return None, "invalid_enum_or_confidence"
    return {
        "name": name,
        "verdict": verdict,
        "economic_theme": theme,
        "secondary_themes": list(dict.fromkeys(secondary)),
        "semantic_form": form,
        "update_cadence": cadence,
        "signedness": signedness,
        "unit_family": unit_family,
        "direction_prior": direction,
        "confidence": min(0.92, confidence),
        "reason": _short(item.get("reason"), 320),
    }, None


def _apply(connection: sqlite3.Connection, review: dict[str, Any]) -> dict[str, Any]:
    row = connection.execute(
        "SELECT * FROM field_profiles WHERE lower(name)=lower(?) LIMIT 1", (review["name"],)
    ).fetchone()
    if row is None:
        return {"name": review["name"], "status": "skipped", "reason": "profile_missing"}

    verdict = review["verdict"]
    if verdict == "reject_for_discovery":
        connection.execute(
            """UPDATE field_profiles SET classification_source=?,confidence=?,updated_at=?
               WHERE field_key=?""",
            (f"{REVIEW_VERSION}_rejected", 0.0, utc_now(), row["field_key"]),
        )
        return {"name": row["name"], "status": "rejected", "reason": review.get("reason", "")}

    if verdict == "accept":
        confidence = min(0.92, max(float(row["confidence"] or 0), float(review["confidence"])))
        connection.execute(
            """UPDATE field_profiles SET classification_source=?,confidence=?,updated_at=?
               WHERE field_key=?""",
            (REVIEW_VERSION, confidence, utc_now(), row["field_key"]),
        )
        return {"name": row["name"], "status": "accepted", "confidence": confidence}

    theme = review["economic_theme"]
    form = review["semantic_form"]
    cadence = review["update_cadence"]
    sparsity = "event_sparse" if cadence == "event" else ("slow_stepwise" if cadence == "slow" else "dense")
    peer_dependence = "high" if theme in {
        "value", "profitability", "quality", "growth", "leverage", "analyst_revision"
    } else "medium"
    preferred, discouraged = _roles(theme, form, cadence)
    direction_confidence = (
        "medium"
        if review["direction_prior"] != "ambiguous" and review["confidence"] >= 0.8
        else "low"
    )
    connection.execute(
        """UPDATE field_profiles SET
             economic_theme=?,secondary_themes_json=?,semantic_form=?,update_cadence=?,signedness=?,
             unit_family=?,sparsity_class=?,peer_dependence=?,direction_prior=?,direction_confidence=?,
             horizon_prior_json=?,preferred_roles_json=?,discouraged_roles_json=?,classification_source=?,
             confidence=?,updated_at=?
           WHERE field_key=?""",
        (
            theme,
            json_dumps(review["secondary_themes"]),
            form,
            cadence,
            review["signedness"],
            review["unit_family"],
            sparsity,
            peer_dependence,
            review["direction_prior"],
            direction_confidence,
            json_dumps(HORIZONS[cadence]),
            json_dumps(preferred),
            json_dumps(discouraged),
            REVIEW_VERSION,
            float(review["confidence"]),
            utc_now(),
            row["field_key"],
        ),
    )
    return {
        "name": row["name"],
        "status": "corrected",
        "theme": theme,
        "form": form,
        "confidence": float(review["confidence"]),
        "reason": review.get("reason", ""),
    }


def _gate(packet: dict[str, Any], reviewed_names: set[str]) -> dict[str, Any]:
    fields = list(packet.get("candidate_fields", []))
    total = len(fields)
    datasets = Counter(str(item.get("dataset") or "unknown") for item in fields)
    themes = Counter(str(item.get("theme") or "generic") for item in fields)
    names = {str(item.get("name") or "").lower() for item in fields}
    reasons: list[str] = []
    expected = int(packet.get("requested_hypotheses") or 6) * 4
    if total < expected:
        reasons.append("packet_not_refilled")
    if names - reviewed_names:
        reasons.append("unreviewed_final_candidate")
    if any(str(item.get("data_type") or "").upper() not in {"MATRIX", "VECTOR"} for item in fields):
        reasons.append("infrastructure_field_present")
    if any(str(item.get("theme") or "generic") == "generic" for item in fields):
        reasons.append("generic_field_present")
    if any(float(item.get("profile_confidence") or 0) < 0.70 for item in fields):
        reasons.append("low_confidence_field_present")
    if any(not str(item.get("description") or "").strip() for item in fields):
        reasons.append("missing_description")
    if total and len(datasets) >= 4 and max(datasets.values()) / total > 0.25:
        reasons.append("dataset_cap_exceeded")
    if total and len(themes) >= 4 and max(themes.values()) / total > 0.25:
        reasons.append("theme_cap_exceeded")
    return {
        "pass": not reasons,
        "reasons": reasons or ["all_candidate_review_gates_passed"],
        "field_count": total,
        "dataset_count": len(datasets),
        "theme_count": len(themes),
        "max_dataset_share": round(max(datasets.values(), default=0) / total, 6) if total else 0.0,
        "max_theme_share": round(max(themes.values(), default=0) / total, 6) if total else 0.0,
    }


def adjudicate_packet(
    connection: sqlite3.Connection,
    count: int = 6,
    *,
    max_rounds: int = 3,
    settings: Settings | None = None,
    provider: CompletionProvider | None = None,
) -> dict[str, Any]:
    settings = _gemini_settings(settings or Settings.from_env())
    model = provider or provider_for(settings)
    reviewed_names: set[str] = set()
    details: list[dict[str, Any]] = []
    evidence_paths: list[str] = []
    invalid: list[dict[str, Any]] = []

    for round_index in range(max(1, int(max_rounds))):
        packet = build_discovery_context(connection, count=count)
        pending = [
            item
            for item in packet.get("candidate_fields", [])
            if str(item.get("name") or "").lower() not in reviewed_names
        ]
        if not pending:
            break
        system = _system()
        user = json_dumps(_packet_payload(connection, pending))
        answer = model.complete(system, user)
        evidence, prompt_hash = _write_exchange(
            settings,
            f"candidate_semantic_review_round_{round_index + 1}",
            system,
            user,
            answer,
        )
        evidence_paths.append(str(evidence))
        payload = _parse_object(answer)
        raw_reviews = payload.get("reviews")
        if not isinstance(raw_reviews, list):
            raise ValueError("Candidate semantic reviewer returned no reviews list")
        allowed_names = {str(item["name"]).lower() for item in pending}
        returned: set[str] = set()
        for raw in raw_reviews:
            review, reason = _validated(raw, allowed_names)
            if review is None:
                invalid.append({"reason": reason})
                continue
            key = review["name"].lower()
            if key in returned:
                invalid.append({"name": review["name"], "reason": "duplicate_review"})
                continue
            returned.add(key)
            reviewed_names.add(key)
            details.append(_apply(connection, review))
        connection.execute(
            "INSERT INTO research_events(artifact_id,event_type,payload_json,created_at) VALUES(NULL,?,?,?)",
            (
                "candidate_semantic_review_v3",
                json_dumps({
                    "round": round_index + 1,
                    "prompt_hash": prompt_hash,
                    "evidence_path": str(evidence),
                    "reviewed": len(returned),
                    "invalid": len(invalid),
                }),
                utc_now(),
            ),
        )

    final_packet = build_discovery_context(connection, count=count)
    gate = _gate(final_packet, reviewed_names)
    status_counts = Counter(str(item.get("status") or "unknown") for item in details)
    return {
        "version": REVIEW_VERSION,
        "reviewed_unique": len(reviewed_names),
        "accept": status_counts["accepted"],
        "correct": status_counts["corrected"],
        "reject": status_counts["rejected"],
        "invalid": invalid,
        "details": details,
        "evidence_paths": evidence_paths,
        "final_packet": final_packet,
        "gate": gate,
    }


__all__ = ["REVIEW_VERSION", "adjudicate_packet"]
