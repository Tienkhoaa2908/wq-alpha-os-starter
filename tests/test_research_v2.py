import sqlite3
import unittest

from wq_alpha_os.db import DDL
from wq_alpha_os.dsl.validator import validate_expression
from wq_alpha_os.research.field_profiles import materialize_field_profiles, stored_profile
from wq_alpha_os.research.knowledge_base import materialize_operator_profiles, materialize_path_templates
from wq_alpha_os.research.motifs import motif_fingerprint
from wq_alpha_os.research.operator_kb import active_operator_knowledge
from wq_alpha_os.research.path_templates import eligible_templates
from wq_alpha_os.research.plans import PlanRequest, compile_plan, resolve_request
from wq_alpha_os.research.scheduler import diagnose_run
from wq_alpha_os.research.scorer import score_vector


class ResearchV2Tests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(DDL)
        self.connection.execute(
            "INSERT INTO catalog_snapshots VALUES(?,?,?,?,?,?,?)",
            ("brain", "brain_api", "USA", "TOP3000", 1, "operators.json", "2026-09-05T00:00:00+00:00"),
        )
        for name, category, definition in (
            ("ts_rank", "Time Series", "ts_rank(x,d,constant=0)"),
            ("ts_decay_linear", "Time Series", "ts_decay_linear(x,d,dense=false)"),
            ("hump", "Time Series", "hump(x,hump=0.01)"),
            ("reverse", "Arithmetic", "reverse(x)"),
            ("inverse", "Arithmetic", "inverse(x)"),
            ("sign", "Arithmetic", "sign(x)"),
            ("group_rank", "Group", "group_rank(x,group)"),
            ("normalize", "Cross Sectional", "normalize(x,useStd=false,limit=0)"),
        ):
            self.connection.execute(
                "INSERT INTO operators VALUES(?,?,?,?,?,?,?,?)",
                (f"brain-{name}", name, category, definition, definition, "{}", "brain", "2026-09-05T00:00:00+00:00"),
            )
        self._field("value_factor_177", "Deep cash flow to price value factor", "MATRIX", "Model", 98.0)
        self._field("value_factor_222", "Independent cash flow to price value factor", "MATRIX", "Model", 97.0)
        self._field("analyst_revision", "Analyst estimate revision", "MATRIX", "Analyst", 96.0)
        self._field("news_vector", "News sentiment scores", "VECTOR", "News", 94.0)
        materialize_field_profiles(self.connection)

    def tearDown(self):
        self.connection.close()

    def _field(self, name, description, data_type, dataset, coverage):
        self.connection.execute(
            """INSERT INTO fields(
                field_key,field_id,name,dataset_id,dataset_name,category,description,data_type,
                region,universe_name,delay,coverage,date_coverage,alpha_count,semantic_theme,
                semantic_direction,raw_json,snapshot_id,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name, name, name, dataset, dataset, None, description, data_type, "USA", "TOP3000", 1,
             coverage, coverage, 0, None, None, "{}", "brain", "2026-09-05T00:00:00+00:00"),
        )

    def test_operator_semantics_separate_smoothing_from_position_control(self):
        kb = active_operator_knowledge(self.connection)
        self.assertEqual(kb["ts_decay_linear"].primary_role, "recency_weighted_smoothing")
        self.assertEqual(kb["hump"].primary_role, "position_change_limiter")
        self.assertNotEqual(kb["reverse"].primary_role, kb["inverse"].primary_role)
        self.assertNotEqual(kb["reverse"].primary_role, kb["sign"].primary_role)

    def test_field_profiles_drive_horizon_and_form(self):
        value = stored_profile(self.connection, "value_factor_177")
        analyst = stored_profile(self.connection, "analyst_revision")
        news = stored_profile(self.connection, "news_vector")
        self.assertEqual(value.update_cadence, "slow")
        self.assertIn(504, value.horizon_prior)
        self.assertEqual(analyst.update_cadence, "medium")
        self.assertEqual(news.data_type, "VECTOR")
        self.assertEqual(news.semantic_form, "vector_score")

    def test_path_eligibility_uses_field_type_and_semantics(self):
        value = stored_profile(self.connection, "value_factor_177")
        news = stored_profile(self.connection, "news_vector")
        value_paths = {item.id for item in eligible_templates([value])}
        news_paths = {item.id for item in eligible_templates([news])}
        self.assertIn("slow_level_peer", value_paths)
        self.assertIn("vector_event_novelty", news_paths)
        self.assertNotIn("slow_level_peer", news_paths)

    def test_plan_compiler_builds_valid_slow_level_expression(self):
        request = PlanRequest(
            template_id="slow_level_peer", field_names=("value_factor_177",),
            horizon_bucket="very_slow", direction="negative", group="industry",
        )
        plan = resolve_request(self.connection, request, family="test_value")
        expression = compile_plan(self.connection, plan)
        self.assertIn("ts_rank(value_factor_177", expression)
        self.assertIn("group_rank", expression)
        self.assertIn("reverse", expression)
        self.assertIn("normalize", expression)
        self.assertTrue(validate_expression(expression, self.connection).valid)

    def test_multi_horizon_is_marked_robustness_not_novelty(self):
        request = PlanRequest(
            template_id="multi_horizon_consensus", field_names=("value_factor_177",),
            horizon_bucket="very_slow", direction="negative", group="industry",
        )
        plan = resolve_request(self.connection, request, family="robustness")
        self.assertEqual(plan.novelty_class, "robustness")
        self.assertEqual(len(plan.windows), 2)
        self.assertIn("add(multiply", compile_plan(self.connection, plan))

    def test_parameter_fingerprint_keeps_field_identity_but_coarsens_windows(self):
        first = motif_fingerprint(
            self.connection,
            "normalize(reverse(group_rank(ts_rank(value_factor_177,504),industry)),useStd=true,limit=3)",
        )
        second = motif_fingerprint(
            self.connection,
            "normalize(reverse(group_rank(ts_rank(value_factor_177,756),industry)),useStd=true,limit=3)",
        )
        other_field = motif_fingerprint(
            self.connection,
            "normalize(reverse(group_rank(ts_rank(value_factor_222,756),industry)),useStd=true,limit=3)",
        )
        self.assertEqual(first.parameter_hash, second.parameter_hash)
        self.assertNotEqual(second.parameter_hash, other_field.parameter_hash)
        self.assertIn("value_factor_177", first.parameter_normalized)

    def test_high_correlation_routes_to_semantic_branch(self):
        row = {
            "platform_status": "COMPLETE", "checks_json": "[]", "sharpe": 1.43, "fitness": 0.98,
            "turnover": 0.028, "self_correlation": 0.9415, "annual_json": "[]",
        }
        diagnosis = diagnose_run(row)
        self.assertEqual(diagnosis.action, "BRANCH_SEMANTIC")
        self.assertEqual(diagnosis.allowed_change, "field_or_economic_mechanism")

    def test_multi_objective_score_penalizes_trials_and_high_corr(self):
        base = score_vector(
            {"sharpe": 1.4, "fitness": 1.05, "turnover": 0.1, "selfCorrelation": 0.3},
            [], novelty_score=0.9, effective_trial_count=1,
        )
        crowded = score_vector(
            {"sharpe": 1.4, "fitness": 1.05, "turnover": 0.1, "selfCorrelation": 0.95},
            [], novelty_score=0.2, effective_trial_count=100,
        )
        self.assertGreater(base["diversity"], crowded["diversity"])
        self.assertLess(base["trial_burden"], crowded["trial_burden"])

    def test_knowledge_registry_materializes(self):
        ops = materialize_operator_profiles(self.connection)
        templates = materialize_path_templates(self.connection)
        self.assertTrue(ops["complete"])
        self.assertEqual(templates["materialized"], 14)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM path_template_registry").fetchone()[0], 14)


if __name__ == "__main__":
    unittest.main()
