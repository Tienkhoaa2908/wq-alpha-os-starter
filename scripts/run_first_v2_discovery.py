from __future__ import annotations

"""Run the first reviewed v2 breadth cycle locally, without BRAIN simulation.

This wrapper always writes a small sanitized run-status file so a failed Gemini
or local research stage is visible on GitHub after the PowerShell wrapper
finalizes the task. Secrets, prompts, raw responses and FASTEXPR expressions
are never written to this status file.
"""

import argparse
from dataclasses import replace
from datetime import UTC, datetime
import json
import traceback

from wq_alpha_os.config import PROJECT_ROOT, Settings
from wq_alpha_os.db import initialize, session
from wq_alpha_os.providers import GeminiProvider
from wq_alpha_os.research.first_cycle import run_first_cycle


STATUS_PATH = PROJECT_ROOT / "docs" / "generated" / "first_v2_run_status.json"


def _safe_error(exc: BaseException, limit: int = 1200) -> str:
    """Return a short diagnostic without dumping request/response payloads."""
    text = " ".join(str(exc).split())
    if not text:
        text = exc.__class__.__name__
    return text[:limit]


def _write_status(payload: dict[str, object]) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    value = {
        "generated_at": datetime.now(UTC).isoformat(),
        "brain_simulations_sent": 0,
        **payload,
    }
    STATUS_PATH.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=6)
    args = parser.parse_args()

    _write_status({
        "status": "running",
        "stage": "startup",
        "requested_hypotheses": args.count,
    })

    selected_model: str | None = None
    try:
        initialize()
        settings = Settings.from_env()

        # Resolve against GET /models using the user's own API key. This avoids
        # failing the whole research run when a configured model is retired or
        # unavailable to this Google AI project. Replace Settings before the
        # run so evidence/provenance records the actual model used.
        gemini_settings = replace(settings, llm_provider="gemini")
        resolver = GeminiProvider(gemini_settings)
        selected_model = resolver.resolve_model()
        settings = replace(
            gemini_settings,
            gemini_model=selected_model,
        )

        _write_status({
            "status": "running",
            "stage": "first_cycle",
            "requested_hypotheses": args.count,
            "provider": "gemini",
            "configured_model": gemini_settings.gemini_model,
            "selected_model": selected_model,
        })
        with session() as connection:
            result = run_first_cycle(connection, count=args.count, settings=settings)
    except Exception as exc:  # noqa: BLE001 - runner must persist failures from every local stage.
        _write_status({
            "status": "failed",
            "stage": "first_cycle",
            "requested_hypotheses": args.count,
            "selected_model": selected_model,
            "error_type": exc.__class__.__name__,
            "error": _safe_error(exc),
            "traceback_tail": [
                line[:500]
                for line in traceback.format_exception_only(exc.__class__, exc)[-3:]
            ],
            "ready_for_first_simulation": False,
        })
        print(json.dumps({
            "ok": False,
            "status_path": str(STATUS_PATH),
            "selected_model": selected_model,
            "error_type": exc.__class__.__name__,
            "error": _safe_error(exc),
            "brain_simulations_sent": 0,
        }, ensure_ascii=False, indent=2))
        return 1

    result["gemini_model"] = selected_model
    _write_status({
        "status": "success",
        "stage": "dry_run_complete",
        "requested_hypotheses": args.count,
        "selected_model": selected_model,
        "ready_for_first_simulation": bool(result.get("ready_for_first_simulation")),
        "gate_reasons": result.get("gate_reasons", []),
        "hypothesis_cards": result.get("hypothesis_cards", []),
        "design": result.get("design", {}),
        "audit_path": result.get("audit_path"),
    })
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
