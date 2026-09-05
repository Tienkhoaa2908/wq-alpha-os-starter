from __future__ import annotations

"""Export sanitized v2 calibration audits from the local SQLite database."""

from wq_alpha_os.db import initialize, session
from wq_alpha_os.research.audit_snapshot import write_audit_snapshots


def main() -> None:
    initialize()
    with session() as connection:
        result = write_audit_snapshots(connection, count=6)
    print(result)


if __name__ == "__main__":
    main()
