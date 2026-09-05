from __future__ import annotations

import os
from pathlib import Path
import unittest
from unittest.mock import patch

from wq_alpha_os.config import Settings
from wq_alpha_os.providers import FreeStackProvider, ProviderError
from wq_alpha_os.research.autonomous_search import SearchCandidate, select_diverse


def _settings() -> Settings:
    return Settings(
        db_path=Path("data/db/test.sqlite"),
        evidence_dir=Path("data/evidence"),
        brain_base_url="https://brain.example",
        brain_email="",
        brain_password="",
        brain_timeout_seconds=60,
        brain_poll_seconds=10,
        brain_max_polls=1,
        llm_base_url="http://localhost:11434/v1",
        llm_model="local",
        llm_api_key="local",
        llm_timeout_seconds=10,
        llm_provider="auto_free",
        gemini_base_url="https://generativelanguage.googleapis.com/v1beta",
        gemini_model="auto",
        gemini_api_key="",
    )


def _candidate(index: int, theme: str, dataset: str, template: str = "slow_level_peer") -> SearchCandidate:
    return SearchCandidate(
        field_name=f"field_{index}",
        dataset=dataset,
        theme=theme,
        template_id=template,
        horizon_bucket="long",
        expression=f"normalize(group_rank(ts_rank(field_{index}, 252), industry), useStd=true, limit=3)",
        base_score=3.0 - index * 0.01,
        novelty_score=1.0,
        confidence=0.9,
        coverage=90.0,
        rationale="test",
    )


class FreeStackTests(unittest.TestCase):
    def test_requires_at_least_one_key(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "", "OPENROUTER_API_KEY": ""}, clear=False):
            with self.assertRaisesRegex(ProviderError, "GROQ_API_KEY"):
                FreeStackProvider(_settings()).complete("system", "user")

    def test_groq_is_preferred_and_openrouter_is_fallback(self):
        env = {
            "GROQ_API_KEY": "groq-secret",
            "OPENROUTER_API_KEY": "or-secret",
            "GROQ_MODELS": "openai/gpt-oss-120b",
            "OPENROUTER_FREE_MODELS": "inclusionai/ling-3.0-flash-fin:free",
        }
        with patch.dict(os.environ, env, clear=False):
            endpoints = FreeStackProvider(_settings())._endpoints()
        self.assertEqual([item.provider for item in endpoints], ["groq", "openrouter"])
        self.assertEqual(endpoints[0].model, "openai/gpt-oss-120b")
        self.assertEqual(endpoints[1].model, "inclusionai/ling-3.0-flash-fin:free")


class AutonomousSelectionTests(unittest.TestCase):
    def test_selects_six_with_theme_dataset_and_template_breadth(self):
        themes = ["value", "price", "risk_volatility", "sentiment_news", "quality", "relationship"]
        templates = [
            "slow_level_peer", "extremum_recency", "risk_dispersion",
            "vector_event_novelty", "peer_residual", "information_staleness",
        ]
        pool = [
            _candidate(i, theme, f"Dataset {i}", templates[i])
            for i, theme in enumerate(themes)
        ]
        selected = select_diverse(pool, 6)
        self.assertEqual(len(selected), 6)
        self.assertEqual(len({item.theme for item in selected}), 6)
        self.assertEqual(len({item.dataset for item in selected}), 6)
        self.assertGreaterEqual(len({item.template_id for item in selected}), 4)
        self.assertEqual(len({item.field_name for item in selected}), 6)

    def test_rejects_batch_with_only_three_templates(self):
        templates = ["slow_level_peer", "extremum_recency", "risk_dispersion"]
        pool = [
            _candidate(i, f"theme_{i}", f"Dataset {i}", templates[i % 3])
            for i in range(6)
        ]
        with self.assertRaisesRegex(RuntimeError, "templates"):
            select_diverse(pool, 6)

    def test_family_is_stable_and_parameter_free(self):
        item = _candidate(1, "price", "Price")
        self.assertEqual(item.family, item.family)
        self.assertTrue(item.family.startswith("auto_price_slow_level_peer_"))


if __name__ == "__main__":
    unittest.main()
