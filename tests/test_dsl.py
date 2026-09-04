import sqlite3
import unittest

from wq_alpha_os.db import DDL
from wq_alpha_os.dsl.fingerprint import fingerprint, similarity
from wq_alpha_os.dsl.validator import validate_expression


EXAMPLE = "normalize(add(multiply(0.75, hump(reverse(group_rank(ts_rank(mdl177_2_deepvaluefactor_ttmcfp, 504), industry)), hump=0.01)), multiply(0.25, reverse(group_rank(ts_rank(mdl177_2_deepvaluefactor_ttmcfp, 252), industry))), filter=true), useStd=true, limit=3)"


class DslTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.executescript(DDL)
        self.connection.execute(
            """INSERT INTO fields(field_key,field_id,name,data_type,raw_json,updated_at)
               VALUES('x','x','mdl177_2_deepvaluefactor_ttmcfp','MATRIX','{}','now')"""
        )

    def tearDown(self):
        self.connection.close()

    def test_user_example_is_valid(self):
        report = validate_expression(EXAMPLE, self.connection)
        self.assertTrue(report.valid, report.issues)
        self.assertIn("hump", report.fingerprint.operators)
        self.assertEqual(report.fingerprint.fields, ("mdl177_2_deepvaluefactor_ttmcfp",))

    def test_unknown_field_is_rejected(self):
        report = validate_expression("rank(made_up_field)", self.connection)
        self.assertFalse(report.valid)

    def test_fingerprint_normalizes_case_and_spacing(self):
        self.assertEqual(fingerprint("RANK( x )").exact_hash, fingerprint("rank(x)").exact_hash)

    def test_sensitivity_is_near_duplicate(self):
        left = fingerprint("rank(ts_rank(x,252))")
        right = fingerprint("rank(ts_rank(x,504))")
        self.assertGreaterEqual(similarity(left, right), 0.9)


if __name__ == "__main__":
    unittest.main()
