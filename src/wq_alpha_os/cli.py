from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from .brain.client import BrainClient
from .brain.simulation import plan, refresh_analytics, run_pending
from .catalog import import_brain_snapshot, import_legacy, sync_from_brain
from .config import Settings
from .db import initialize, session
from .dsl.validator import validate_expression
from .exporter import export_csv
from .research.agentic_v2 import design as agent_design
from .research.agentic_v2 import discover as agent_discover
from .research.agentic_v2 import packet as agent_packet
from .research.agentic_v2 import run_cycle as agent_run_cycle
from .research.prompts import build_prompt
from .research.proposer import ingest_proposals, parse_response, propose, write_prompt_packet
from .research.reviewer import review_pending
from .research.seeds import seed_family
from .research.semantic_validator import validate_semantics


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _result_counts(results: list[Any]) -> dict[str, Any]:
    return {
        "accepted": sum(bool(item.accepted) for item in results),
        "rejected": sum(not bool(item.accepted) for item in results),
        "details": [item.__dict__ for item in results],
    }


def cmd_init(_: argparse.Namespace) -> None:
    path = initialize()
    _print({"ok": True, "database": str(path)})


def cmd_catalog(args: argparse.Namespace) -> None:
    initialize()
    if args.catalog_command == "import-legacy":
        result = import_legacy(Path(args.source).resolve())
    elif args.catalog_command == "import-snapshot":
        result = import_brain_snapshot(Path(args.source).resolve(), None, args.region, args.universe, args.delay)
    else:
        result = sync_from_brain(BrainClient(), None, args.region, args.universe, args.delay)
    _print(result)


def cmd_seed(args: argparse.Namespace) -> None:
    initialize()
    with session() as connection:
        exists = connection.execute("SELECT 1 FROM fields WHERE lower(name)=lower(?)", (args.field,)).fetchone()
        if not exists:
            raise SystemExit(f"Không có trường {args.field}; hãy nhập hoặc đồng bộ danh mục trước.")
        results = seed_family(connection, args.field)
    _print(_result_counts(results))


def cmd_validate(args: argparse.Namespace) -> None:
    initialize()
    with session() as connection:
        dsl = validate_expression(args.expression, connection)
        semantic = validate_semantics(args.expression, connection)
    _print({"valid": dsl.valid and semantic.valid, "dsl": dsl.to_dict(), "semantic": semantic.to_dict()})


def cmd_prompt(args: argparse.Namespace) -> None:
    """Legacy direct-expression prompt packet; retained only for reproducibility."""
    initialize()
    with session() as connection:
        packet = build_prompt(connection, args.count)
        path = write_prompt_packet(packet, Path(args.output).resolve() if args.output else None)
    _print({"legacy": True, "ok": True, "path": str(path), "prompt_hash": packet.prompt_hash})


def cmd_propose(args: argparse.Namespace) -> None:
    """Legacy direct-expression proposer; v2 users should use `agent` instead."""
    initialize()
    settings = Settings.from_env()
    if args.provider:
        settings = replace(settings, llm_provider=args.provider.replace("-", "_"))
    with session() as connection:
        path, results = propose(connection, args.count, settings)
    _print({"legacy": True, "response_path": str(path), **_result_counts(results)})


def cmd_ingest(args: argparse.Namespace) -> None:
    initialize()
    path = Path(args.file).resolve()
    data = parse_response(path.read_text(encoding="utf-8"))
    with session() as connection:
        results = ingest_proposals(connection, data, generator="manual_or_codex")
    _print(_result_counts(results))


def cmd_candidates(args: argparse.Namespace) -> None:
    initialize()
    with session() as connection:
        rows = connection.execute(
            """SELECT id,parent_id,family,status,best_reward,expression,rationale,created_at
               FROM alpha_artifacts WHERE (?='all' OR status=?)
               ORDER BY coalesce(best_reward,-999) DESC,created_at DESC LIMIT ?""",
            (args.status, args.status, args.limit),
        ).fetchall()
        _print([dict(row) for row in rows])


def cmd_simulate(args: argparse.Namespace) -> None:
    initialize()
    with session() as connection:
        if args.dry_run:
            _print({"dry_run": True, "requests": plan(connection, args.limit)})
        else:
            _print(run_pending(connection, args.limit))


def cmd_review(args: argparse.Namespace) -> None:
    initialize()
    with session() as connection:
        _print(review_pending(connection, args.limit))


def cmd_refresh(args: argparse.Namespace) -> None:
    initialize()
    with session() as connection:
        _print(refresh_analytics(connection, args.limit))


def cmd_export(args: argparse.Namespace) -> None:
    initialize()
    output = Path(args.output).resolve()
    with session() as connection:
        count = export_csv(connection, output, args.status, args.limit)
    _print({"ok": True, "rows": count, "path": str(output)})


def cmd_status(_: argparse.Namespace) -> None:
    from .operator_registry import active_brain_operator_count

    initialize()
    with session() as connection:
        tables = (
            "datasets", "fields", "operators", "operator_profiles", "field_profiles", "path_template_registry",
            "hypotheses", "hypothesis_cards", "alpha_plans", "alpha_artifacts", "artifact_motifs",
            "rejected_candidates", "simulation_runs", "reviews", "motif_stats",
        )
        counts = {name: connection.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in tables}
        counts["operators"] = active_brain_operator_count(connection)
        statuses = {row[0]: row[1] for row in connection.execute("SELECT status,count(*) FROM alpha_artifacts GROUP BY status")}
        families = [dict(row) for row in connection.execute(
            """SELECT f.family,f.completed_runs,f.total_reward,f.best_reward,f.last_artifact_id,
                      coalesce(t.effective_trial_count,0) effective_trial_count,
                      coalesce(t.semantic_branches,0) semantic_branches,
                      coalesce(t.parameter_only_trials,0) parameter_only_trials,
                      coalesce(t.stopped,0) stopped,t.stop_reason
               FROM family_stats f LEFT JOIN family_trial_stats t ON t.family=f.family
               ORDER BY f.best_reward DESC"""
        )]
    _print({"counts": counts, "artifact_statuses": statuses, "family_stats": families})


def cmd_run(args: argparse.Namespace) -> None:
    from .research.orchestrator import run_cycle

    initialize()
    settings = Settings.from_env()
    if args.provider:
        settings = replace(settings, llm_provider=args.provider.replace("-", "_"))
    with session() as connection:
        _print(run_cycle(connection, args.budget, settings=settings, simulate=not getattr(args, "no_simulate", False)))


def cmd_agent(args: argparse.Namespace) -> None:
    initialize()
    with session() as connection:
        if args.agent_command == "packet":
            result = agent_packet(connection, args.count)
        elif args.agent_command == "discover":
            result = agent_discover(connection, args.count)
        elif args.agent_command == "design":
            result = agent_design(connection, args.limit, per_card=args.per_card)
        else:
            result = agent_run_cycle(connection, args.count, per_card=args.per_card)
    _print(result)


def cmd_knowledge(args: argparse.Namespace) -> None:
    from .research.field_review import review_ambiguous_fields
    from .research.knowledge_base import rebuild_all
    from .research.operator_kb import assert_semantic_coverage

    initialize()
    with session() as connection:
        if args.knowledge_command == "build":
            result = rebuild_all(connection)
        elif args.knowledge_command == "operators":
            result = {
                "coverage": assert_semantic_coverage(connection),
                "rows": [dict(row) for row in connection.execute(
                    "SELECT * FROM operator_profiles WHERE active=1 ORDER BY operator_name LIMIT ?", (args.limit,)
                )],
            }
        elif args.knowledge_command == "fields":
            result = [dict(row) for row in connection.execute(
                "SELECT * FROM field_profiles ORDER BY confidence DESC,name LIMIT ?", (args.limit,)
            )]
        elif args.knowledge_command == "review-fields":
            result = review_ambiguous_fields(connection, args.limit)
        else:
            result = [dict(row) for row in connection.execute(
                "SELECT * FROM motif_stats ORDER BY completed_runs DESC,pass_rate DESC LIMIT ?", (args.limit,)
            )]
    _print(result)


def cmd_research(args: argparse.Namespace) -> None:
    from .research.scheduler import controlled_cycle_plan, diagnose_run

    initialize()
    with session() as connection:
        if args.research_command == "cycle-plan":
            result = controlled_cycle_plan(connection, args.budget)
        else:
            rows = connection.execute(
                """SELECT a.id artifact_id,a.family,a.expression,r.* FROM alpha_artifacts a
                   JOIN simulation_runs r ON r.artifact_id=a.id
                   ORDER BY coalesce(r.finished_at,r.started_at) DESC LIMIT ?""", (args.limit,)
            ).fetchall()
            result = [
                {"artifact_id": row["artifact_id"], "family": row["family"], **diagnose_run(row).to_dict()}
                for row in rows
            ]
    _print(result)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="alpha-os", description="Hệ thống nghiên cứu alpha theo bằng chứng")
    sub = root.add_subparsers(dest="command", required=True)

    item = sub.add_parser("init", help="Khởi tạo/nâng cấp cơ sở dữ liệu")
    item.set_defaults(func=cmd_init)

    item = sub.add_parser("catalog", help="Nhập hoặc đồng bộ danh mục")
    child = item.add_subparsers(dest="catalog_command", required=True)
    legacy = child.add_parser("import-legacy", help="Nhập cơ sở dữ liệu cũ")
    legacy.add_argument("--source", default="data/db/legacy_wq_alpha_os.sqlite")
    legacy.set_defaults(func=cmd_catalog)
    snapshot = child.add_parser("import-snapshot", help="Nhập bản chụp BRAIN đã tải")
    snapshot.add_argument("--source", required=True)
    snapshot.add_argument("--region", default="USA")
    snapshot.add_argument("--universe", default="TOP3000")
    snapshot.add_argument("--delay", type=int, default=1)
    snapshot.set_defaults(func=cmd_catalog)
    sync = child.add_parser("sync", help="Đồng bộ từ tài khoản BRAIN")
    sync.add_argument("--region", default="USA")
    sync.add_argument("--universe", default="TOP3000")
    sync.add_argument("--delay", type=int, default=1)
    sync.set_defaults(func=cmd_catalog)

    item = sub.add_parser("seed", help="Tạo họ alpha nền cũ (tương thích lịch sử)")
    item.add_argument("--field", required=True)
    item.set_defaults(func=cmd_seed)
    item = sub.add_parser("validate", help="Kiểm tra cú pháp, kiểu và ngữ nghĩa một biểu thức")
    item.add_argument("expression")
    item.set_defaults(func=cmd_validate)

    item = sub.add_parser("prompt", help="[cũ] Xuất gói câu nhắc sinh biểu thức trực tiếp")
    item.add_argument("--count", type=int, default=8)
    item.add_argument("--output")
    item.set_defaults(func=cmd_prompt)
    item = sub.add_parser("propose", help="[cũ] Gọi mô hình sinh FASTEXPR trực tiếp; không dùng cho v2")
    item.add_argument("--count", type=int, default=8)
    item.add_argument("--provider", choices=("gemini", "ollama", "openai-compatible"))
    item.set_defaults(func=cmd_propose)
    item = sub.add_parser("ingest-proposals", help="Nhập phản hồi JSON thủ công/cũ")
    item.add_argument("file")
    item.set_defaults(func=cmd_ingest)

    item = sub.add_parser("candidates", help="Liệt kê alpha")
    item.add_argument("--status", default="all")
    item.add_argument("--limit", type=int, default=30)
    item.set_defaults(func=cmd_candidates)
    item = sub.add_parser("simulate", help="Mô phỏng alpha đã xác thực")
    item.add_argument("--limit", type=int, default=5)
    item.add_argument("--dry-run", action="store_true")
    item.set_defaults(func=cmd_simulate)
    item = sub.add_parser("review", help="Đánh giá độc lập kết quả đã có")
    item.add_argument("--limit", type=int, default=20)
    item.set_defaults(func=cmd_review)
    item = sub.add_parser("refresh", help="Lấy lại thống kê theo năm và tương quan")
    item.add_argument("--limit", type=int, default=20)
    item.set_defaults(func=cmd_refresh)
    item = sub.add_parser("export", help="Xuất CSV có đường dẫn điền sẵn")
    item.add_argument("--output", default="data/exports/alpha_candidates.csv")
    item.add_argument("--status", default="promoted")
    item.add_argument("--limit", type=int, default=200)
    item.set_defaults(func=cmd_export)
    item = sub.add_parser("status", help="Xem trạng thái kho nghiên cứu")
    item.set_defaults(func=cmd_status)

    item = sub.add_parser("run", help="Chạy một vòng nghiên cứu v2 đầy đủ")
    item.add_argument("--budget", type=int, default=12)
    item.add_argument("--provider", choices=("gemini", "ollama", "openai-compatible"))
    item.add_argument("--no-simulate", action="store_true", help="Chỉ tạo/biên dịch ứng viên; không gửi BRAIN")
    item.set_defaults(func=cmd_run)

    item = sub.add_parser("agent", help="Tác nhân v2: giả thuyết -> AlphaPlan -> biên dịch cục bộ")
    child = item.add_subparsers(dest="agent_command", required=True)
    child_packet = child.add_parser("packet", help="Xuất gói khám phá, không gọi Gemini")
    child_packet.add_argument("--count", type=int, default=6)
    child_packet.set_defaults(func=cmd_agent)
    child_discover = child.add_parser("discover", help="Gọi Gemini chỉ để sinh thẻ giả thuyết")
    child_discover.add_argument("--count", type=int, default=6)
    child_discover.set_defaults(func=cmd_agent)
    child_design = child.add_parser("design", help="Gemini chỉ chọn AlphaPlan; code tự biên dịch FASTEXPR")
    child_design.add_argument("--limit", type=int, default=6)
    child_design.add_argument("--per-card", type=int, default=1)
    child_design.set_defaults(func=cmd_agent)
    child_cycle = child.add_parser("run", help="Khám phá và thiết kế v2; không mô phỏng")
    child_cycle.add_argument("--count", type=int, default=6)
    child_cycle.add_argument("--per-card", type=int, default=1)
    child_cycle.set_defaults(func=cmd_agent)

    item = sub.add_parser("knowledge", help="Cơ sở tri thức toán tử/trường/motif")
    child = item.add_subparsers(dest="knowledge_command", required=True)
    child_build = child.add_parser("build", help="Vật chất hóa tri thức cục bộ; không gọi mạng")
    child_build.set_defaults(func=cmd_knowledge)
    child_ops = child.add_parser("operators", help="Xem hồ sơ ngữ nghĩa toán tử")
    child_ops.add_argument("--limit", type=int, default=100)
    child_ops.set_defaults(func=cmd_knowledge)
    child_fields = child.add_parser("fields", help="Xem hồ sơ ngữ nghĩa trường")
    child_fields.add_argument("--limit", type=int, default=50)
    child_fields.set_defaults(func=cmd_knowledge)
    child_review = child.add_parser("review-fields", help="Gemini rà soát chỉ các trường mơ hồ; không sinh alpha")
    child_review.add_argument("--limit", type=int, default=20)
    child_review.set_defaults(func=cmd_knowledge)
    child_motifs = child.add_parser("motifs", help="Xem thống kê motif thực nghiệm")
    child_motifs.add_argument("--limit", type=int, default=50)
    child_motifs.set_defaults(func=cmd_knowledge)

    item = sub.add_parser("research", help="Lập kế hoạch nghiên cứu theo bằng chứng; không tự mô phỏng")
    child = item.add_subparsers(dest="research_command", required=True)
    child_cycle_plan = child.add_parser("cycle-plan", help="Chia ngân sách 50/25/25 cho vòng nghiên cứu")
    child_cycle_plan.add_argument("--budget", type=int, default=12)
    child_cycle_plan.set_defaults(func=cmd_research)
    child_diag = child.add_parser("diagnose", help="Chẩn đoán dạng thất bại của các mô phỏng gần nhất")
    child_diag.add_argument("--limit", type=int, default=20)
    child_diag.set_defaults(func=cmd_research)
    return root


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = parser().parse_args()
    args.func(args)
