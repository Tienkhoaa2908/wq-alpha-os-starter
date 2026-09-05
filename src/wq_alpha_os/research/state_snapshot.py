from __future__ import annotations

"""Sanitized, source-controlled snapshot of the local research state.

The SQLite database and raw evidence remain local. This module exports only the
small coordination state that another agent can safely read from GitHub.
"""

from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
import subprocess
from typing import Any

from ..config import PROJECT_ROOT, simulation_settings
from ..operator_registry import active_brain_operator_count


LEGACY_STATUS = "legacy_unverified"


def _git_value(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True,
            check=True, timeout=5,
        )
        value = result.stdout.strip()
        return value or None
    except (OSError, subprocess.SubprocessError):
        return None


def _annual_summary(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {"years": 0, "positive_sharpe_years": 0, "min_sharpe": None}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return {"years": 0, "positive_sharpe_years": 0, "min_sharpe": None}
    rows: list[dict[str, Any]] = []
    if isinstance(payload, list):
        rows = [item for item in payload if isinstance(item, dict)]
    elif isinstance(payload, dict):
        raw_rows = payload.get("value") or payload.get("records") or payload.get("results") or payload.get("data")
        if isinstance(raw_rows, list):
            for item in raw_rows:
                if isinstance(item, dict) and isinstance(item.get("value"), dict):
                    rows.append(item["value"])
                elif isinstance(item, dict):
                    rows.append(item)
    values: list[float] = []
    for row in rows:
        if str(row.get("stage") or "IS").upper() != "IS":
            continue
        try:
            values.append(float(row.get("sharpe")))
        except (TypeError, ValueError):
            pass
    return {
        "years": len(values),
        "positive_sharpe_years": sum(value > 0 for value in values),
        "min_sharpe": min(values) if values else None,
    }


def build_state(connection: sqlite3.Connection) -> dict[str, Any]:
    artifact_statuses = {
        str(row[0]): int(row[1])
        for row in connection.execute("SELECT status,count(*) FROM alpha_artifacts GROUP BY status")
    }
    run_statuses = {
        str(row[0]): int(row[1])
        for row in connection.execute("SELECT platform_status,count(*) FROM simulation_runs GROUP BY platform_status")
    }
    best = connection.execute(
        """SELECT a.id,a.family,a.expression,a.status,r.sharpe,r.fitness,r.turnover,r.self_correlation,
                  r.annual_json,r.platform_alpha_id,r.finished_at
           FROM simulation_runs r JOIN alpha_artifacts a ON a.id=r.artifact_id
           WHERE r.platform_status='COMPLETE'
           ORDER BY coalesce(r.sharpe,-999) DESC,coalesce(r.fitness,-999) DESC LIMIT 1"""
    ).fetchone()
    best_alpha: dict[str, Any] | None = None
    if best is not None:
        best_alpha = {
            "artifact_id": best["id"],
            "family": best["family"],
            "expression": best["expression"],
            "status": best["status"],
            "sharpe": best["sharpe"],
            "fitness": best["fitness"],
            "turnover": best["turnover"],
            "self_correlation": best["self_correlation"],
            "annual": _annual_summary(best["annual_json"]),
            "platform_alpha_id": best["platform_alpha_id"],
            "finished_at": best["finished_at"],
        }

    families = [dict(row) for row in connection.execute(
        """SELECT f.family,f.completed_runs,f.best_reward,
                  coalesce(t.effective_trial_count,0) effective_trial_count,
                  coalesce(t.semantic_branches,0) semantic_branches,
                  coalesce(t.parameter_only_trials,0) parameter_only_trials,
                  coalesce(t.stopped,0) stopped,t.stop_reason
           FROM family_stats f LEFT JOIN family_trial_stats t ON t.family=f.family
           ORDER BY f.completed_runs DESC,f.family"""
    )]

    total_artifacts = int(connection.execute("SELECT count(*) FROM alpha_artifacts").fetchone()[0])
    legacy_artifacts = int(connection.execute(
        "SELECT count(*) FROM alpha_artifacts WHERE status=?", (LEGACY_STATUS,)
    ).fetchone()[0])
    eligible_artifacts = total_artifacts - legacy_artifacts
    settings = simulation_settings()
    return {
        "snapshot": {
            "generated_at": datetime.now(UTC).isoformat(),
            "git_branch": _git_value("rev-parse", "--abbrev-ref", "HEAD"),
            "git_commit": _git_value("rev-parse", "HEAD"),
            "source": "local SQLite sanitized snapshot",
        },
        "configuration": settings,
        "catalog": {
            "datasets": int(connection.execute("SELECT count(*) FROM datasets").fetchone()[0]),
            "fields": int(connection.execute("SELECT count(*) FROM fields").fetchone()[0]),
            "active_brain_operators": active_brain_operator_count(connection),
            "operator_profiles": int(connection.execute("SELECT count(*) FROM operator_profiles WHERE active=1").fetchone()[0]),
            "field_profiles": int(connection.execute("SELECT count(*) FROM field_profiles").fetchone()[0]),
            "path_templates": int(connection.execute("SELECT count(*) FROM path_template_registry").fetchone()[0]),
        },
        "research": {
            "hypotheses": int(connection.execute("SELECT count(*) FROM hypotheses").fetchone()[0]),
            "hypothesis_cards": int(connection.execute("SELECT count(*) FROM hypothesis_cards").fetchone()[0]),
            "alpha_plans": int(connection.execute("SELECT count(*) FROM alpha_plans").fetchone()[0]),
            "artifacts_total": total_artifacts,
            "artifacts_research_eligible": eligible_artifacts,
            "legacy_unverified_quarantined": legacy_artifacts,
            "artifact_statuses": artifact_statuses,
            "motifs_active": int(connection.execute("SELECT count(*) FROM artifact_motifs").fetchone()[0]),
            "motif_contexts": int(connection.execute("SELECT count(*) FROM motif_stats").fetchone()[0]),
            "legacy_policy": "retain for provenance; exclude from v2 novelty, subtree and empirical memory",
        },
        "simulations": {
            "total": int(connection.execute("SELECT count(*) FROM simulation_runs").fetchone()[0]),
            "statuses": run_statuses,
        },
        "best_alpha": best_alpha,
        "families": families,
        "coordination": {
            "source_of_truth": [
                "00_TONG_QUAN_DU_AN.md",
                "docs/TRANG_THAI_HIEN_TAI.md",
                "docs/generated/research_state.json",
            ],
            "next_gate": "audit field semantics and v2 agent packet before spending new BRAIN simulations",
        },
    }


def _markdown(state: dict[str, Any]) -> str:
    snapshot = state["snapshot"]
    catalog = state["catalog"]
    research = state["research"]
    simulations = state["simulations"]
    best = state.get("best_alpha")
    lines = [
        "# Trạng thái hiện tại",
        "",
        "> Tệp này được tạo bởi `alpha-os snapshot`. Không chỉnh số liệu thủ công; hãy cập nhật từ SQLite rồi commit/push.",
        "",
        f"- Thời điểm: `{snapshot.get('generated_at')}`",
        f"- Branch: `{snapshot.get('git_branch')}`",
        f"- Commit: `{snapshot.get('git_commit')}`",
        "",
        "## Danh mục và tri thức",
        "",
        f"- Dataset: **{catalog['datasets']}**",
        f"- Field: **{catalog['fields']}**; đã lập hồ sơ: **{catalog['field_profiles']}**",
        f"- BRAIN operator active: **{catalog['active_brain_operators']}**; đã lập hồ sơ: **{catalog['operator_profiles']}**",
        f"- Path template: **{catalog['path_templates']}**",
        "",
        "## Kho nghiên cứu",
        "",
        f"- Alpha artifact vật lý: **{research['artifacts_total']}**",
        f"- Artifact đủ điều kiện tham gia nghiên cứu v2: **{research['artifacts_research_eligible']}**",
        f"- Legacy Gemini bị cách ly: **{research['legacy_unverified_quarantined']}**",
        f"- Motif đang hoạt động: **{research['motifs_active']}**; empirical context: **{research['motif_contexts']}**",
        f"- Hypothesis card: **{research['hypothesis_cards']}**; AlphaPlan: **{research['alpha_plans']}**",
        "",
        "Legacy policy: giữ lại record cũ để truy vết, nhưng không cho chúng ảnh hưởng novelty, subtree frequency hay empirical memory của v2.",
        "",
        "## Mô phỏng",
        "",
        f"- Tổng: **{simulations['total']}**",
        f"- Trạng thái: `{json.dumps(simulations['statuses'], ensure_ascii=False, sort_keys=True)}`",
    ]
    if best:
        lines += [
            "",
            "## Alpha tốt nhất theo Sharpe hiện có",
            "",
            f"- Family: `{best['family']}`",
            f"- Sharpe: **{best['sharpe']}**; Fitness: **{best['fitness']}**; Turnover: **{best['turnover']}**",
            f"- Self-correlation: **{best['self_correlation']}**",
            f"- Annual: `{json.dumps(best['annual'], ensure_ascii=False, sort_keys=True)}`",
            "",
            "```text",
            str(best["expression"]),
            "```",
        ]
    lines += [
        "",
        "## Cổng tiếp theo",
        "",
        "Audit chất lượng phân loại field và packet tác tử v2 trước khi tiêu thêm lượt mô phỏng BRAIN.",
        "",
        "Nguồn chi tiết máy đọc được: `docs/generated/research_state.json`.",
        "",
    ]
    return "\n".join(lines)


def write_snapshot(
    connection: sqlite3.Connection,
    *,
    json_path: Path | None = None,
    markdown_path: Path | None = None,
) -> dict[str, Any]:
    json_path = json_path or PROJECT_ROOT / "docs" / "generated" / "research_state.json"
    markdown_path = markdown_path or PROJECT_ROOT / "docs" / "TRANG_THAI_HIEN_TAI.md"
    state = build_state(connection)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    markdown_path.write_text(_markdown(state), encoding="utf-8")
    return {
        "json": str(json_path),
        "markdown": str(markdown_path),
        "legacy_quarantined": state["research"]["legacy_unverified_quarantined"],
        "research_eligible_artifacts": state["research"]["artifacts_research_eligible"],
    }


__all__ = ["build_state", "write_snapshot"]
