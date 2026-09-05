import json
import unittest

from wq_alpha_os.research.empirical import _annual_min
from wq_alpha_os.research.recordsets import annual_sharpes, decode_recordset
from wq_alpha_os.research.scheduler import diagnose_run
from wq_alpha_os.research.state_snapshot import _annual_summary


RECORDSET = {
    "schema": {
        "properties": [
            {"name": "stage"},
            {"name": "year"},
            {"name": "sharpe"},
            {"name": "pnl"},
        ]
    },
    "records": [
        {"value": ["IS", 2021, 1.2, 10.0], "Count": 1},
        {"value": ["IS", 2022, -0.4, -3.0], "Count": 1},
        {"value": ["OS", 2022, 9.9, 99.0], "Count": 1},
    ],
}


class RecordsetV2Tests(unittest.TestCase):
    def test_current_brain_schema_records_are_decoded(self):
        rows = decode_recordset(RECORDSET)
        self.assertEqual(rows[0]["stage"], "IS")
        self.assertEqual(rows[0]["year"], 2021)
        self.assertEqual(rows[1]["sharpe"], -0.4)

    def test_annual_sharpes_ignore_out_of_sample_rows(self):
        self.assertEqual(annual_sharpes(RECORDSET), [1.2, -0.4])

    def test_snapshot_and_empirical_memory_use_same_yearly_evidence(self):
        raw = json.dumps(RECORDSET)
        self.assertEqual(
            _annual_summary(raw),
            {"years": 2, "positive_sharpe_years": 1, "min_sharpe": -0.4},
        )
        self.assertEqual(_annual_min(raw), -0.4)

    def test_scheduler_sees_negative_year_from_recordset_shape(self):
        diagnosis = diagnose_run({
            "platform_status": "COMPLETE",
            "checks_json": "[]",
            "sharpe": 1.30,
            "fitness": 1.10,
            "turnover": 0.10,
            "self_correlation": 0.20,
            "annual_json": json.dumps(RECORDSET),
        })
        self.assertEqual(diagnosis.action, "ROBUSTNESS_BRANCH")
        self.assertEqual(diagnosis.failure_mode, "annual_instability")


if __name__ == "__main__":
    unittest.main()
