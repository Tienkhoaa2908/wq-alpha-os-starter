from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..config import Settings, simulation_settings
from ..db import json_dumps, utc_now
from ..research.scorer import score
from .client import BrainClient, BrainError


def payload_for(expression: str, settings: dict[str, Any]) -> dict[str, Any]:
    return {"type": "REGULAR", "settings": settings, "regular": expression}


def settings_hash(settings: dict[str, Any]) -> str:
    return hashlib.sha256(json_dumps(settings).encode()).hexdigest()


def pending(connection: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    return connection.execute(
        """SELECT a.* FROM alpha_artifacts a
           WHERE a.status='validated' AND NOT EXISTS(
             SELECT 1 FROM simulation_runs r WHERE r.artifact_id=a.id AND r.platform_status IN ('PENDING','RUNNING','COMPLETE')
           ) ORDER BY a.created_at LIMIT ?""", (limit,),
    ).fetchall()


def plan(connection: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    settings = simulation_settings()
    return [{"artifact_id": row["id"], "expression": row["expression"], "settings": settings}
            for row in pending(connection, limit)]


def _metrics(data: dict[str, Any]) -> tuple[dict[str, Any], Any, Any]:
    in_sample = data.get("is") if isinstance(data.get("is"), dict) else data
    names = ("sharpe", "fitness", "turnover", "returns", "drawdown", "margin", "subuniverseSharpe", "selfCorrelation")
    metrics = {name: in_sample.get(name) for name in names}
    checks = in_sample.get("checks") or []
    annual = in_sample.get("annual") or data.get("annual") or []
    return metrics, checks, annual


def _records(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        return []
    properties = payload.get("schema", {}).get("properties", []) if isinstance(payload.get("schema"), dict) else []
    if isinstance(properties, list):
        names = [str(item.get("name") or "") if isinstance(item, dict) else str(item) for item in properties]
    elif isinstance(properties, dict):
        names = [name for name, _ in sorted(properties.items(), key=lambda item: int(item[1].get("index", 0)) if isinstance(item[1], dict) else 0)]
    else:
        names = []
    rows: list[dict[str, Any]] = []
    for item in payload["records"]:
        # BRAIN currently wraps each row as {"value": [...], "Count": n},
        # while older responses used the bare list.  Accept both forms so
        # evidence and yearly stability checks remain reliable.
        row = item.get("value") if isinstance(item, dict) else item
        if isinstance(row, list):
            rows.append(dict(zip(names, row)))
    return rows


def _maximum_self_correlation(payload: Any) -> float | None:
    values: list[float] = []
    for row in _records(payload):
        value = row.get("correlation")
        try:
            values.append(abs(float(value)))
        except (TypeError, ValueError):
            pass
    return max(values) if values else None


def _prefer_records(current: Any, candidate: Any) -> Any:
    return candidate if len(_records(candidate)) > len(_records(current)) else current


def _historical_analytics(directory: Path) -> tuple[Any, Any, Any]:
    yearly: Any = {}
    pnl: Any = {}
    correlations: Any = {}
    for path in directory.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        yearly = _prefer_records(yearly, data.get("yearly") or {})
        pnl = _prefer_records(pnl, data.get("pnl") or {})
        correlations = _prefer_records(correlations, data.get("self_correlations") or {})
    return yearly, pnl, correlations


def run_one(connection: sqlite3.Connection, client: BrainClient, artifact: sqlite3.Row) -> dict[str, Any]:
    settings = simulation_settings()
    request_data = payload_for(artifact["expression"], settings)
    run_id = str(uuid.uuid4())
    evidence = client.new_evidence_directory(f"simulation/{run_id}")
    request_path = evidence / "request.json"
    response_path = evidence / "response.json"
    request_path.write_text(json_dumps(request_data), encoding="utf-8")
    connection.execute(
        """INSERT INTO simulation_runs(id,artifact_id,settings_json,settings_hash,request_path,response_path,
           platform_status,checks_json,annual_json,started_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (run_id, artifact["id"], json_dumps(settings), settings_hash(settings), str(request_path),
         str(response_path), "PENDING", "[]", "[]", utc_now()),
    )
    connection.execute("UPDATE alpha_artifacts SET status='simulating' WHERE id=?", (artifact["id"],))
    connection.commit()
    try:
        submitted = client.post("/simulations", request_data)
        location = next((v for k, v in submitted.headers.items() if k.lower() == "location"), "")
        if submitted.status not in {200, 201} or not location:
            raise BrainError(f"BRAIN không trả địa chỉ theo dõi mô phỏng: {submitted.data}")
        connection.execute("UPDATE simulation_runs SET platform_status='RUNNING',simulation_url=? WHERE id=?", (location, run_id))
        connection.commit()
        completed = client.poll(location)
        simulation_data = completed.data if isinstance(completed.data, dict) else {}
        platform_status = str(simulation_data.get("status") or "COMPLETE").upper()
        alpha_id = simulation_data.get("alpha") or simulation_data.get("alphaId")
        if platform_status == "COMPLETED":
            platform_status = "COMPLETE"
        if platform_status in {"ERROR", "FAILED", "CANCELLED"} or not alpha_id:
            raise BrainError(f"Mô phỏng không tạo được alpha: {simulation_data}")
        detail = client.get(f"/alphas/{alpha_id}").data if alpha_id else simulation_data
        yearly: Any = {}
        pnl: Any = {}
        correlations: Any = {}
        if alpha_id:
            try:
                check_data = client.get(f"/alphas/{alpha_id}/check").data
                if isinstance(detail, dict) and isinstance(check_data, dict):
                    detail = {**detail, "precheck": check_data}
            except BrainError as exc:
                detail = {**detail, "precheck_error": str(exc)} if isinstance(detail, dict) else detail
            try:
                yearly = client.get(f"/alphas/{alpha_id}/recordsets/yearly-stats").data
            except BrainError:
                yearly = {}
            try:
                pnl = client.get(f"/alphas/{alpha_id}/recordsets/pnl").data
            except BrainError:
                pnl = {}
            try:
                correlations = client.get(f"/alphas/{alpha_id}/correlations/self").data
            except BrainError:
                correlations = {}
        response_path.write_text(json_dumps({"submission": submitted.data, "simulation": simulation_data,
                                             "alpha": detail, "yearly": yearly, "pnl": pnl,
                                             "self_correlations": correlations}), encoding="utf-8")
        detail_dict = detail if isinstance(detail, dict) else {}
        metrics, checks, annual = _metrics(detail_dict)
        annual = yearly or annual
        measured_correlation = _maximum_self_correlation(correlations)
        if measured_correlation is not None:
            metrics["selfCorrelation"] = measured_correlation
        reward = score(metrics, checks)
        status = "tested"
        connection.execute(
            """UPDATE simulation_runs SET platform_alpha_id=?,platform_status=?,sharpe=?,fitness=?,turnover=?,
               returns_value=?,drawdown=?,margin=?,subuniverse_sharpe=?,self_correlation=?,checks_json=?,annual_json=?,
               reward=?,finished_at=? WHERE id=?""",
            (alpha_id, platform_status, metrics.get("sharpe"), metrics.get("fitness"), metrics.get("turnover"),
             metrics.get("returns"), metrics.get("drawdown"), metrics.get("margin"), metrics.get("subuniverseSharpe"),
             metrics.get("selfCorrelation"), json_dumps(checks), json_dumps(annual), reward, utc_now(), run_id),
        )
        connection.execute("UPDATE alpha_artifacts SET status=?,best_reward=max(coalesce(best_reward,-999),?) WHERE id=?",
                           (status, reward, artifact["id"]))
        connection.execute(
            """INSERT INTO family_stats VALUES(?,?,?,?,?,?) ON CONFLICT(family) DO UPDATE SET
               completed_runs=completed_runs+1,total_reward=total_reward+excluded.total_reward,
               best_reward=max(coalesce(best_reward,-999),excluded.best_reward),last_artifact_id=excluded.last_artifact_id,
               updated_at=excluded.updated_at""",
            (artifact["family"], 1, reward, reward, artifact["id"], utc_now()),
        )
        connection.commit()
        return {"run_id": run_id, "artifact_id": artifact["id"], "status": status, "reward": reward, "metrics": metrics}
    except Exception as exc:
        response_path.write_text(json_dumps({"error": str(exc)}), encoding="utf-8")
        connection.execute("UPDATE simulation_runs SET platform_status='ERROR',error_text=?,finished_at=? WHERE id=?",
                           (str(exc), utc_now(), run_id))
        connection.execute("UPDATE alpha_artifacts SET status='validated' WHERE id=?", (artifact["id"],))
        connection.commit()
        raise


def run_pending(connection: sqlite3.Connection, limit: int, client: BrainClient | None = None) -> list[dict[str, Any]]:
    client = client or BrainClient(Settings.from_env())
    return [run_one(connection, client, row) for row in pending(connection, limit)]


def refresh_analytics(connection: sqlite3.Connection, limit: int = 20,
                      client: BrainClient | None = None) -> list[dict[str, Any]]:
    client = client or BrainClient(Settings.from_env())
    rows = connection.execute(
        """SELECT r.*,a.family,a.expression FROM simulation_runs r
           JOIN alpha_artifacts a ON a.id=r.artifact_id
           WHERE r.platform_status='COMPLETE' AND r.platform_alpha_id IS NOT NULL
           ORDER BY r.finished_at DESC LIMIT ?""", (limit,),
    ).fetchall()
    refreshed: list[dict[str, Any]] = []
    families: set[str] = set()
    for row in rows:
        alpha_id = row["platform_alpha_id"]
        detail = client.get(f"/alphas/{alpha_id}").data
        old_path = Path(row["response_path"])
        old_path.parent.mkdir(parents=True, exist_ok=True)
        yearly, pnl, correlations = _historical_analytics(old_path.parent)
        yearly = _prefer_records(yearly, client.get(f"/alphas/{alpha_id}/recordsets/yearly-stats").data)
        pnl = _prefer_records(pnl, client.get(f"/alphas/{alpha_id}/recordsets/pnl").data)
        correlations = _prefer_records(correlations, client.get(f"/alphas/{alpha_id}/correlations/self").data)
        try:
            precheck = client.get(f"/alphas/{alpha_id}/check").data
        except BrainError as exc:
            precheck = {"error": str(exc)}
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        refreshed_path = old_path.parent / f"analytics_refresh_{stamp}.json"
        refreshed_path.write_text(json_dumps({"alpha": detail, "precheck": precheck, "yearly": yearly,
                                               "pnl": pnl, "self_correlations": correlations}), encoding="utf-8")
        metrics, checks, _ = _metrics(detail if isinstance(detail, dict) else {})
        metrics["selfCorrelation"] = _maximum_self_correlation(correlations)
        reward = score(metrics, checks)
        connection.execute(
            """UPDATE simulation_runs SET response_path=?,sharpe=?,fitness=?,turnover=?,returns_value=?,drawdown=?,
               margin=?,subuniverse_sharpe=?,self_correlation=?,checks_json=?,annual_json=?,reward=?,error_text=NULL
               WHERE id=?""",
            (str(refreshed_path), metrics.get("sharpe"), metrics.get("fitness"), metrics.get("turnover"),
             metrics.get("returns"), metrics.get("drawdown"), metrics.get("margin"), metrics.get("subuniverseSharpe"),
             metrics.get("selfCorrelation"), json_dumps(checks), json_dumps(yearly), reward, row["id"]),
        )
        connection.execute("DELETE FROM reviews WHERE simulation_run_id=?", (row["id"],))
        families.add(str(row["family"]))
        refreshed.append({"run_id": row["id"], "alpha_id": alpha_id,
                          "yearly_records": len(_records(yearly)),
                          "self_correlation": metrics.get("selfCorrelation"), "reward": reward})
    for family in families:
        aggregate = connection.execute(
            """SELECT count(*),coalesce(sum(r.reward),0),max(r.reward)
               FROM simulation_runs r JOIN alpha_artifacts a ON a.id=r.artifact_id
               WHERE a.family=? AND r.platform_status='COMPLETE'""", (family,),
        ).fetchone()
        connection.execute(
            "UPDATE family_stats SET completed_runs=?,total_reward=?,best_reward=?,updated_at=? WHERE family=?",
            (aggregate[0], aggregate[1], aggregate[2], utc_now(), family),
        )
    return refreshed
