from __future__ import annotations

from collections import Counter
from dataclasses import replace
import json
import sqlite3
import unittest

from wq_alpha_os.db import DDL
from wq_alpha_os.research.audit_snapshot import build_agent_packet_audit
from wq_alpha_os.research.discovery_v2 import build_discovery_context
from wq_alpha_os.research.field_profiles import profile_row
from wq_alpha_os.research.field_review import THEMES as REVIEW_THEMES
from wq_alpha_os.research.field_review import _rows as review_rows
from wq_alpha_os.research.knowledge import THEME_TEMPLATES
from wq_alpha_os.research.path_templates import PATH_TEMPLATES, eligible_templates
from wq_alpha_os.research.scheduler import (
    controlled_cycle_plan,
    diagnose_run,
    rebuild_family_trial_stats,
)
from wq_alpha_os.research.taxonomy import ECONOMIC_THEMES


class FieldProfilerV3Tests(unittest.TestCase):
    def _profile(self, name: str, description: str, dataset: str, data_type: str = "MATRIX"):
        return profile_row({
            "field_key": name,
            "name": name,
            "description": description,
            "dataset_name": dataset,
            "data_type": data_type,
            "semantic_theme": None,
            "semantic_direction": None,
        })

    def test_name_and_description_override_dataset_prior(self):
        momentum = self._profile(
            "mdl77_opricemomentumfactor_normalmf60d", "price momentum model factor", "Analysts' Factor Model"
        )
        atr = self._profile(
            "average_true_range_fourteen_periods", "average true range risk measure", "US News Data", "VECTOR"
        )
        self.assertEqual(momentum.economic_theme, "price")
        self.assertEqual(momentum.semantic_form, "return")
        self.assertEqual(momentum.signedness, "signed")
        self.assertEqual(atr.economic_theme, "risk_volatility")

    def test_token_aware_rules_fix_known_false_positives(self):
        liquidity = self._profile(
            "mdl77_liquidityriskfactor_monchgsip", "monthly change in liquidity risk", "Analysts' Factor Model"
        )
        price_change = self._profile(
            "previous_day_open_close_change_pct_all", "previous day open close price change", "US News Data", "VECTOR"
        )
        news_dispersion = self._profile(
            "news_vol_stddev", "standard deviation of news volume", "US News Data"
        )
        self.assertEqual(liquidity.economic_theme, "volume_liquidity")
        self.assertEqual(liquidity.signedness, "signed")
        self.assertEqual(price_change.economic_theme, "price")
        self.assertEqual(price_change.signedness, "signed")
        self.assertEqual(news_dispersion.economic_theme, "sentiment_news")
        self.assertEqual(news_dispersion.semantic_form, "dispersion")

    def test_value_direction_defaults_to_ambiguous(self):
        profile = self._profile("cash_flow_to_price_value_factor", "cash flow to price value factor", "Model")
        self.assertEqual(profile.economic_theme, "value")
        self.assertEqual(profile.direction_prior, "ambiguous")

    def test_theme_taxonomy_is_shared_across_research_components(self):
        path_themes = {theme for template in PATH_TEMPLATES for theme in template.preferred_themes}
        self.assertEqual(REVIEW_THEMES, ECONOMIC_THEMES)
        self.assertLessEqual(set(THEME_TEMPLATES), ECONOMIC_THEMES)
        self.assertLessEqual(path_themes, ECONOMIC_THEMES)

    def test_path_gate_requires_each_declared_semantic_dimension(self):
        analyst_ratio = replace(
            self._profile("estimate_revision", "analyst estimate revision", "Analyst"),
            semantic_form="ratio",
        )
        paths = {item.id for item in eligible_templates([analyst_ratio])}
        self.assertNotIn("slow_change_peer", paths)

    def test_two_field_path_checks_both_fields_and_pair(self):
        price = self._profile("price_momentum", "stock return momentum", "Price")
        value = self._profile("cash_flow_to_price", "cash flow to price value factor", "Fundamental")
        paths = {item.id for item in eligible_templates([price, value])}
        self.assertNotIn("two_series_correlation", paths)

        incompatible_a = replace(value, semantic_form="level", unit_family="currency_flow")
        incompatible_b = replace(value, name="other", semantic_form="level", unit_family="count")
        ratio_paths = {item.id for item in eligible_templates([incompatible_a, incompatible_b])}
        self.assertNotIn("relative_ratio", ratio_paths)


class CandidatePacketV3Tests(unittest.TestCase):
    THEMES = ("value", "profitability", "price", "risk_volatility", "sentiment_news", "relationship")

    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(DDL)
        for dataset_index in range(6):
            for field_index in range(4):
                theme = self.THEMES[(dataset_index + field_index) % len(self.THEMES)]
                self._insert_profile(
                    f"field_{dataset_index}_{field_index}", f"Dataset {dataset_index}", "MATRIX", theme, 0.90
                )
        self._insert_profile("top3000", "Universe Dataset", "UNIVERSE", "generic", 0.95)

    def tearDown(self):
        self.connection.close()

    def _insert_profile(self, name: str, dataset: str, data_type: str, theme: str, confidence: float):
        self.connection.execute(
            """INSERT INTO fields(field_key,name,dataset_name,description,data_type,coverage,alpha_count,raw_json,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (name, name, dataset, f"Description for {name}", data_type, 95.0, 0, "{}", "2026-09-05T00:00:00+00:00"),
        )
        self.connection.execute(
            """INSERT INTO field_profiles(
                field_key,name,dataset_name,data_type,economic_theme,secondary_themes_json,semantic_form,
                update_cadence,signedness,unit_family,sparsity_class,peer_dependence,direction_prior,
                direction_confidence,horizon_prior_json,preferred_roles_json,discouraged_roles_json,
                classification_source,confidence,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                name, name, dataset, data_type, theme, "[]", "level", "slow", "unknown", "unknown",
                "slow_stepwise", "high", "ambiguous", "low", "[126,252]", "[]", "[]",
                "deterministic_v3", confidence, "2026-09-05T00:00:00+00:00",
            ),
        )

    def test_packet_is_diverse_described_and_excludes_infrastructure(self):
        packet = build_discovery_context(self.connection, count=6)
        fields = packet["candidate_fields"]
        datasets = Counter(item["dataset"] for item in fields)
        themes = Counter(item["theme"] for item in fields)
        self.assertEqual(len(fields), 24)
        self.assertTrue(all(item["data_type"] in {"MATRIX", "VECTOR"} for item in fields))
        self.assertTrue(all(item["description"] for item in fields))
        self.assertLessEqual(max(datasets.values()) / len(fields), 0.25)
        self.assertLessEqual(max(themes.values()) / len(fields), 0.25)
        self.assertGreaterEqual(len(datasets), 6)

        audit = build_agent_packet_audit(self.connection, count=6)
        self.assertTrue(audit["audit"]["gate_pass"])
        self.assertEqual(audit["audit"]["infrastructure_count"], 0)

    def test_field_review_excludes_infrastructure_and_unknown_unit_alone(self):
        self.assertEqual(review_rows(self.connection, 20), [])
        self._insert_profile("ambiguous_matrix", "Strategic", "MATRIX", "generic", 0.35)
        rows = review_rows(self.connection, 20)
        self.assertEqual([row["name"] for row in rows], ["ambiguous_matrix"])


class SchedulerCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(DDL)

    def tearDown(self):
        self.connection.close()

    def _artifact_and_run(self, index: int, mutation: str | None, *, best: bool = False):
        artifact = f"a{index}"
        self.connection.execute(
            """INSERT INTO alpha_artifacts(
                id,family,expression,canonical_expression,exact_hash,structural_hash,field_names_json,
                operator_names_json,rationale,mutation,generator,prompt_version,validation_json,
                complexity_nodes,complexity_depth,status,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                artifact, "value_cashflow_multihorizon", f"rank(f{index})", f"rank(f{index})",
                f"exact-{index}", f"struct-{index}", f'["f{index}"]', '["rank"]', "test", mutation,
                "test", "v2", "{}", 2, 2, "tested", f"2026-09-05T00:00:{index:02d}+00:00",
            ),
        )
        checks = [{"name": "LOW_FITNESS", "result": "FAIL"}]
        self.connection.execute(
            """INSERT INTO simulation_runs(
                id,artifact_id,settings_json,settings_hash,platform_status,sharpe,fitness,turnover,
                self_correlation,checks_json,annual_json,started_at,finished_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                f"r{index}", artifact, "{}", f"settings-{index}", "COMPLETE",
                1.43 if best else 1.2, 0.98 if best else 0.8, 0.028,
                0.9415 if best else 0.5, json.dumps(checks), "[]",
                f"2026-09-05T00:00:{index:02d}+00:00", f"2026-09-05T00:01:{index:02d}+00:00",
            ),
        )
        return artifact

    def test_metric_check_does_not_mask_high_correlation_routing(self):
        diagnosis = diagnose_run({
            "platform_status": "COMPLETE",
            "checks_json": json.dumps([{"name": "LOW_FITNESS", "result": "FAIL"}]),
            "sharpe": 1.43,
            "fitness": 0.98,
            "turnover": 0.028,
            "self_correlation": 0.9415,
            "annual_json": "[]",
        })
        self.assertEqual(diagnosis.action, "BRANCH_SEMANTIC")

    def test_cycle_plan_contains_best_semantic_branch_parent(self):
        best_id = self._artifact_and_run(1, None, best=True)
        plan = controlled_cycle_plan(self.connection, 12)
        self.assertIn(best_id, {item["artifact_id"] for item in plan["diversity_parents"]})

    def test_historical_trials_are_rebuilt_and_sensitivity_adds_burden(self):
        for index in range(8):
            self._artifact_and_run(index, f"sensitivity:window_{index}" if index else None, best=index == 0)
        result = rebuild_family_trial_stats(self.connection)
        row = self.connection.execute(
            "SELECT effective_trial_count,semantic_branches,parameter_only_trials FROM family_trial_stats WHERE family=?",
            ("value_cashflow_multihorizon",),
        ).fetchone()
        self.assertEqual(result["effective_trials"], 8)
        self.assertEqual(row["effective_trial_count"], 8)
        self.assertEqual(row["parameter_only_trials"], 7)
        self.assertEqual(row["semantic_branches"], 0)


if __name__ == "__main__":
    unittest.main()
