from __future__ import annotations

import sqlite3
from typing import Any

from ..brain.simulation import run_pending
from ..config import Settings
from ..providers import ProviderError
from .mutations import evidence_mutations
from .proposer import propose
from .reviewer import review_pending


def run_cycle(
    connection: sqlite3.Connection,
    budget: int,
    settings: Settings | None = None,
) -> dict[str, Any]:
    mutated = evidence_mutations(connection, max(1, budget // 3))
    provider_error = None
    try:
        _, generated = propose(connection, max(1, budget - len(mutated)), settings)
    except ProviderError as exc:
        generated = []
        provider_error = str(exc)
    accepted = sum(result.accepted for result in generated)
    simulated = run_pending(connection, budget)
    reviewed = review_pending(connection, budget)
    return {"evidence_mutations": len(mutated), "generated": len(generated), "accepted": accepted,
            "simulated": len(simulated), "reviewed": len(reviewed), "provider_error": provider_error}
