"""LLM-independent semantic alpha search.

This module makes the research loop resilient to weak or unavailable free LLMs.
It searches the audited space:

field profile -> eligible path template -> deterministic AlphaPlan -> FASTEXPR
-> DSL/type/semantic/novelty gates.

The first breadth stage intentionally uses one field per candidate. Cross-field
confirmation/relation templates are introduced only after evidence exists.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import sqlite3
import uuid
from typing import Any

from ..db import json_dumps, utc_now
from .artifacts import ingest_candidate
from .field_profiles import FieldProfile, stored_profile
from .motifs import RESEARCH_EXCLUDED_STATUSES, SCREENED_OUT_STATUS, backfill_motifs, motif_fingerprint, novelty_diagnostics
from .path_templates import PathTemplate, eligible_templates
from .plans import PlanError, PlanRequest, compile_plan, resolve_request, store_plan, update_plan_artifact


AUTONOMOUS_VERSION = "deterministic-semantic-search-v2"
EXCLUDED_BREADTH_TEMPLATES = {
    "relative_ratio",
    "two_series_correlation",
    "regression_residual",
    "state_gated_core",
    "multi_horizon_consensus",
    "orthogonal_confirmation",
}

# High-signal lexical contradictions that should never be overridden merely
# because the broad dataset/profile prior had a high confidence score.
_OPTION_VOL_MARKERS = (
    "putvol", "callvol", "put_vol", "call_vol", "impliedvol", "implied_vol",
    "implied volatility", "atm put", "atm call", "option volatility",
)


@dataclass(frozen=True)
class SearchCandidate:
    field_name: str
    dataset: str
    theme: str
    template_id: str
    horizon_bucket: str
    expression: str
    base_score: float
    novelty_score: float
    confidence: float
    coverage: float
    rationale: str

    @property
    def key(self) -> str:
        return f"{self.template_id}|{self.field_name}".lower()

    @property
    def family(self) -> str:
        digest = hashlib.sha1(self.key.encode("utf-8")).hexdigest()[:8]
        theme = "".join(ch if ch.isalnum() else "_" for ch in self.theme.lower()).strip("_")
        template = "".join(ch if ch.isalnum() else "_" for ch in self.template_id.lower()).strip("_")
        return f"auto_{theme}_{template}_{digest}"[:64]


def _coverage(value: Any) -> float:
    try:
        raw = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if 0.0 <= raw <= 1.0:
        raw *= 100.0
    return max(0.0, min(100.0, raw))


def _horizon(profile: FieldProfile, template: PathTemplate) -> str:
    if profile.update_cadence == "event":
        return "event"
    if profile.update_cadence == "fast":
        return "short"
    if profile.update_cadence == "medium":
        return "medium"
    if template.id in {"slow_level_peer", "peer_residual", "information_staleness"}:
        return "very_slow"
    return "long"


def _lexically_consistent(profile: FieldProfile, name: str, description: str) -> bool:
    """Reject a few high-confidence-but-obviously-contradictory profiles.

    This is deliberately narrow: only unambiguous domain markers are used here.
    Broad semantic interpretation remains the Field Profiler's job.
    """
    text = f"{name} {description}".lower()
    if any(marker in text for marker in _OPTION_VOL_MARKERS):
        return profile.economic_theme in {"options", "risk_volatility"}
    return True


def _active_used_fields(connection: sqlite3.Connection) -> set[str]:
    result: set[str] = set()
    rows = connection.execute(
        """SELECT field_names_json FROM alpha_artifacts
           WHERE status NOT IN (?,?)""",
        RESEARCH_EXCLUDED_STATUSES,
    ).fetchall()
    for row in rows:
        try:
            result.update(str(item).lower() for item in json.loads(row[0] or "[]"))
        except (TypeError, ValueError):
            continue
    return result


def _profile_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """SELECT fp.name,fp.dataset_name,fp.economic_theme,fp.confidence,
                  fp.classification_source,f.description,f.coverage
           FROM field_profiles fp
           JOIN fields f ON f.field_key=fp.field_key
           WHERE fp.data_type IN ('MATRIX','VECTOR')
             AND fp.economic_theme<>'generic'
             AND fp.confidence>=0.70
             AND coalesce(f.description,'')<>''
             AND fp.classification_source NOT LIKE '%_rejected'
           ORDER BY fp.confidence DESC, coalesce(f.coverage,0) DESC, fp.name"""
    ).fetchall()


def retire_unsimulated_autonomous_batches(connection: sqlite3.Connection) -> dict[str, int]:
    """Screen out prior autonomous dry-runs that never consumed BRAIN evidence.

    Re-running the first breadth generator should replace an unsimulated review
    batch, not accumulate it into novelty/duplicate memory. We preserve rows for
    provenance and mark them ``screened_out``.
    """
    rows = connection.execute(
        """SELECT a.id,a.hypothesis_id
           FROM alpha_artifacts a
           LEFT JOIN simulation_runs r ON r.artifact_id=a.id
           WHERE a.generator LIKE 'deterministic-semantic-search-v%'
           GROUP BY a.id,a.hypothesis_id
           HAVING count(r.id)=0"""
    ).fetchall()
    if not rows:
        return {"screened_out": 0}

    artifact_ids = [str(row["id"]) for row in rows]
    hypothesis_ids = [str(row["hypothesis_id"]) for row in rows if row["hypothesis_id"]]
    placeholders = ",".join("?" for _ in artifact_ids)
    connection.execute(
        f"UPDATE alpha_artifacts SET status=? WHERE id IN ({placeholders})",
        (SCREENED_OUT_STATUS, *artifact_ids),
    )
    connection.execute(
        f"UPDATE alpha_plans SET status=? WHERE artifact_id IN ({placeholders})",
        (SCREENED_OUT_STATUS, *artifact_ids),
    )
    if hypothesis_ids:
        hmarks = ",".join("?" for _ in hypothesis_ids)
        connection.execute(
            f"UPDATE hypothesis_cards SET status=? WHERE hypothesis_id IN ({hmarks})",
            (SCREENED_OUT_STATUS, *hypothesis_ids),
        )
    # Rebuild derived caches so screened rows cannot influence novelty/subtree
    # statistics before the replacement batch is compiled.
    backfill_motifs(connection)
    connection.commit()
    return {"screened_out": len(artifact_ids)}


def build_candidate_pool(
    connection: sqlite3.Connection,
    *,
    max_fields_per_theme: int = 16,
    exclude_previously_used: bool = True,
) -> list[SearchCandidate]:
    """Compile a bounded pool of legal single-field breadth candidates."""
    used = _active_used_fields(connection) if exclude_previously_used else set()
    theme_counts: Counter[str] = Counter()
    pool: list[SearchCandidate] = []

    for row in _profile_rows(connection):
        name = str(row["name"])
        if name.lower() in used:
            continue
        theme = str(row["economic_theme"])
        if theme_counts[theme] >= max_fields_per_theme:
            continue
        profile = stored_profile(connection, name)
        if profile is None:
            continue
        description = " ".join(str(row["description"] or "").split())[:240]
        if not _lexically_consistent(profile, name, description):
            continue
        templates = [
            template
            for template in eligible_templates([profile])
            if template.id not in EXCLUDED_BREADTH_TEMPLATES
        ]
        if not templates:
            continue
        theme_counts[theme] += 1
        confidence = float(row["confidence"] or 0.0)
        coverage = _coverage(row["coverage"])

        for template in templates:
            horizon = _horizon(profile, template)
            request = PlanRequest(
                template_id=template.id,
                field_names=(name,),
                horizon_bucket=horizon,
                direction="prior",
                group="industry",
                turnover_control=False,
                output_control="standardize",
                rationale=f"{template.purpose} Field evidence: {description}",
            )
            family = f"preview_{hashlib.sha1((template.id+'|'+name).encode()).hexdigest()[:10]}"
            try:
                plan = resolve_request(connection, request, family=family)
                expression = compile_plan(connection, plan)
                motif = motif_fingerprint(connection, expression)
                novelty = novelty_diagnostics(connection, motif)
            except (PlanError, ValueError):
                continue
            if int(novelty.get("parameter_bucket_count", 0)) > 0:
                continue

            base = (
                2.0 * confidence
                + 0.8 * (coverage / 100.0)
                + 1.4 * float(novelty.get("novelty_score", 0.0))
            )
            if template.id in {"vector_event_novelty", "information_staleness", "extremum_recency"}:
                base += 0.20
            pool.append(SearchCandidate(
                field_name=name,
                dataset=str(row["dataset_name"] or "unknown"),
                theme=theme,
                template_id=template.id,
                horizon_bucket=horizon,
                expression=expression,
                base_score=round(base, 6),
                novelty_score=float(novelty.get("novelty_score", 0.0)),
                confidence=confidence,
                coverage=coverage,
                rationale=request.rationale,
            ))

    return sorted(pool, key=lambda item: (-item.base_score, item.theme, item.dataset, item.field_name, item.template_id))


def select_diverse(pool: list[SearchCandidate], count: int = 6) -> list[SearchCandidate]:
    """Greedily maximize quality and breadth across theme/dataset/template."""
    selected: list[SearchCandidate] = []
    used_fields: set[str] = set()
    theme_counts: Counter[str] = Counter()
    dataset_counts: Counter[str] = Counter()
    template_counts: Counter[str] = Counter()
    remaining = list(pool)

    while remaining and len(selected) < count:
        best: tuple[float, SearchCandidate] | None = None
        for item in remaining:
            if item.field_name.lower() in used_fields:
                continue
            if template_counts[item.template_id] >= 2:
                continue
            score = item.base_score
            score += 1.40 if theme_counts[item.theme] == 0 else -0.55 * theme_counts[item.theme]
            score += 1.10 if dataset_counts[item.dataset] == 0 else -0.70 * dataset_counts[item.dataset]
            score += 1.20 if template_counts[item.template_id] == 0 else -0.85 * template_counts[item.template_id]
            if best is None or score > best[0]:
                best = (score, item)
        if best is None:
            break
        item = best[1]
        selected.append(item)
        used_fields.add(item.field_name.lower())
        theme_counts[item.theme] += 1
        dataset_counts[item.dataset] += 1
        template_counts[item.template_id] += 1
        remaining = [candidate for candidate in remaining if candidate.key != item.key]

    if len(selected) != count:
        raise RuntimeError(f"Autonomous search found only {len(selected)}/{count} usable candidates")
    if len(theme_counts) < min(5, count):
        raise RuntimeError(f"Autonomous breadth diversity failed: only {len(theme_counts)} themes")
    if len(dataset_counts) < min(5, count):
        raise RuntimeError(f"Autonomous breadth diversity failed: only {len(dataset_counts)} datasets")
    if len(template_counts) < min(4, count):
        raise RuntimeError(f"Autonomous breadth diversity failed: only {len(template_counts)} templates")
    return selected


def _store_research_record(
    connection: sqlite3.Connection,
    candidate: SearchCandidate,
    *,
    artifact_id: str,
) -> tuple[str, str]:
    hypothesis_id = str(uuid.uuid4())
    card_id = str(uuid.uuid4())
    profile = stored_profile(connection, candidate.field_name)
    direction = profile.direction_prior if profile else "ambiguous"
    statement = (
        f"{candidate.template_id} on {candidate.field_name} may contain predictive cross-sectional information "
        f"consistent with the field's {profile.update_cadence if profile else 'unknown'} update structure."
    )
    mechanism = candidate.rationale
    falsifier = (
        "Reject this breadth hypothesis if the first BRAIN diagnostic is non-predictive, structurally invalid, "
        "or fails robustness/coverage checks; do not rescue it by dense parameter search."
    )
    connection.execute(
        """INSERT INTO hypotheses(id,family,statement,mechanism,expected_direction,source,created_at)
           VALUES(?,?,?,?,?,?,?)""",
        (hypothesis_id, candidate.family, statement, mechanism, direction, AUTONOMOUS_VERSION, utc_now()),
    )
    connection.execute(
        """INSERT INTO hypothesis_cards(
            id,hypothesis_id,family,statement,mechanism,expected_direction,horizon,data_themes_json,
            field_names_json,operator_roles_json,falsifier,novelty_json,status,generator,model_name,
            prompt_hash,evidence_path,created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            card_id, hypothesis_id, candidate.family, statement, mechanism, direction,
            candidate.horizon_bucket, json_dumps([candidate.theme]), json_dumps([candidate.field_name]),
            json_dumps([]), falsifier,
            json_dumps({
                "novelty_score": candidate.novelty_score,
                "base_score": candidate.base_score,
                "dataset": candidate.dataset,
                "source": AUTONOMOUS_VERSION,
            }),
            "compiled", AUTONOMOUS_VERSION, None, None,
            json_dumps({"source": "local deterministic semantic search"}), utc_now(),
        ),
    )
    connection.execute("UPDATE alpha_artifacts SET hypothesis_id=? WHERE id=?", (hypothesis_id, artifact_id))
    return hypothesis_id, card_id


def materialize_autonomous_breadth(
    connection: sqlite3.Connection,
    *,
    count: int = 6,
) -> dict[str, Any]:
    """Generate and persist exactly ``count`` validated breadth candidates."""
    retired = retire_unsimulated_autonomous_batches(connection)
    pool = build_candidate_pool(connection)
    selected = select_diverse(pool, count=count)
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for candidate in selected:
        result = ingest_candidate(
            connection,
            expression=candidate.expression,
            family=candidate.family,
            rationale=candidate.rationale,
            generator=AUTONOMOUS_VERSION,
            prompt_version=AUTONOMOUS_VERSION,
        )
        if not result.accepted or not result.artifact_id:
            rejected.append({
                "family": candidate.family,
                "field": candidate.field_name,
                "template": candidate.template_id,
                "reason": result.reason,
            })
            continue

        hypothesis_id, card_id = _store_research_record(
            connection, candidate, artifact_id=result.artifact_id
        )
        request = PlanRequest(
            template_id=candidate.template_id,
            field_names=(candidate.field_name,),
            horizon_bucket=candidate.horizon_bucket,
            direction="prior",
            group="industry",
            turnover_control=False,
            output_control="standardize",
            rationale=candidate.rationale,
        )
        plan = resolve_request(
            connection,
            request,
            family=candidate.family,
            hypothesis_id=hypothesis_id,
            card_id=card_id,
        )
        store_plan(connection, plan, request=request, artifact_id=result.artifact_id, status="compiled")
        update_plan_artifact(connection, plan.id, result.artifact_id, "compiled")
        accepted.append({
            "artifact_id": result.artifact_id,
            "family": candidate.family,
            "field": candidate.field_name,
            "dataset": candidate.dataset,
            "theme": candidate.theme,
            "template": candidate.template_id,
            "horizon_bucket": candidate.horizon_bucket,
            "expression": candidate.expression,
            "confidence": round(candidate.confidence, 6),
            "coverage": round(candidate.coverage, 6),
            "base_score": candidate.base_score,
            "novelty_score": candidate.novelty_score,
            "nearest_similarity": result.similarity,
        })

    connection.commit()
    if len(accepted) != count:
        raise RuntimeError(
            f"Only {len(accepted)}/{count} autonomous candidates survived final ingest gates; "
            f"rejections={rejected}"
        )
    return {
        "version": AUTONOMOUS_VERSION,
        "network_calls": 0,
        "brain_simulations_sent": 0,
        "retired_unsimulated_previous_batch": retired["screened_out"],
        "pool_size": len(pool),
        "accepted": accepted,
        "rejected": rejected,
        "theme_count": len({item["theme"] for item in accepted}),
        "dataset_count": len({item["dataset"] for item in accepted}),
        "template_count": len({item["template"] for item in accepted}),
        "ready_for_simulation_review": True,
    }


__all__ = [
    "AUTONOMOUS_VERSION",
    "SearchCandidate",
    "build_candidate_pool",
    "materialize_autonomous_breadth",
    "retire_unsimulated_autonomous_batches",
    "select_diverse",
]
