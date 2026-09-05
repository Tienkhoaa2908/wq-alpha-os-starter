import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from wq_alpha_os.db import DDL
from wq_alpha_os.research.state_snapshot import build_state, write_snapshot


class StateSnapshotV2Tests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(DDL)
        self.connection.execute(
            """INSERT INTO alpha_artifacts(
                id,parent_id,hypothesis_id,family,expression,canonical_expression,exact_hash,structural_hash,
                field_names_json,operator_names_json,rationale,mutation,generator,model_name,prompt_hash,
                prompt_version,validation_json,complexity_nodes,complexity_depth,status,best_reward,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "legacy", None, None, "legacy", "reverse(foo)", "reverse(foo)", "exact-legacy", "struct-legacy",
                "[]", "[]", "legacy", None, "old_gemini", None, None, "v1", "{}", 2, 2,
                "legacy_unverified", None, "2026-09-05T00:00:00+00:00",
            ),
        )
        self.connection.execute(
            """INSERT INTO alpha_artifacts(
                id,parent_id,hypothesis_id,family,expression,canonical_expression,exact_hash,structural_hash,
                field_names_json,operator_names_json,rationale,mutation,generator,model_name,prompt_hash,
                prompt_version,validation_json,complexity_nodes,complexity_depth,status,best_reward,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "tested", None, None, "value", "reverse(bar)", "reverse(bar)", "exact-tested", "struct-tested",
                "[]", "[]", "tested", None, "v2", None, None, "v2", "{}", 2, 2,
                "tested", None, "2026-09-05T00:00:01+00:00",
            ),
        )

    def tearDown(self):
        self.connection.close()

    def test_state_reports_legacy_separately_from_research_eligible(self):
        state = build_state(self.connection)
        self.assertEqual(state["research"]["artifacts_total"], 2)
        self.assertEqual(state["research"]["legacy_unverified_quarantined"], 1)
        self.assertEqual(state["research"]["artifacts_research_eligible"], 1)

    def test_write_snapshot_creates_json_and_markdown(self):
        with TemporaryDirectory() as tmp:
            json_path = Path(tmp) / "state.json"
            md_path = Path(tmp) / "state.md"
            result = write_snapshot(self.connection, json_path=json_path, markdown_path=md_path)
            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())
            self.assertEqual(result["legacy_quarantined"], 1)
            self.assertIn("Legacy Gemini", md_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
