import json
import unittest

from wq_alpha_os.research.operator_graph import (
    build_operator_profiles,
    catalog_field_types,
    compatible_paths,
    graph_payload,
    inspect_expression,
    operator_roles,
)


class OperatorGraphTests(unittest.TestCase):
    def setUp(self):
        self.catalog = [
            {"name": "ts_rank", "category": "Time Series", "signature": "ts_rank(x, d)"},
            {"name": "group_rank", "category": "Group", "signature": "group_rank(x, group)"},
            {"name": "vec_avg", "category": "Vector", "signature": "vec_avg(x)"},
            {"name": "normalize", "category": "Transformational", "signature": "normalize(x)"},
            {"name": "greater", "category": "Logical", "signature": "greater(x, y)"},
        ]

    def test_roles_and_catalog_metadata_are_merged(self):
        profiles = build_operator_profiles(self.catalog)
        self.assertIn("time_position", operator_roles("TS_RANK", self.catalog))
        self.assertEqual(profiles["ts_rank"].category, "Time Series")
        self.assertEqual(profiles["ts_rank"].signature, "ts_rank(x, d)")
        # ``greater`` có trong catalog thô nhưng không có trong DSL typed registry.
        self.assertNotIn("greater", profiles)

    def test_vector_path_requires_a_reducer(self):
        paths = compatible_paths(
            "VECTOR", available_operators={"vec_avg", "group_rank", "normalize"}
        )
        self.assertEqual([path["id"] for path in paths], ["vector_event_signal"])
        reducer = paths[0]["slots"][0]
        self.assertEqual(reducer["min_select"], 1)
        self.assertEqual(reducer["operators"], ["vec_avg"])

    def test_payload_is_json_serializable_and_catalog_bounded(self):
        payload = graph_payload(item for item in self.catalog)
        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertIn("operator-graph-v1", encoded)
        self.assertEqual({item["name"] for item in payload["operators"]}, {
            "group_rank", "normalize", "ts_rank", "vec_avg"
        })

        selected = graph_payload(self.catalog, operator_names={"ts_rank", "group_rank"})
        self.assertEqual({item["name"] for item in selected["operators"]}, {"group_rank", "ts_rank"})

    def test_catalog_field_types_only_keeps_dsl_types(self):
        result = catalog_field_types([
            {"name": "event_vector", "data_type": "VECTOR"},
            {"name": "mystery", "data_type": "TABLE"},
        ])
        self.assertEqual(result, {"event_vector": "VECTOR", "mystery": "UNKNOWN"})

    def test_structure_rejects_direct_vector_and_bad_group(self):
        vector_report = inspect_expression("rank(event_vector)", field_types={"event_vector": "VECTOR"})
        self.assertFalse(vector_report["valid_structure"])
        self.assertIn("vector_requires_reduction", {item["code"] for item in vector_report["issues"]})

        group_report = inspect_expression("group_rank(ts_rank(x, 20), x)", field_types={"x": "MATRIX"})
        self.assertFalse(group_report["valid_structure"])
        self.assertIn("group_argument_required", {item["code"] for item in group_report["issues"]})

    def test_structure_warns_when_alternative_cluster_is_stacked(self):
        report = inspect_expression(
            "normalize(zscore(x), useStd=true, limit=3)", field_types={"x": "MATRIX"}
        )
        self.assertTrue(report["valid_structure"])
        self.assertIn("repeated_alternative_cluster", {item["code"] for item in report["issues"]})

    def test_valid_ordered_path_has_no_structural_error(self):
        expression = "normalize(hump(reverse(group_rank(ts_rank(x, 252), industry)), hump=0.01), useStd=true, limit=3)"
        report = inspect_expression(expression, field_types={"x": "MATRIX"})
        self.assertTrue(report["valid_structure"], report["issues"])


if __name__ == "__main__":
    unittest.main()
