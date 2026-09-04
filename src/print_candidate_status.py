from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path("data/db/wq_alpha_os.sqlite")


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    print("\n=== STATUS COUNTS ===")
    for status, n in cur.execute("SELECT COALESCE(status,'NULL'), COUNT(*) FROM alpha_candidates GROUP BY status ORDER BY COUNT(*) DESC"):
        print(f"{status:30s} {n}")

    print("\n=== FIRST SIMPLE ECON CANDIDATES ===")
    rows = cur.execute(
        """
        SELECT id, family, expression
        FROM alpha_candidates
        WHERE status = 'simple_econ_family'
        ORDER BY id DESC
        LIMIT 20
        """
    ).fetchall()
    for i, fam, expr in rows:
        print(f"\nID {i} | {fam}\n{expr}")

    conn.close()


if __name__ == "__main__":
    main()
