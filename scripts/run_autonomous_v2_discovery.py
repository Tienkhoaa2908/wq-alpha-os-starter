from __future__ import annotations

"""Generate the first autonomous v2 breadth batch without any LLM/API call."""

import argparse
from datetime import UTC, datetime
import json

from wq_alpha_os.config import PROJECT_ROOT
from wq_alpha_os.db import initialize, session
from wq_alpha_os.research.autonomous_search import materialize_autonomous_breadth


STATUS_PATH = PROJECT_ROOT / "docs" / "generated" / "autonomous_v2_run_status.json"
AUDIT_PATH = PROJECT_ROOT / "docs" / "generated" / "autonomous_v2_dry_run.json"


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=6)
    args = parser.parse_args()
    if args.count != 6:
        raise SystemExit("The first autonomous breadth batch is fixed at 6 candidates.")

    _write(STATUS_PATH, {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "running",
        "mode": "deterministic_no_llm",
        "network_calls": 0,
        "brain_simulations_sent": 0,
    })

    try:
        initialize()
        with session() as connection:
            result = materialize_autonomous_breadth(connection, count=args.count)
    except Exception as exc:  # runner must persist sanitized failure state
        payload = {
            "generated_at": datetime.now(UTC).isoformat(),
            "status": "failed",
            "mode": "deterministic_no_llm",
            "network_calls": 0,
            "brain_simulations_sent": 0,
            "error_type": exc.__class__.__name__,
            "error": " ".join(str(exc).split())[:1800],
            "ready_for_simulation_review": False,
        }
        _write(STATUS_PATH, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1

    _write(AUDIT_PATH, result)
    status = {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "success",
        "mode": "deterministic_no_llm",
        "network_calls": 0,
        "brain_simulations_sent": 0,
        "accepted": len(result.get("accepted", [])),
        "pool_size": result.get("pool_size"),
        "theme_count": result.get("theme_count"),
        "dataset_count": result.get("dataset_count"),
        "ready_for_simulation_review": bool(result.get("ready_for_simulation_review")),
        "audit_path": str(AUDIT_PATH.relative_to(PROJECT_ROOT)),
    }
    _write(STATUS_PATH, status)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
