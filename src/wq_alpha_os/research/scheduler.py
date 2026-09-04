from __future__ import annotations

import math
import sqlite3


def choose_family(connection: sqlite3.Connection) -> str | None:
    rows = connection.execute("SELECT family,completed_runs,total_reward FROM family_stats").fetchall()
    if not rows:
        row = connection.execute(
            "SELECT family FROM alpha_artifacts WHERE status!='legacy_unverified' GROUP BY family ORDER BY count(*) DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else None
    total = max(1, sum(int(row[1]) for row in rows))
    best = max(rows, key=lambda row: float("inf") if int(row[1]) == 0 else float(row[2]) / int(row[1]) + math.sqrt(2 * math.log(total) / int(row[1])))
    return str(best[0])


def mutation_hint(row: sqlite3.Row) -> str:
    turnover = row["turnover"]
    sharpe = row["sharpe"]
    if turnover is not None and turnover > 0.7:
        return "Giảm vòng quay: thêm hump hoặc tăng khung thời gian; chỉ đổi một yếu tố."
    if sharpe is not None and sharpe < 0:
        return "Kiểm tra hướng kinh tế bằng reverse; không đồng thời đổi cấu trúc."
    return "Thử loại bỏ một nhánh để đo đóng góp, hoặc thay một khung thời gian có lý do."
