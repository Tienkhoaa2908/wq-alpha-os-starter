from __future__ import annotations

"""Optional LLM review of ambiguous/high-value field semantics.

This is intentionally separate from deterministic materialization.  It sends
only selected field metadata, never alpha PnL, credentials or raw account
responses, and caches accepted classifications in field_profiles.
"""

import json
import sqlite3
from typing import Any

from ..config import Settings
from ..db import json_dumps, utc_now
from ..providers import CompletionProvider, provider_for
from .agentic_v2 import _gemini_settings, _parse_object, _write_exchange
from .field_profiles import HORIZONS
from .taxonomy import ECONOMIC_THEMES


THEMES = ECONOMIC_THEMES
FORMS = {
    "level", "ratio", "count", "forecast", "dispersion", "probability", "flow", "return", "volume", "price",
    "event", "score", "vector_count", "vector_score", "vector_event",
}
CADENCES = {"event", "fast", "medium", "slow"}
DIRECTIONS = {"positive", "negative", "ambiguous"}
SIGNEDNESS = {"nonnegative", "signed", "unknown"}
UNIT_FAMILIES = {
    "dimensionless_or_ratio", "currency_price", "return", "count", "volume", "currency_flow", "risk_measure", "unknown",
}


def _system() -> str:
    return """Bạn phân loại ngữ nghĩa field WorldQuant BRAIN để một bộ lập kế hoạch toán tử cục bộ sử dụng.
Không tạo alpha, không viết FASTEXPR, không nêu toán tử và không dự đoán Sharpe. Chỉ suy luận từ tên, mô tả,
dataset, kiểu dữ liệu và phân loại hiện tại. Nếu không chắc, giữ generic/unknown/ambiguous thay vì bịa.

Trả duy nhất JSON {\"reviews\":[...]}. Mỗi phần tử gồm đúng:
name, economic_theme, semantic_form, update_cadence, signedness, unit_family,
direction_prior, confidence, reason.
confidence trong [0,1]. Chỉ dùng enum được cấp trong user payload."""


def _rows(connection: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    return connection.execute(
        """SELECT fp.field_key,fp.name,fp.dataset_name,fp.data_type,fp.economic_theme,fp.semantic_form,
                  fp.update_cadence,fp.signedness,fp.unit_family,fp.direction_prior,fp.confidence,
                  f.description,f.coverage
           FROM field_profiles fp JOIN fields f ON f.field_key=fp.field_key
           WHERE fp.classification_source='deterministic_v3'
             AND upper(fp.data_type) IN ('MATRIX','VECTOR')
             AND coalesce(f.coverage,0)>=70
             AND (fp.economic_theme='generic' OR fp.confidence<0.70)
           ORDER BY coalesce(f.coverage,0) DESC,fp.confidence ASC,fp.name LIMIT ?""",
        (max(1, int(limit)),),
    ).fetchall()


def review_ambiguous_fields(
    connection: sqlite3.Connection,
    limit: int = 20,
    *,
    settings: Settings | None = None,
    provider: CompletionProvider | None = None,
) -> dict[str, Any]:
    settings = _gemini_settings(settings or Settings.from_env())
    rows = _rows(connection, limit)
    if not rows:
        return {"reviewed": 0, "accepted": 0, "rejected": 0, "reason": "no_ambiguous_fields"}
    packet = {
        "allowed": {
            "economic_theme": sorted(THEMES), "semantic_form": sorted(FORMS), "update_cadence": sorted(CADENCES),
            "signedness": sorted(SIGNEDNESS), "unit_family": sorted(UNIT_FAMILIES), "direction_prior": sorted(DIRECTIONS),
        },
        "fields": [
            {
                "name": row["name"], "dataset": row["dataset_name"], "data_type": row["data_type"],
                "description": row["description"], "coverage": row["coverage"],
                "current_theme": row["economic_theme"], "current_form": row["semantic_form"],
                "current_cadence": row["update_cadence"], "current_signedness": row["signedness"],
                "current_unit_family": row["unit_family"], "current_direction": row["direction_prior"],
            }
            for row in rows
        ],
    }
    system = _system()
    user = json_dumps(packet)
    answer = (provider or provider_for(settings)).complete(system, user)
    evidence, prompt_hash = _write_exchange(settings, "field_semantic_review", system, user, answer)
    payload = _parse_object(answer)
    reviews = payload.get("reviews")
    if not isinstance(reviews, list):
        raise ValueError("Field reviewer response has no reviews list")
    index = {str(row["name"]).lower(): row for row in rows}
    accepted = rejected = 0
    details: list[dict[str, Any]] = []
    for item in reviews:
        if not isinstance(item, dict):
            rejected += 1
            continue
        name = str(item.get("name") or "").strip()
        row = index.get(name.lower())
        if row is None:
            rejected += 1
            details.append({"name": name, "status": "rejected", "reason": "field_outside_packet"})
            continue
        theme = str(item.get("economic_theme") or "").lower()
        form = str(item.get("semantic_form") or "").lower()
        cadence = str(item.get("update_cadence") or "").lower()
        signedness = str(item.get("signedness") or "").lower()
        unit_family = str(item.get("unit_family") or "").lower()
        direction = str(item.get("direction_prior") or "").lower()
        try:
            confidence = float(item.get("confidence"))
        except (TypeError, ValueError):
            confidence = -1
        valid = (
            theme in THEMES and form in FORMS and cadence in CADENCES and signedness in SIGNEDNESS
            and unit_family in UNIT_FAMILIES and direction in DIRECTIONS and 0 <= confidence <= 1
        )
        if not valid:
            rejected += 1
            details.append({"name": name, "status": "rejected", "reason": "invalid_enum_or_confidence"})
            continue
        # LLM review never gets absolute confidence; deterministic descriptions
        # may still be ambiguous, so cap to avoid treating it as ground truth.
        confidence = min(0.92, confidence)
        connection.execute(
            """UPDATE field_profiles SET economic_theme=?,semantic_form=?,update_cadence=?,signedness=?,unit_family=?,
               direction_prior=?,direction_confidence=?,horizon_prior_json=?,classification_source=?,confidence=?,updated_at=?
               WHERE field_key=?""",
            (
                theme, form, cadence, signedness, unit_family, direction,
                "medium" if confidence >= 0.75 else "low", json_dumps(HORIZONS[cadence]),
                "gemini_semantic_review_v2", confidence, utc_now(), row["field_key"],
            ),
        )
        accepted += 1
        details.append({"name": name, "status": "accepted", "confidence": confidence, "reason": str(item.get("reason") or "")[:300]})
    connection.execute(
        "INSERT INTO research_events(artifact_id,event_type,payload_json,created_at) VALUES(NULL,?,?,?)",
        ("field_semantic_review_v2", json_dumps({"prompt_hash": prompt_hash, "evidence": str(evidence), "accepted": accepted, "rejected": rejected}), utc_now()),
    )
    return {"reviewed": len(rows), "accepted": accepted, "rejected": rejected, "evidence_path": str(evidence), "details": details}


__all__ = ["review_ambiguous_fields"]
