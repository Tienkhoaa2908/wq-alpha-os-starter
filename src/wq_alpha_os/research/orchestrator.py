from __future__ import annotations

"""End-to-end evidence-driven research cycle v2.

The orchestrator uses deterministic knowledge/scheduling locally, asks the LLM
only for hypotheses and high-level AlphaPlans, then lets BRAIN evaluate the
compiled candidates.  It never calls the legacy direct-expression proposer.
"""

import sqlite3
from typing import Any

from ..brain.simulation import refresh_analytics, run_pending
from ..config import Settings
from ..providers import ProviderError
from .agentic_v2 import design, discover
from .empirical import rebuild_motif_stats
from .knowledge_base import rebuild_all
from .mutations import evidence_mutations
from .reviewer import review_pending
from .scheduler import controlled_cycle_plan


def run_cycle(
    connection: sqlite3.Connection,
    budget: int = 12,
    settings: Settings | None = None,
    *,
    simulate: bool = True,
) -> dict[str, Any]:
    budget = max(1, int(budget))
    knowledge_before = rebuild_all(connection)
    allocation = controlled_cycle_plan(connection, budget)
    quotas = allocation["quotas"]

    # Only deterministic, evidence-isolating mutations are automatic.  At the
    # moment this means one polarity diagnostic or one hump intervention.
    diagnostic_budget = int(quotas.get("targeted_refinement", 0))
    diagnostic_results = evidence_mutations(connection, diagnostic_budget) if diagnostic_budget else []

    provider_error: str | None = None
    discovered: dict[str, Any] = {"accepted": [], "rejected": []}
    designed: dict[str, Any] = {"accepted": 0, "rejected": 0, "cards": []}
    # New breadth plus semantic diversity both need hypothesis-level reasoning.
    hypothesis_budget = int(quotas.get("new_hypotheses", 0)) + int(quotas.get("diversity_or_robustness", 0))
    try:
        if hypothesis_budget > 0:
            discovered = discover(connection, hypothesis_budget, settings=settings)
            # One plan per card keeps the first pass diagnostic and prevents a
            # free LLM batch from silently becoming a parameter grid search.
            designed = design(connection, hypothesis_budget, per_card=1, settings=settings)
    except ProviderError as exc:
        provider_error = str(exc)

    simulated: list[dict[str, Any]] = []
    refreshed: list[dict[str, Any]] = []
    reviewed: list[dict[str, Any]] = []
    if simulate:
        simulated = run_pending(connection, budget)
        # run_one already fetches initial analytics; refresh is still useful
        # because correlation/yearly endpoints can become available later.
        if simulated:
            try:
                refreshed = refresh_analytics(connection, min(budget, len(simulated)))
            except Exception:
                # Do not erase completed simulation evidence merely because an
                # optional analytics endpoint is temporarily unavailable.
                refreshed = []
        reviewed = review_pending(connection, budget)

    empirical_after = rebuild_motif_stats(connection)
    allocation_after = controlled_cycle_plan(connection, budget)
    return {
        "version": "research-orchestrator-v2",
        "knowledge": knowledge_before,
        "allocation_before": allocation,
        "diagnostic_mutations": [result.__dict__ for result in diagnostic_results],
        "discovery": discovered,
        "design": designed,
        "simulated": simulated,
        "analytics_refreshed": refreshed,
        "reviewed": reviewed,
        "empirical_after": empirical_after,
        "allocation_after": allocation_after,
        "provider_error": provider_error,
        "simulation_enabled": simulate,
    }
