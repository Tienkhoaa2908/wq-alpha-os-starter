from __future__ import annotations

"""Local first-cycle orchestrator.

The user runs one command locally. Gemini is used only for bounded semantic
review, hypothesis reasoning and plan/critic calls; FASTEXPR compilation and
all gates stay deterministic. This module never sends a BRAIN simulation.
"""

from collections import Counter
from itertools import combinations
import json
from pathlib import Path
import sqlite3
import uuid
from typing import Any

from ..config import PROJECT_ROOT, Settings
from ..db import json_dumps, utc_now
from ..providers import CompletionProvider, provider_for
from .agentic_v2 import (
    _gemini_settings,
    _model_name,
    _parse_object,
    _validate_hypothesis,
    _write_exchange,
    design,
)
from .candidate_review import adjudicate_packet


FIRST_CYCLE_VERSION = "first-v2-breadth-cycle-v1"
CARD_GENERATOR = "semantic_discovery_v3_critic"


def _discovery_system() -> str:
    return """Bạn tạo ứng viên giả thuyết alpha định lượng từ packet field đã được kiểm định ngữ nghĩa.
TUYỆT ĐỐI không viết FASTEXPR, công thức, tên toán tử, tham số số cụ thể hay kết quả mô phỏng.

Mỗi giả thuyết phải có đúng một cơ chế kinh tế có thể bác bỏ. Ưu tiên breadth:
- khác field;
- khác economic theme;
- khác dataset;
- không clone family value_cashflow_multihorizon bằng đổi field/window;
- không multi-horizon ở breadth stage.

Trả duy nhất JSON {"hypotheses":[...]}.
Mỗi phần tử gồm đúng:
family, statement, mechanism, expected_direction, horizon_bucket, field_names, falsifier, novelty.

expected_direction: positive|negative|ambiguous.
horizon_bucket: event|short|medium|long|very_slow.
field_names: 1 hoặc 2 tên chính xác trong candidate_fields.
Không được có expression/formula/operator/operator_roles/parameters."""


def _critic_system() -> str:
    return """Bạn là phản biện độc lập cho các giả thuyết alpha cấp kinh tế, chưa phải công thức.
Không viết FASTEXPR, không nêu toán tử và không sửa giả thuyết.

Với từng candidate index, đánh giá:
- mechanism có được field description hỗ trợ không;
- direction có bị bịa không;
- falsifier có thực sự bác bỏ được không;
- novelty có khác các failure/family cũ không;
- giả thuyết có quá chung chung hay ghép nhiều cơ chế không.

Trả duy nhất JSON:
{"decisions":[{"index":0,"verdict":"accept|reject","reasons":["..."],"semantic_concerns":["..."]}]} ."""


def _short(value: Any, limit: int = 320) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _field_info(connection: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    row = connection.execute(
        """SELECT fp.name,fp.dataset_name,fp.economic_theme,fp.secondary_themes_json,
                  fp.semantic_form,fp.update_cadence,fp.classification_source,fp.confidence,
                  f.description,f.coverage
           FROM field_profiles fp JOIN fields f ON f.field_key=fp.field_key
           WHERE lower(fp.name)=lower(?) LIMIT 1""",
        (name,),
    ).fetchone()
    if row is None:
        return None
    return {
        "name": row["name"],
        "description": _short(row["description"], 240),
        "dataset": row["dataset_name"],
        "theme": row["economic_theme"],
        "secondary_themes": json.loads(row["secondary_themes_json"] or "[]"),
        "form": row["semantic_form"],
        "cadence": row["update_cadence"],
        "review_source": row["classification_source"],
        "confidence": row["confidence"],
        "coverage": row["coverage"],
    }


def _enrich(connection: sqlite3.Connection, card: dict[str, Any]) -> dict[str, Any] | None:
    fields = [_field_info(connection, name) for name in card["field_names"]]
    if any(item is None for item in fields):
        return None
    typed = [item for item in fields if item is not None]
    return {
        **card,
        "primary_theme": str(typed[0]["theme"]),
        "source_datasets": sorted({str(item["dataset"]) for item in typed}),
        "field_details": typed,
    }


def _propose(
    connection: sqlite3.Connection,
    context: dict[str, Any],
    *,
    requested: int,
    settings: Settings,
    model: CompletionProvider,
    stage: str,
    extra: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    system = _discovery_system()
    payload = dict(context)
    payload["requested_hypotheses"] = requested
    if extra:
        payload["repair_context"] = extra
    user = json_dumps(payload)
    answer = model.complete(system, user)
    evidence, prompt_hash = _write_exchange(settings, stage, system, user, answer)
    data = _parse_object(answer)
    raw_items = data.get("hypotheses")
    if not isinstance(raw_items, list):
        raise ValueError("Hypothesis discovery returned no hypotheses list")

    allowed_fields = {str(item["name"]).lower() for item in context["candidate_fields"]}
    existing = {
        str(row[0]).lower()
        for row in connection.execute("SELECT family FROM hypotheses GROUP BY family")
    }
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen_families: set[str] = set()
    for raw in raw_items[: max(requested * 2, requested)]:
        card, reason = _validate_hypothesis(raw, allowed_fields, existing | seen_families)
        if card is None:
            rejected.append({"reason": reason})
            continue
        enriched = _enrich(connection, card)
        if enriched is None:
            rejected.append({"family": card["family"], "reason": "field_profile_missing"})
            continue
        seen_families.add(card["family"])
        accepted.append(enriched)
    return accepted, {
        "evidence_path": str(evidence),
        "prompt_hash": prompt_hash,
        "rejected": rejected,
    }


def _critic(
    candidates: list[dict[str, Any]],
    *,
    failure_ledger: list[dict[str, Any]],
    settings: Settings,
    model: CompletionProvider,
    stage: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not candidates:
        return [], {"evidence_path": None, "decisions": []}
    system = _critic_system()
    public_candidates = [
        {
            "index": index,
            "family": item["family"],
            "statement": item["statement"],
            "mechanism": item["mechanism"],
            "expected_direction": item["expected_direction"],
            "horizon_bucket": item["horizon_bucket"],
            "field_names": item["field_names"],
            "field_details": item["field_details"],
            "falsifier": item["falsifier"],
            "novelty": item["novelty"],
            "primary_theme": item["primary_theme"],
            "source_datasets": item["source_datasets"],
        }
        for index, item in enumerate(candidates)
    ]
    user = json_dumps({
        "version": FIRST_CYCLE_VERSION,
        "candidates": public_candidates,
        "failure_ledger": failure_ledger,
    })
    answer = model.complete(system, user)
    evidence, _ = _write_exchange(settings, stage, system, user, answer)
    data = _parse_object(answer)
    raw = data.get("decisions")
    if not isinstance(raw, list):
        raise ValueError("Hypothesis critic returned no decisions list")
    decisions: dict[int, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        verdict = str(item.get("verdict") or "").lower()
        if not isinstance(index, int) or not 0 <= index < len(candidates):
            continue
        if verdict not in {"accept", "reject"}:
            continue
        decisions[index] = {
            "verdict": verdict,
            "reasons": [_short(value, 220) for value in item.get("reasons", []) if str(value).strip()][:4],
            "semantic_concerns": [
                _short(value, 220)
                for value in item.get("semantic_concerns", [])
                if str(value).strip()
            ][:4],
        }
    accepted = []
    detail_rows = []
    for index, candidate in enumerate(candidates):
        decision = decisions.get(index, {
            "verdict": "reject",
            "reasons": ["missing_valid_critic_decision"],
            "semantic_concerns": [],
        })
        detail_rows.append({"index": index, "family": candidate["family"], **decision})
        if decision["verdict"] == "accept":
            accepted.append({**candidate, "critic": decision})
    return accepted, {"evidence_path": str(evidence), "decisions": detail_rows}


def _combo_metrics(combo: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
    families = [str(item["family"]).lower() for item in combo]
    if len(families) != len(set(families)):
        return None
    fields = [name.lower() for item in combo for name in item["field_names"]]
    if len(fields) != len(set(fields)):
        return None
    primary_themes = {str(item["primary_theme"]) for item in combo}
    datasets = {dataset for item in combo for dataset in item["source_datasets"]}
    dataset_card_counts: Counter[str] = Counter()
    for item in combo:
        for dataset in set(item["source_datasets"]):
            dataset_card_counts[dataset] += 1
    if any(count > 2 for count in dataset_card_counts.values()):
        return None
    return {
        "theme_count": len(primary_themes),
        "dataset_count": len(datasets),
        "max_dataset_cards": max(dataset_card_counts.values(), default=0),
    }


def _select_diverse(candidates: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if len(candidates) < count:
        return []
    need = min(5, count)
    best: tuple[tuple[int, int, int], tuple[dict[str, Any], ...]] | None = None
    pool = candidates[:16]
    for combo in combinations(pool, count):
        metrics = _combo_metrics(combo)
        if metrics is None:
            continue
        if metrics["theme_count"] < need or metrics["dataset_count"] < need:
            continue
        score = (
            metrics["theme_count"],
            metrics["dataset_count"],
            -metrics["max_dataset_cards"],
        )
        if best is None or score > best[0]:
            best = (score, combo)
    return list(best[1]) if best else []


def _store_cards(
    connection: sqlite3.Connection,
    cards: list[dict[str, Any]],
    *,
    settings: Settings,
    discovery_meta: dict[str, Any],
    critic_meta: dict[str, Any],
) -> list[str]:
    ids: list[str] = []
    for card in cards:
        hypothesis_id = str(uuid.uuid4())
        card_id = str(uuid.uuid4())
        connection.execute(
            "INSERT INTO hypotheses VALUES(?,?,?,?,?,?,?)",
            (
                hypothesis_id,
                card["family"],
                card["statement"],
                card["mechanism"],
                card["expected_direction"],
                CARD_GENERATOR,
                utc_now(),
            ),
        )
        connection.execute(
            """INSERT INTO hypothesis_cards VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                card_id,
                hypothesis_id,
                card["family"],
                card["statement"],
                card["mechanism"],
                card["expected_direction"],
                card["horizon_bucket"],
                json_dumps(sorted({item["theme"] for item in card["field_details"]})),
                json_dumps(card["field_names"]),
                json_dumps([]),
                card["falsifier"],
                json_dumps({
                    "statement": card["novelty"],
                    "primary_theme": card["primary_theme"],
                    "source_datasets": card["source_datasets"],
                    "hypothesis_critic": card.get("critic", {}),
                }),
                "discovered",
                CARD_GENERATOR,
                _model_name(settings),
                discovery_meta.get("prompt_hash"),
                json_dumps({
                    "discovery": discovery_meta.get("evidence_path"),
                    "critic": critic_meta.get("evidence_path"),
                }),
                utc_now(),
            ),
        )
        ids.append(card_id)
    return ids


def _existing_first_cycle_cards(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """SELECT * FROM hypothesis_cards
           WHERE generator=?
           ORDER BY created_at,id""",
        (CARD_GENERATOR,),
    ).fetchall()


def _card_public(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    names = [str(value) for value in json.loads(row["field_names_json"] or "[]")]
    field_details = [_field_info(connection, name) for name in names]
    field_details = [item for item in field_details if item is not None]
    novelty = json.loads(row["novelty_json"] or "{}")
    return {
        "card_id": row["id"],
        "family": row["family"],
        "statement": row["statement"],
        "mechanism": row["mechanism"],
        "field_names": names,
        "field_details": field_details,
        "source_datasets": sorted({str(item["dataset"]) for item in field_details}),
        "primary_theme": str(field_details[0]["theme"]) if field_details else "unknown",
        "expected_direction": row["expected_direction"],
        "horizon_bucket": row["horizon"],
        "falsifier": row["falsifier"],
        "novelty": novelty.get("statement"),
        "hypothesis_critic": novelty.get("hypothesis_critic", {}),
        "status": row["status"],
    }


def _plan_public(connection: sqlite3.Connection, card_id: str) -> dict[str, Any] | None:
    row = connection.execute(
        """SELECT p.*,a.complexity_nodes,a.complexity_depth
           FROM alpha_plans p
           LEFT JOIN alpha_artifacts a ON a.id=p.artifact_id
           WHERE p.card_id=?
           ORDER BY p.created_at DESC LIMIT 1""",
        (card_id,),
    ).fetchone()
    if row is None:
        return None
    request = json.loads(row["request_json"] or "{}")
    resolved = json.loads(row["resolved_json"] or "{}")
    motif = None
    if row["artifact_id"]:
        motif_row = connection.execute(
            """SELECT role_motif_hash,semantic_hash,parameter_hash,novelty_score
               FROM artifact_motifs WHERE artifact_id=?""",
            (row["artifact_id"],),
        ).fetchone()
        motif = dict(motif_row) if motif_row else None
    return {
        "plan_id": row["id"],
        "template_id": row["template_id"],
        "status": row["status"],
        "artifact_id": row["artifact_id"],
        "horizon_bucket": resolved.get("horizon_bucket") or request.get("horizon_bucket"),
        "direction": resolved.get("direction") or request.get("direction"),
        "group": resolved.get("group") or request.get("group"),
        "turnover_control": bool(request.get("turnover_control", False)),
        "output_control": request.get("output_control"),
        "rationale": _short(request.get("rationale"), 320),
        "compile_success": bool(row["artifact_id"]),
        "dsl_type_gate": "pass" if row["artifact_id"] else "fail",
        "semantic_gate": "pass" if row["artifact_id"] else "fail",
        "exact_structural_gate": "pass" if row["artifact_id"] else "fail",
        "parameter_normalized_gate": "pass" if row["artifact_id"] else "fail",
        "plan_critic": "accept" if row["artifact_id"] else "reject_or_not_run",
        "motif": motif,
        "ast_nodes": row["complexity_nodes"],
        "ast_depth": row["complexity_depth"],
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _dry_run_audit(
    connection: sqlite3.Connection,
    *,
    semantic_review: dict[str, Any] | None,
    card_rows: list[sqlite3.Row],
    design_result: dict[str, Any],
    count: int,
) -> dict[str, Any]:
    cards = [_card_public(connection, row) for row in card_rows]
    plans = {card["card_id"]: _plan_public(connection, card["card_id"]) for card in cards}
    items = [{**card, "plan": plans[card["card_id"]]} for card in cards]
    ready_items = [item for item in items if item["plan"] and item["plan"]["compile_success"]]
    themes = Counter(str(item["primary_theme"]) for item in cards)
    datasets = Counter(dataset for item in cards for dataset in set(item["source_datasets"]))
    duplicate_rejections = 0
    semantic_rejections = 0
    for card_result in design_result.get("cards", []):
        for rejection in card_result.get("rejected", []):
            reason = str(rejection.get("reason") or "")
            if "duplicate" in reason or "clone" in reason:
                duplicate_rejections += 1
            if "semantic" in reason or "validation" in reason:
                semantic_rejections += 1
    reasons: list[str] = []
    if len(cards) != count:
        reasons.append("not_exactly_six_reviewed_cards")
    if len(ready_items) != count:
        reasons.append("not_all_plans_compiled_and_gated")
    if len(themes) < min(5, count):
        reasons.append("insufficient_theme_diversity")
    if len(datasets) < min(5, count):
        reasons.append("insufficient_dataset_diversity")
    ready = not reasons
    return {
        "version": FIRST_CYCLE_VERSION,
        "semantic_review_summary": None if semantic_review is None else {
            "reviewed_unique": semantic_review.get("reviewed_unique"),
            "accept": semantic_review.get("accept"),
            "correct": semantic_review.get("correct"),
            "reject": semantic_review.get("reject"),
            "gate": semantic_review.get("gate"),
        },
        "cards": items,
        "batch": {
            "accepted_hypothesis_count": len(cards),
            "accepted_plan_count": len(ready_items),
            "theme_count": len(themes),
            "dataset_count": len(datasets),
            "theme_counts": dict(themes),
            "dataset_counts": dict(datasets),
            "duplicate_rejection_count": duplicate_rejections,
            "semantic_rejection_count": semantic_rejections,
            "ready_for_first_simulation": ready,
            "gate_reasons": reasons or ["all_first_cycle_dry_run_gates_passed"],
            "brain_simulations_sent": 0,
        },
    }


def run_first_cycle(
    connection: sqlite3.Connection,
    count: int = 6,
    *,
    settings: Settings | None = None,
    provider: CompletionProvider | None = None,
) -> dict[str, Any]:
    if count != 6:
        raise ValueError("The first breadth cycle is fixed at exactly 6 hypotheses")
    settings = _gemini_settings(settings or Settings.from_env())
    model = provider or provider_for(settings)

    unrelated = connection.execute(
        """SELECT count(*) FROM hypothesis_cards
           WHERE status='discovered' AND generator<>?""",
        (CARD_GENERATOR,),
    ).fetchone()[0]
    if unrelated:
        raise RuntimeError("Unrelated discovered hypothesis cards exist; resolve them before first-cycle automation")

    existing = _existing_first_cycle_cards(connection)
    semantic_review: dict[str, Any] | None = None
    discovery_meta: dict[str, Any] = {}
    critic_meta: dict[str, Any] = {}

    if not existing:
        semantic_review = adjudicate_packet(
            connection, count=count, max_rounds=3, settings=settings, provider=model
        )
        if not semantic_review["gate"]["pass"]:
            _write_json(
                PROJECT_ROOT / "docs" / "generated" / "candidate_semantic_review.json",
                {key: value for key, value in semantic_review.items() if key != "final_packet"},
            )
            raise RuntimeError(
                "Candidate semantic review gate failed: " + ",".join(semantic_review["gate"]["reasons"])
            )
        connection.commit()

        context = semantic_review["final_packet"]
        proposed, discovery_meta = _propose(
            connection,
            context,
            requested=12,
            settings=settings,
            model=model,
            stage="first_cycle_hypothesis_discovery",
        )
        critiqued, critic_meta = _critic(
            proposed,
            failure_ledger=context.get("failure_ledger", []),
            settings=settings,
            model=model,
            stage="first_cycle_hypothesis_critic",
        )
        selected = _select_diverse(critiqued, count)

        if len(selected) < count:
            repair_needed = count - len(selected)
            repair_extra = {
                "need_replacements": repair_needed,
                "surviving_families": [item["family"] for item in critiqued],
                "surviving_fields": [name for item in critiqued for name in item["field_names"]],
                "critic_rejections": critic_meta.get("decisions", []),
                "constraints": {
                    "unique_fields": True,
                    "min_primary_themes": 5,
                    "min_datasets": 5,
                    "max_cards_per_dataset": 2,
                },
            }
            replacements, repair_meta = _propose(
                connection,
                context,
                requested=max(4, repair_needed * 2),
                settings=settings,
                model=model,
                stage="first_cycle_hypothesis_repair",
                extra=repair_extra,
            )
            repaired, repair_critic_meta = _critic(
                replacements,
                failure_ledger=context.get("failure_ledger", []),
                settings=settings,
                model=model,
                stage="first_cycle_hypothesis_repair_critic",
            )
            selected = _select_diverse(critiqued + repaired, count)
            discovery_meta["repair"] = repair_meta
            critic_meta["repair"] = repair_critic_meta

        if len(selected) != count:
            raise RuntimeError("Could not obtain 6 diverse critic-approved hypotheses after one repair call")

        _store_cards(
            connection,
            selected,
            settings=settings,
            discovery_meta=discovery_meta,
            critic_meta=critic_meta,
        )
        connection.commit()
        existing = _existing_first_cycle_cards(connection)
        _write_json(
            PROJECT_ROOT / "docs" / "generated" / "candidate_semantic_review.json",
            {
                "version": semantic_review["version"],
                "reviewed_unique": semantic_review["reviewed_unique"],
                "accept": semantic_review["accept"],
                "correct": semantic_review["correct"],
                "reject": semantic_review["reject"],
                "invalid": semantic_review["invalid"],
                "details": semantic_review["details"],
                "gate": semantic_review["gate"],
                "final_packet": {
                    "field_count": len(semantic_review["final_packet"]["candidate_fields"]),
                    "dataset_count": len({
                        item["dataset"] for item in semantic_review["final_packet"]["candidate_fields"]
                    }),
                    "theme_count": len({
                        item["theme"] for item in semantic_review["final_packet"]["candidate_fields"]
                    }),
                },
            },
        )

    if len(existing) != count:
        raise RuntimeError(
            f"Expected {count} first-cycle cards, found {len(existing)}. Resolve partial state before continuing."
        )

    discovered_count = sum(row["status"] == "discovered" for row in existing)
    if discovered_count:
        design_result = design(
            connection,
            limit=discovered_count,
            per_card=1,
            settings=settings,
            provider=model,
        )
    else:
        design_result = {"version": FIRST_CYCLE_VERSION, "cards": [], "accepted": 0, "rejected": 0}
    connection.commit()

    refreshed = _existing_first_cycle_cards(connection)
    audit = _dry_run_audit(
        connection,
        semantic_review=semantic_review,
        card_rows=refreshed,
        design_result=design_result,
        count=count,
    )
    _write_json(PROJECT_ROOT / "docs" / "generated" / "first_v2_hypothesis_dry_run.json", audit)
    connection.execute(
        "INSERT INTO research_events(artifact_id,event_type,payload_json,created_at) VALUES(NULL,?,?,?)",
        (
            "first_v2_hypothesis_dry_run",
            json_dumps({
                "ready_for_first_simulation": audit["batch"]["ready_for_first_simulation"],
                "accepted_hypotheses": audit["batch"]["accepted_hypothesis_count"],
                "accepted_plans": audit["batch"]["accepted_plan_count"],
                "brain_simulations_sent": 0,
            }),
            utc_now(),
        ),
    )
    return {
        "version": FIRST_CYCLE_VERSION,
        "semantic_review": None if semantic_review is None else {
            "accept": semantic_review["accept"],
            "correct": semantic_review["correct"],
            "reject": semantic_review["reject"],
            "gate": semantic_review["gate"],
        },
        "hypothesis_cards": [
            {
                "family": item["family"],
                "primary_theme": item["primary_theme"],
                "source_datasets": item["source_datasets"],
            }
            for item in audit["cards"]
        ],
        "design": {
            "accepted_this_run": design_result.get("accepted", 0),
            "rejected_this_run": design_result.get("rejected", 0),
        },
        "ready_for_first_simulation": audit["batch"]["ready_for_first_simulation"],
        "gate_reasons": audit["batch"]["gate_reasons"],
        "brain_simulations_sent": 0,
        "audit_path": "docs/generated/first_v2_hypothesis_dry_run.json",
    }


__all__ = ["FIRST_CYCLE_VERSION", "run_first_cycle"]
