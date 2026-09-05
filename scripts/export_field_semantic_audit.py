from __future__ import annotations

import json

from wq_alpha_os.config import PROJECT_ROOT
from wq_alpha_os.db import initialize, session
from wq_alpha_os.research.audit_snapshot import build_field_semantic_audit


def main() -> None:
    initialize()
    with session() as connection:
        payload = build_field_semantic_audit(connection)
    path = PROJECT_ROOT / "docs" / "generated" / "field_semantic_audit.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print({"path": str(path), "total_profiles": payload["total_profiles"]})


if __name__ == "__main__":
    main()
