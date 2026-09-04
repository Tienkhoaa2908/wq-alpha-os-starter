from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from ..config import load_defaults
from ..db import json_dumps, utc_now
from ..brain.simulation import settings_hash
from .scorer import check_summary, promotable


def _verify_evidence(row: sqlite3.Row) -> list[str]:
    errors: list[str] = []
    request_path = Path(row["request_path"] or "")
    response_path = Path(row["response_path"] or "")
    if not request_path.is_file():
        errors.append("Thiếu tệp yêu cầu mô phỏng.")
    if not response_path.is_file():
        errors.append("Thiếu tệp phản hồi mô phỏng.")
    if errors:
        return errors
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        response = json.loads(response_path.read_text(encoding="utf-8"))
        stored_settings = json.loads(row["settings_json"])
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        return [f"Không đọc được bằng chứng: {exc}"]
    if request.get("regular") != row["expression"]:
        errors.append("Biểu thức trong bằng chứng không khớp hiện vật.")
    if request.get("settings") != stored_settings or settings_hash(stored_settings) != row["settings_hash"]:
        errors.append("Thiết lập trong bằng chứng không khớp chỉ mục.")
    if not isinstance(response.get("alpha"), dict):
        errors.append("Phản hồi không có chi tiết alpha.")
    return errors


def review_pending(connection: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    rows = connection.execute(
        """SELECT a.id artifact_id,a.family,a.expression,r.* FROM alpha_artifacts a
           JOIN simulation_runs r ON r.artifact_id=a.id
           WHERE r.platform_status='COMPLETE' AND NOT EXISTS(
             SELECT 1 FROM reviews v WHERE v.simulation_run_id=r.id)
           ORDER BY r.finished_at DESC LIMIT ?""", (limit,),
    ).fetchall()
    reports = []
    limits = load_defaults()["research"]
    for row in rows:
        metrics = {"sharpe": row["sharpe"], "fitness": row["fitness"], "turnover": row["turnover"],
                   "returns": row["returns_value"], "drawdown": row["drawdown"], "margin": row["margin"],
                   "selfCorrelation": row["self_correlation"]}
        checks = json.loads(row["checks_json"] or "[]")
        _, failed, failures = check_summary(checks)
        evidence_errors = _verify_evidence(row)
        warnings = list(evidence_errors)
        if not checks:
            warnings.append("Chưa có danh sách kiểm tra của BRAIN.")
        if row["self_correlation"] is None:
            warnings.append("Chưa có bằng chứng về tương quan tự thân.")
        if not json.loads(row["annual_json"] or "[]"):
            warnings.append("Chưa có chuỗi kết quả theo năm để đánh giá độ ổn định.")
        if failed:
            warnings.append("Kiểm tra thất bại: " + ", ".join(failures))
        evidence_valid = not evidence_errors
        verdict = "promote" if promotable(metrics, checks, limits) and not warnings else "hold"
        report = {"verdict": verdict, "metrics": metrics, "failed_checks": failures,
                  "warnings": warnings, "evidence_path": row["response_path"]}
        connection.execute(
            "INSERT INTO reviews VALUES(?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), row["artifact_id"], row["id"], "deterministic_reviewer_v1", verdict,
             int(evidence_valid), json_dumps(warnings), json_dumps(report), utc_now()),
        )
        if verdict == "promote":
            connection.execute("UPDATE alpha_artifacts SET status='promoted' WHERE id=?", (row["artifact_id"],))
        reports.append(report)
    return reports
