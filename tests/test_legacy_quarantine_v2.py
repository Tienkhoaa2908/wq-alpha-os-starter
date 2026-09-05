import sqlite3
import unittest

from wq_alpha_os.db import DDL
from wq_alpha_os.research.motifs import backfill_motifs


class LegacyQuarantineV2Tests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(DDL)

    def tearDown(self):
        self.connection.close()

    def _artifact(self, artifact_id: str, expression: str, status: str) -> None:
        self.connection.execute(
            """INSERT INTO alpha_artifacts(
                id,parent_id,hypothesis_id,family,expression,canonical_expression,exact_hash,structural_hash,
                field_names_json,operator_names_json,rationale,mutation,generator,model_name,prompt_hash,
                prompt_version,validation_json,complexity_nodes,complexity_depth,status,best_reward,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                artifact_id, None, None, "test", expression, expression, f"exact-{artifact_id}",
                f"struct-{artifact_id}", "[]", "[]", "test", None, "test", None, None, "v2", "{}",
                2, 2, status, None, f"2026-09-05T00:00:0{artifact_id[-1]}+00:00",
            ),
        )

    def test_backfill_rebuilds_memory_without_legacy_unverified(self):
        self._artifact("artifact-1", "reverse(foo)", "legacy_unverified")
        self._artifact("artifact-2", "reverse(bar)", "tested")

        result = backfill_motifs(self.connection)

        self.assertEqual(result["excluded_legacy"], 1)
        self.assertEqual(result["materialized"], 1)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM artifact_motifs").fetchone()[0], 1)
        kept = self.connection.execute("SELECT artifact_id FROM artifact_motifs").fetchone()[0]
        self.assertEqual(kept, "artifact-2")
        self.assertGreater(self.connection.execute("SELECT count(*) FROM subtree_stats").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
