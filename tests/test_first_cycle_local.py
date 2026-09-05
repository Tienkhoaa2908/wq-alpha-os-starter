from __future__ import annotations

import unittest

from wq_alpha_os.research.candidate_review import _validated
from wq_alpha_os.research.first_cycle import _select_diverse


class CandidateReviewSafetyTests(unittest.TestCase):
    def test_forbidden_formula_surface_is_rejected(self):
        item = {
            "name": "field_a",
            "verdict": "accept",
            "economic_theme": "price",
            "secondary_themes": [],
            "semantic_form": "return",
            "update_cadence": "fast",
            "signedness": "signed",
            "unit_family": "return",
            "direction_prior": "ambiguous",
            "confidence": 0.9,
            "reason": "description supports it",
            "operator": "ts_rank",
        }
        review, reason = _validated(item, {"field_a"})
        self.assertIsNone(review)
        self.assertEqual(reason, "forbidden_formula_content")

    def test_valid_review_is_bounded(self):
        item = {
            "name": "field_a",
            "verdict": "correct",
            "economic_theme": "price",
            "secondary_themes": ["risk_volatility"],
            "semantic_form": "return",
            "update_cadence": "fast",
            "signedness": "signed",
            "unit_family": "return",
            "direction_prior": "ambiguous",
            "confidence": 0.99,
            "reason": "description says stock return",
        }
        review, reason = _validated(item, {"field_a"})
        self.assertIsNone(reason)
        self.assertEqual(review["confidence"], 0.92)
        self.assertEqual(review["secondary_themes"], ["risk_volatility"])


class FirstCycleDiversityTests(unittest.TestCase):
    def _card(self, idx: int, theme: str, dataset: str):
        return {
            "family": f"family_{idx}",
            "field_names": [f"field_{idx}"],
            "primary_theme": theme,
            "source_datasets": [dataset],
        }

    def test_selects_six_diverse_cards(self):
        cards = [
            self._card(0, "price", "D0"),
            self._card(1, "value", "D1"),
            self._card(2, "quality", "D2"),
            self._card(3, "options", "D3"),
            self._card(4, "relationship", "D4"),
            self._card(5, "sentiment_news", "D5"),
            self._card(6, "price", "D6"),
        ]
        selected = _select_diverse(cards, 6)
        self.assertEqual(len(selected), 6)
        self.assertGreaterEqual(len({item["primary_theme"] for item in selected}), 5)
        self.assertGreaterEqual(
            len({dataset for item in selected for dataset in item["source_datasets"]}),
            5,
        )

    def test_repeated_field_cannot_form_breadth_batch(self):
        cards = [
            self._card(0, "price", "D0"),
            self._card(1, "value", "D1"),
            self._card(2, "quality", "D2"),
            self._card(3, "options", "D3"),
            self._card(4, "relationship", "D4"),
            self._card(5, "sentiment_news", "D5"),
        ]
        cards[5]["field_names"] = ["field_0"]
        self.assertEqual(_select_diverse(cards, 6), [])


if __name__ == "__main__":
    unittest.main()
