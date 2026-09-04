import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from wq_alpha_os.brain.simulation import payload_for, settings_hash
from wq_alpha_os.catalog import classify_field
from wq_alpha_os.db import DDL
from wq_alpha_os.research.proposer import parse_response
from wq_alpha_os.research.reviewer import review_pending
from wq_alpha_os.research.seeds import seed_family


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(DDL)
        self.connection.execute(
            """INSERT INTO fields(field_key,field_id,name,data_type,raw_json,updated_at)
               VALUES('x','x','mdl177_2_deepvaluefactor_ttmcfp','MATRIX','{}','now')"""
        )

    def tearDown(self):
        self.connection.close()

    def test_seed_is_repeatable_and_keeps_all_controlled_tests(self):
        first = seed_family(self.connection, "mdl177_2_deepvaluefactor_ttmcfp")
        second = seed_family(self.connection, "mdl177_2_deepvaluefactor_ttmcfp")
        self.assertEqual(sum(item.accepted for item in first), 8)
        self.assertEqual(sum(item.accepted for item in second), 0)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM alpha_artifacts").fetchone()[0], 8)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM hypotheses").fetchone()[0], 1)

    def test_provider_fence_is_parsed(self):
        data = parse_response('```json\n{"proposals": []}\n```')
        self.assertEqual(data, {"proposals": []})

    def test_simulation_payload_shape(self):
        payload = payload_for("rank(close)", {"region": "USA"})
        self.assertEqual(payload["type"], "REGULAR")
        self.assertEqual(payload["regular"], "rank(close)")

    def test_specific_semantics_precede_generic_model_label(self):
        self.assertEqual(classify_field("mdl_value_cashflow_factor", "model score")[0], "value_cashflow")

    def test_reviewer_is_the_only_promotion_gate(self):
        artifact_id = next(item.artifact_id for item in seed_family(
            self.connection, "mdl177_2_deepvaluefactor_ttmcfp") if item.accepted)
        expression = self.connection.execute("SELECT expression FROM alpha_artifacts WHERE id=?", (artifact_id,)).fetchone()[0]
        with tempfile.TemporaryDirectory() as directory:
            request_path = Path(directory) / "request.json"
            response_path = Path(directory) / "response.json"
            settings = {}
            request_path.write_text(json.dumps(payload_for(expression, settings)), encoding="utf-8")
            response_path.write_text(json.dumps({"alpha": {"is": {"sharpe": 1.5}}}), encoding="utf-8")
            self.connection.execute(
                """INSERT INTO simulation_runs(
                   id,artifact_id,settings_json,settings_hash,request_path,response_path,platform_status,sharpe,fitness,
                   turnover,self_correlation,checks_json,annual_json,started_at,finished_at)
                   VALUES('run',?,?,?,?,?,'COMPLETE',1.5,1.2,0.2,0.5,?,?, 'now','now')""",
                (artifact_id, json.dumps(settings), settings_hash(settings), str(request_path), str(response_path),
                 json.dumps([{"name": "LOW_SHARPE", "result": "PASS"}]), json.dumps({"records": [[2025, 1.5]]})),
            )
            reports = review_pending(self.connection)
            self.assertEqual(reports[0]["verdict"], "promote")
            status = self.connection.execute("SELECT status FROM alpha_artifacts WHERE id=?", (artifact_id,)).fetchone()[0]
            self.assertEqual(status, "promoted")


if __name__ == "__main__":
    unittest.main()
