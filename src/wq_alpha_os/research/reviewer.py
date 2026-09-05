from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from ..config import load_defaults
from ..db import json_dumps, utc_now
from ..brain.simulation import _records, settings_hash
from .scorer import check_summary, promotable, research_utility, score_vector


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


def _annual_stability(payload: Any, minimum_years: int = 3) -> tuple[dict[str, Any], list[str]]:
    """Summarize yearly evidence and flag fragile performance."""
    rows = _records(payload)
    if not rows:
        return {}, ["Chưa đọc được dữ liệu kết quả theo năm."]
    if not any(key in rows[0] for key in ("year", "pnl", "sharpe")):
        return {}, []
    is_rows = [row for row in rows if str(row.get("stage") or "IS").upper() == "IS"]
    if not is_rows:
        is_rows = rows
    warnings: list[str] = []
    if len(is_rows) < minimum_years:
        warnings.append(f"Chỉ có {len(is_rows)} năm dữ liệu; cần ít nhất {minimum_years} năm.")
    pnl_values = []
    sharpe_values = []
    for row in is_rows:
        try:
            if row.get("pnl") is not None:
                pnl_values.append(float(row["pnl"]))
        except (TypeError, ValueError):
            pass
        try:
            if row.get("sharpe") is not None:
                sharpe_values.append(float(row["sharpe"]))
        except (TypeError, ValueError):
            pass
    negative_pnl_years = sum(value < 0 for value in pnl_values)
    negative_sharpe_years = sum(value < 0 for value in sharpe_values)
    if negative_pnl_years > 0:
        warnings.append(f"Có {negative_pnl_years} năm âm PnL (lãi/lỗ tích lũy).")
    if negative_sharpe_years > 0:
        warnings.append(f"Có {negative_sharpe_years} năm âm chỉ số Sharpe (hiệu quả đã điều chỉnh rủi ro).")
    summary = {
        "years": len(is_rows),
        "negative_pnl_years": negative_pnl_years,
        "negative_sharpe_years": negative_sharpe_years,
        "min_sharpe": min(sharpe_values) if sharpe_values else None,
        "mean_sharpe": round(sum(sharpe_values) / len(sharpe_values), 4) if sharpe_values else None,
    }
    return summary, warnings


def review_pending(connection: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    rows = connection.execute(
        """SELECT a.id artifact_id,a.family,a.expression,a.complexity_nodes,a.complexity_depth,
                  coalesce(m.novelty_score,0.5) novelty_score,
                  coalesce(t.effective_trial_count,0) effective_trial_count,r.*
           FROM alpha_artifacts a
           JOIN simulation_runs r ON r.artifact_id=a.id
           LEFT JOIN artifact_motifs m ON m.artifact_id=a.id
           LEFT JOIN family_trial_stats t ON t.family=a.family
           WHERE r.platform_status='COMPLETE' AND NOT EXISTS(
             SELECT 1 FROM reviews v WHERE v.simulation_run_id=r.id)
           ORDER BY r.finished_at DESC LIMIT ?""", (limit,),
    ).fetchall()
    reports = []
    limits = load_defaults()["research"]
    for row in rows:
        metrics = {"sharpe": row["sharpe"], "fitness": row["fitness"], "turnover": row["turnover"],
                   "returns": row["returns_value"], "drawdown": row["drawdown"], "margin": row["margin"],
                   "subuniverseSharpe": row["subuniverse_sharpe"], "selfCorrelation": row["self_correlation"]}
        checks = json.loads(row["checks_json"] or "[]")
        _, failed, failures = check_summary(checks)
        evidence_errors = _verify_evidence(row)
        warnings = list(evidence_errors)
        if not checks:
            warnings.append("Chưa có danh sách kiểm tra của BRAIN.")
        if row["self_correlation"] is None:
            warnings.append("Chưa có bằng chứng về tương quan tự thân.")
        annual_payload = json.loads(row["annual_json"] or "[]")
        if not annual_payload:
            warnings.append("Chưa có chuỗi kết quả theo năm để đánh giá độ ổn định.")
            annual_summary = {}
        else:
            annual_summary, annual_warnings = _annual_stability(
                annual_payload, int(limits.get("minimum_annual_years", 3))
            )
            warnings.extend(annual_warnings)
        if failed:
            warnings.append("Kiểm tra thất bại: " + ", ".join(failures))
        evidence_valid = not evidence_errors
        objective_vector = score_vector(
            metrics, checks, annual_summary=annual_summary,
            complexity_nodes=row["complexity_nodes"], complexity_depth=row["complexity_depth"],
            novelty_score=row["novelty_score"], effective_trial_count=row["effective_trial_count"],
        )
        utility = research_utility(objective_vector)
        verdict = "promote" if promotable(metrics, checks, limits) and not warnings else "hold"
        report = {"verdict": verdict, "metrics": metrics, "failed_checks": failures,
                  "annual_stability": annual_summary, "objective_vector": objective_vector,
                  "research_utility": utility, "warnings": warnings,
                  "evidence_path": row["response_path"]}
        connection.execute(
            "INSERT INTO reviews VALUES(?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), row["artifact_id"], row["id"], "deterministic_reviewer_v2", verdict,
             int(evidence_valid), json_dumps(warnings), json_dumps(report), utc_now()),
        )
        if verdict == "promote":
            connection.execute("UPDATE alpha_artifacts SET status='promoted' WHERE id=?", (row["artifact_id"],))
        reports.append(report)
    return reports
