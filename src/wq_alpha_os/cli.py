from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .brain.client import BrainClient
from .brain.simulation import plan, run_pending
from .catalog import import_legacy, sync_from_brain
from .config import PROJECT_ROOT, Settings
from .db import initialize, json_dumps, session
from .dsl.validator import validate_expression
from .exporter import export_csv
from .research.prompts import build_prompt
from .research.proposer import ingest_proposals, parse_response, propose, write_prompt_packet
from .research.reviewer import review_pending
from .research.seeds import seed_family


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
    else:
        client = BrainClient()
        result = sync_from_brain(client, None, args.region, args.universe, args.delay)
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
        _print(validate_expression(args.expression, connection).to_dict())


def cmd_prompt(args: argparse.Namespace) -> None:
    initialize()
    with session() as connection:
        packet = build_prompt(connection, args.count)
        path = write_prompt_packet(packet, Path(args.output).resolve() if args.output else None)
    _print({"ok": True, "path": str(path), "prompt_hash": packet.prompt_hash})


def cmd_propose(args: argparse.Namespace) -> None:
    initialize()
    with session() as connection:
        path, results = propose(connection, args.count)
    _print({"response_path": str(path), **_result_counts(results)})


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


def cmd_export(args: argparse.Namespace) -> None:
    initialize()
    output = Path(args.output).resolve()
    with session() as connection:
        count = export_csv(connection, output, args.status, args.limit)
    _print({"ok": True, "rows": count, "path": str(output)})


def cmd_status(_: argparse.Namespace) -> None:
    initialize()
    with session() as connection:
        tables = ("datasets", "fields", "operators", "hypotheses", "alpha_artifacts", "rejected_candidates", "simulation_runs", "reviews")
        counts = {name: connection.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in tables}
        statuses = {row[0]: row[1] for row in connection.execute("SELECT status,count(*) FROM alpha_artifacts GROUP BY status")}
        families = [dict(row) for row in connection.execute(
            "SELECT family,completed_runs,total_reward,best_reward,last_artifact_id FROM family_stats ORDER BY best_reward DESC"
        )]
    _print({"counts": counts, "artifact_statuses": statuses, "family_stats": families})


def cmd_run(args: argparse.Namespace) -> None:
    from .research.orchestrator import run_cycle
    initialize()
    with session() as connection:
        _print(run_cycle(connection, args.budget))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="alpha-os", description="Dây chuyền nghiên cứu alpha có bằng chứng")
    sub = root.add_subparsers(dest="command", required=True)
    item = sub.add_parser("init", help="Khởi tạo cơ sở dữ liệu")
    item.set_defaults(func=cmd_init)

    item = sub.add_parser("catalog", help="Nhập hoặc đồng bộ danh mục")
    child = item.add_subparsers(dest="catalog_command", required=True)
    legacy = child.add_parser("import-legacy", help="Nhập cơ sở dữ liệu cũ")
    legacy.add_argument("--source", default="data/db/legacy_wq_alpha_os.sqlite")
    legacy.set_defaults(func=cmd_catalog)
    sync = child.add_parser("sync", help="Đồng bộ từ tài khoản BRAIN")
    sync.add_argument("--region", default="USA")
    sync.add_argument("--universe", default="TOP3000")
    sync.add_argument("--delay", type=int, default=1)
    sync.set_defaults(func=cmd_catalog)

    item = sub.add_parser("seed", help="Tạo họ alpha nền")
    item.add_argument("--field", required=True)
    item.set_defaults(func=cmd_seed)
    item = sub.add_parser("validate", help="Kiểm tra một biểu thức")
    item.add_argument("expression")
    item.set_defaults(func=cmd_validate)
    item = sub.add_parser("prompt", help="Xuất gói câu nhắc cho Codex hoặc mô hình khác")
    item.add_argument("--count", type=int, default=8)
    item.add_argument("--output")
    item.set_defaults(func=cmd_prompt)
    item = sub.add_parser("propose", help="Gọi mô hình tương thích giao diện OpenAI")
    item.add_argument("--count", type=int, default=8)
    item.add_argument("--provider", default="ollama", choices=("ollama", "openai-compatible"))
    item.set_defaults(func=cmd_propose)
    item = sub.add_parser("ingest-proposals", help="Nhập phản hồi JSON từ mô hình")
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
    item = sub.add_parser("export", help="Xuất CSV có đường dẫn điền sẵn")
    item.add_argument("--output", default="data/exports/alpha_candidates.csv")
    item.add_argument("--status", default="promoted")
    item.add_argument("--limit", type=int, default=200)
    item.set_defaults(func=cmd_export)
    item = sub.add_parser("status", help="Xem trạng thái kho nghiên cứu")
    item.set_defaults(func=cmd_status)
    item = sub.add_parser("run", help="Chạy một vòng sinh, mô phỏng và đánh giá")
    item.add_argument("--budget", type=int, default=8)
    item.add_argument("--provider", default="ollama", choices=("ollama", "openai-compatible"))
    item.set_defaults(func=cmd_run)
    return root


def main() -> None:
    args = parser().parse_args()
    args.func(args)
