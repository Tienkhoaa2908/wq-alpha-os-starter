import json
import sqlite3
import unittest

from wq_alpha_os.db import DDL, json_dumps
from wq_alpha_os.research.knowledge import (
    build_discovery_context,
    failure_ledger,
    hypothesis_cards,
)


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(DDL)
        self._field("cashflow_yield", "value_cashflow", "reverse", "Fundamental", 96)
        self._field("news_signal", "sentiment", "ambiguous", "News", 93)
        self._field("option_skew", "options", "ambiguous", "Options", 91)
        self._artifact("old-value", "old_value", ["cashflow_yield"], ["ts_rank", "group_rank"])
        self.connection.execute(
            """INSERT INTO simulation_runs(
               id,artifact_id,settings_json,settings_hash,platform_status,sharpe,fitness,turnover,
               self_correlation,checks_json,annual_json,started_at,finished_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "run-1", "old-value", "{}", "settings", "COMPLETE", 0.4, 0.6, 0.15, 0.91,
                json_dumps([{"name": "LOW_FITNESS", "result": "FAIL"}]), "[]", "2026-01-01", "2026-01-02",
            ),
        )
        self.connection.execute(
            """INSERT INTO rejected_candidates(id,expression,family,reason,details_json,generator,created_at)
               VALUES(?,?,?,?,?,?,?)""",
            ("rejected-1", "rank(cashflow_yield)", "old_value", "near_duplicate", "{}", "test", "2026-01-03"),
        )

    def tearDown(self):
        self.connection.close()

    def _field(self, name, theme, direction, dataset, coverage):
        self.connection.execute(
            """INSERT INTO fields(
               field_key,field_id,name,dataset_name,description,data_type,coverage,semantic_theme,
               semantic_direction,raw_json,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (name, name, name, dataset, f"Mô tả {name}", "MATRIX", coverage, theme, direction, "{}", "now"),
        )

    def _artifact(self, artifact_id, family, fields, operators):
        self.connection.execute(
            """INSERT INTO alpha_artifacts(
               id,parent_id,hypothesis_id,family,expression,canonical_expression,exact_hash,structural_hash,
               field_names_json,operator_names_json,rationale,mutation,generator,model_name,prompt_hash,
               prompt_version,validation_json,complexity_nodes,complexity_depth,status,best_reward,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                artifact_id, None, None, family, "rank(cashflow_yield)", "rank(cashflow_yield)", artifact_id,
                artifact_id, json_dumps(fields), json_dumps(operators), "test", None, "test", None, None,
                "test", "{}", 2, 2, "tested", None, "now",
            ),
        )

    def test_failure_ledger_aggregates_metrics_and_lessons(self):
        ledger = failure_ledger(self.connection)
        simulation = next(item for item in ledger if item["origin"] == "simulation")
        self.assertEqual(simulation["family"], "old_value")
        self.assertIn("low_fitness", simulation["failure_modes"])
        self.assertIn("high_self_correlation", simulation["failure_modes"])
        self.assertEqual(simulation["metrics"]["fitness"]["best"], 0.6)
        self.assertTrue(simulation["lesson"])
        self.assertTrue(any(item["origin"] == "candidate_rejection" for item in ledger))

    def test_cards_prioritize_unexplored_themes_and_do_not_expose_expressions(self):
        cards = hypothesis_cards(self.connection, limit=3)
        self.assertEqual(cards[0]["novelty"], "chủ đề mới")
        self.assertTrue({"sentiment_news", "options"}.intersection({card["theme"] for card in cards}))
        self.assertNotIn("expression", cards[0])

    def test_context_is_json_serializable_and_obeys_normal_budget(self):
        context = build_discovery_context(self.connection, limit=3, max_chars=8000)
        payload = json.dumps(context, ensure_ascii=False)
        self.assertLessEqual(len(payload), 8000)
        self.assertEqual(context["version"], "discovery-v1")
        self.assertIn("failure_ledger", context)
        self.assertIn("hypothesis_cards", context)
        self.assertTrue(context["failure_ledger"])


if __name__ == "__main__":
    unittest.main()
