import json
import sqlite3
import unittest

from wq_alpha_os.db import DDL
from wq_alpha_os.research.empirical import rebuild_motif_stats


class EmpiricalV2Tests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(DDL)
        self.connection.execute(
            """INSERT INTO alpha_artifacts(
                id,family,expression,canonical_expression,exact_hash,structural_hash,
                field_names_json,operator_names_json,rationale,generator,prompt_version,
                validation_json,complexity_nodes,complexity_depth,status,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "a1", "family", "rank(x)", "rank(x)", "exact-a1", "struct-a1",
                '["x"]', '["rank"]', "test", "test", "v2", "{}", 2, 2,
                "tested", "2026-09-05T00:00:00+00:00",
            ),
        )
        self.connection.execute(
            """INSERT INTO artifact_motifs(
                artifact_id,role_motif_hash,semantic_hash,parameter_hash,role_path_json,
                field_themes_json,field_forms_json,subtree_hashes_json,parameter_normalized,
                novelty_score,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "a1", "role-hash", "semantic-hash", "parameter-hash", '["peer_ordinal"]',
                '["value"]', '["ratio"]', "[]", "rank(x)", 1.0,
                "2026-09-05T00:00:00+00:00",
            ),
        )
        self.connection.execute(
            """INSERT INTO alpha_plans(
                id,family,template_id,request_json,resolved_json,compiler_version,status,
                artifact_id,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                "p1", "family", "slow_level_peer", "{}",
                json.dumps({"horizon_bucket": "very_slow"}), "v2", "validated", "a1",
                "2026-09-05T00:00:00+00:00",
            ),
        )
        self.connection.execute(
            """INSERT INTO simulation_runs(
                id,artifact_id,settings_json,settings_hash,platform_status,sharpe,fitness,
                turnover,self_correlation,checks_json,annual_json,started_at,finished_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "r1", "a1", "{}", "settings", "COMPLETE", 1.4, 1.1, 0.1, 0.3,
                "[]", "[]", "2026-09-05T00:00:00+00:00", "2026-09-05T00:01:00+00:00",
            ),
        )

    def tearDown(self):
        self.connection.close()

    def test_rebuild_reads_horizon_from_resolved_json_not_missing_sql_column(self):
        result = rebuild_motif_stats(self.connection)
        self.assertEqual(result, {"completed_runs": 1, "contexts": 1})
        row = self.connection.execute(
            "SELECT field_theme,horizon_bucket,completed_runs FROM motif_stats"
        ).fetchone()
        self.assertEqual(tuple(row), ("value", "very_slow", 1))


if __name__ == "__main__":
    unittest.main()
