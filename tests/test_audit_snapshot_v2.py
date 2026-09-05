import sqlite3
import unittest

from wq_alpha_os.db import DDL
from wq_alpha_os.research.audit_snapshot import build_agent_packet_audit, build_field_semantic_audit


class AuditSnapshotV2Tests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(DDL)
        rows = [
            ("f1", "value_field", "Value DS", "MATRIX", 95.0, "value", "ratio", "slow", "unknown", "dimensionless_or_ratio", 0.78),
            ("f2", "mystery_field", "Mystery DS", "MATRIX", 92.0, "generic", "level", "slow", "unknown", "unknown", 0.35),
        ]
        for key, name, dataset, data_type, coverage, theme, form, cadence, signedness, unit, confidence in rows:
            self.connection.execute(
                """INSERT INTO fields(
                    field_key,name,dataset_name,data_type,coverage,raw_json,updated_at
                ) VALUES(?,?,?,?,?,?,?)""",
                (key, name, dataset, data_type, coverage, "{}", "2026-09-05T00:00:00+00:00"),
            )
            self.connection.execute(
                """INSERT INTO field_profiles(
                    field_key,name,dataset_name,data_type,economic_theme,secondary_themes_json,semantic_form,
                    update_cadence,signedness,unit_family,sparsity_class,peer_dependence,direction_prior,
                    direction_confidence,horizon_prior_json,preferred_roles_json,discouraged_roles_json,
                    classification_source,confidence,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    key, name, dataset, data_type, theme, "[]", form, cadence, signedness, unit,
                    "slow_stepwise", "high", "ambiguous", "low", "[126,252,504,756]", "[]", "[]",
                    "deterministic_v2", confidence, "2026-09-05T00:00:00+00:00",
                ),
            )

    def tearDown(self):
        self.connection.close()

    def test_field_audit_surfaces_generic_unknown_and_low_confidence(self):
        audit = build_field_semantic_audit(self.connection)
        self.assertEqual(audit["total_profiles"], 2)
        self.assertEqual(audit["quality"]["generic_theme"]["count"], 1)
        self.assertEqual(audit["quality"]["unknown_unit"]["count"], 1)
        self.assertEqual(audit["quality"]["low_confidence_lt_0_70"]["count"], 1)
        self.assertEqual(audit["distributions"]["economic_theme"]["value"], 1)

    def test_agent_packet_audit_has_no_formula_surface(self):
        audit = build_agent_packet_audit(self.connection, count=1)
        self.assertFalse(audit["audit"]["contains_formula_surface"])
        self.assertEqual(audit["audit"]["forbidden_formula_keys"], [])
        self.assertGreaterEqual(audit["audit"]["candidate_field_count"], 1)


if __name__ == "__main__":
    unittest.main()
