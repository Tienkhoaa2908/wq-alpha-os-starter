import sqlite3
import unittest

from wq_alpha_os.db import DDL
from wq_alpha_os.dsl.specs import SPECS
from wq_alpha_os.operator_registry import (
    active_brain_operator_count,
    active_brain_operator_rows,
    audit_operator_registry,
    deduplicate_brain_operators,
)


class OperatorRegistryTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(DDL)
        self.connection.execute(
            "INSERT INTO catalog_snapshots VALUES(?,?,?,?,?,?,?)",
            ("old", "brain_api", "USA", "TOP3000", 1, "old/operators.json", "2026-01-01T00:00:00+00:00"),
        )
        self.connection.execute(
            "INSERT INTO catalog_snapshots VALUES(?,?,?,?,?,?,?)",
            ("latest", "brain_api", "USA", "TOP3000", 1, "latest/operators.json", "2026-02-01T00:00:00+00:00"),
        )

    def tearDown(self):
        self.connection.close()

    def _insert(self, key, name, category, snapshot="latest", description=""):
        self.connection.execute(
            "INSERT INTO operators VALUES(?,?,?,?,?,?,?,?)",
            (key, name, category, f"{name}(x)", description, "{}", snapshot, "2026-02-01T00:00:00+00:00"),
        )

    def test_active_count_does_not_double_count_typed_registry(self):
        self._insert("old-only", "old_only", "Arithmetic", snapshot="old")
        self._insert("brain-add", "add", "Arithmetic")
        self._insert("typed-add", "add", "typed_registry")
        self._insert("typed-std", "std", "typed_registry")
        self.assertEqual(active_brain_operator_count(self.connection), 1)

    def test_active_rows_deduplicate_by_name_and_prefer_brain(self):
        self._insert("brain-short", "rank", "Cross Sectional")
        self._insert("brain-rich", "RANK", "Cross Sectional", description="authoritative BRAIN row")
        self._insert("typed-rank", "rank", "typed_registry", description="typed metadata")
        rows = active_brain_operator_rows(self.connection)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["description"], "authoritative BRAIN row")

    def test_registry_only_operator_is_not_active(self):
        self._insert("typed-std", "std", "typed_registry")
        self.assertEqual(active_brain_operator_count(self.connection), 0)

    def test_raw_dedup_keeps_one_informative_brain_record(self):
        rows = [
            {"name": "rank", "category": "Cross Sectional"},
            {"name": "RANK", "category": "Cross Sectional", "definition": "rank(x)", "description": "Ranks x"},
        ]
        result = deduplicate_brain_operators(rows)
        self.assertEqual(result, [{"name": "rank", "category": "Cross Sectional", "definition": "rank(x)", "description": "Ranks x"}])

    def test_binary_comparisons_are_audited_outside_call_specs(self):
        rows = [
            {"name": "greater", "category": "Logical", "definition": "input1 > input2"},
            {"name": "less_equal", "category": "Logical", "definition": "input1 <= input2"},
            {"name": "add", "category": "Arithmetic", "definition": "add(x, y, filter=false)"},
        ]
        audit = audit_operator_registry(rows, SPECS)
        self.assertEqual(audit["logical_comparison_operators"], ["greater", "less_equal"])
        self.assertEqual(audit["call_operators"], 1)
        self.assertEqual(audit["brain_not_dsl"], [])


if __name__ == "__main__":
    unittest.main()
