from __future__ import annotations

"""Export sanitized coordination state from local SQLite into tracked docs."""

from wq_alpha_os.db import initialize, session
from wq_alpha_os.research.state_snapshot import write_snapshot


def main() -> None:
    initialize()
    with session() as connection:
        result = write_snapshot(connection)
    print(result)


if __name__ == "__main__":
    main()
