from __future__ import annotations

import base64
import csv
import json
import sqlite3
from pathlib import Path
from typing import Any

from .config import simulation_settings

SIMULATOR_URL = "https://platform.worldquantbrain.com/simulate"


def encode_payload(expression: str, settings: dict[str, Any]) -> str:
    raw = json.dumps({"expression": expression, "settings": settings}, ensure_ascii=False, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_payload(value: str) -> dict[str, Any]:
    padded = value + "=" * (-len(value) % 4)
    return json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))


def simulator_link(expression: str, settings: dict[str, Any]) -> str:
    return f"{SIMULATOR_URL}?alpha_os={encode_payload(expression, settings)}"


def export_csv(connection: sqlite3.Connection, output: Path, status: str = "promoted", limit: int = 200) -> int:
    rows = connection.execute(
        """SELECT a.*,r.settings_json,r.sharpe,r.fitness,r.turnover,r.self_correlation,r.platform_alpha_id,
           (SELECT verdict FROM reviews v WHERE v.artifact_id=a.id ORDER BY created_at DESC LIMIT 1) verdict
           FROM alpha_artifacts a LEFT JOIN simulation_runs r ON r.id=(
             SELECT id FROM simulation_runs x WHERE x.artifact_id=a.id ORDER BY reward DESC,finished_at DESC LIMIT 1)
           WHERE (?='all' OR a.status=?) ORDER BY coalesce(a.best_reward,-999) DESC,a.created_at LIMIT ?""",
        (status, status, limit),
    ).fetchall()
    output.parent.mkdir(parents=True, exist_ok=True)
    columns = ["artifact_id", "family", "status", "expression", "simulator_url", "sharpe", "fitness", "turnover",
               "self_correlation", "verdict", "platform_alpha_id", "rationale"]
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            settings = json.loads(row["settings_json"]) if row["settings_json"] else simulation_settings()
            writer.writerow({
                "artifact_id": row["id"], "family": row["family"], "status": row["status"],
                "expression": row["expression"], "simulator_url": simulator_link(row["expression"], settings),
                "sharpe": row["sharpe"], "fitness": row["fitness"], "turnover": row["turnover"],
                "self_correlation": row["self_correlation"], "verdict": row["verdict"],
                "platform_alpha_id": row["platform_alpha_id"], "rationale": row["rationale"],
            })
    return len(rows)
