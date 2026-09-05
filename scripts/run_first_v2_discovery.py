from __future__ import annotations

"""Run the first reviewed v2 breadth cycle locally, without BRAIN simulation."""

import argparse
import json

from wq_alpha_os.config import Settings
from wq_alpha_os.db import initialize, session
from wq_alpha_os.research.first_cycle import run_first_cycle


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=6)
    args = parser.parse_args()

    initialize()
    settings = Settings.from_env()
    with session() as connection:
        result = run_first_cycle(connection, count=args.count, settings=settings)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
