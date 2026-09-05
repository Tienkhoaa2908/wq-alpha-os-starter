from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from wq_alpha_os.config import Settings
from wq_alpha_os.db import DDL
from wq_alpha_os.research.agentic import design, discover


class FakeProvider:
    def __init__(self, answers: list[dict]):
        self.answers = [json.dumps(answer) for answer in answers]
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.answers.pop(0)


def test_settings(evidence_dir: Path) -> Settings:
    return Settings(
        db_path=Path("data/db/test.sqlite"),
        evidence_dir=evidence_dir,
        brain_base_url="https://brain.example",
        brain_email="",
        brain_password="",
        brain_timeout_seconds=60,
        brain_poll_seconds=10,
        brain_max_polls=1,
        llm_base_url="http://localhost:11434/v1",
        llm_model="unused",
        llm_api_key="unused",
        llm_timeout_seconds=15,
        llm_provider="gemini",
        gemini_base_url="https://generativelanguage.googleapis.com/v1beta",
        gemini_model="gemini-test",
        gemini_api_key="not-used-by-fake",
    )


class AgenticWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(DDL)
        self.connection.execute(
            """INSERT INTO fields(
               field_key,field_id,name,dataset_name,description,data_type,coverage,semantic_theme,
               semantic_direction,raw_json,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            ("news_signal", "news_signal", "news_signal", "US News Data", "Tin tức mới", "MATRIX",
             96, "sentiment", "ambiguous", "{}", "now"),
        )

    def tearDown(self):
        self.connection.close()

    def test_discovery_design_and_critic_create_only_locally_validated_candidate(self):
        provider = FakeProvider([
            {"hypotheses": [{
                "family": "news_event_absorption",
                "statement": "Tin tức mới được hấp thụ chậm giữa các công ty cùng ngành.",
                "mechanism": "Tin tức công khai có thể được phản ánh dần vào định giá.",
                "expected_direction": "Kiểm tra dấu dương trước.",
                "horizon": "Ngắn hạn.",
                "data_themes": ["sentiment"],
                "field_names": ["news_signal"],
                "operator_roles": ["time_position", "group_control"],
                "falsifier": "Đóng nhánh nếu dấu chẩn đoán không có chất lượng.",
                "novelty": "Không dùng dòng tiền hay nhiều khung thời gian.",
            }]},
            {"proposals": [{
                "expression": "normalize(group_rank(ts_rank(news_signal, 20), industry), useStd=true, limit=3)",
                "rationale": "Một nhánh tin tức với một cơ chế thời gian và kiểm soát ngành.",
                "design_note": "thí nghiệm dấu ban đầu",
            }]},
            {"decisions": [{"index": 0, "verdict": "accept", "reasons": ["Đúng thẻ và tối giản."]}]},
        ])
        with tempfile.TemporaryDirectory() as directory:
            settings = test_settings(Path(directory))
            discovered = discover(self.connection, 1, settings=settings, provider=provider)
            self.assertEqual(len(discovered["accepted"]), 1)
            designed = design(self.connection, 1, settings=settings, provider=provider)

        self.assertEqual(designed["accepted"], 1)
        artifact = self.connection.execute("SELECT family,status,generator FROM alpha_artifacts").fetchone()
        self.assertEqual(tuple(artifact), ("news_event_absorption", "validated", "gemini_agent_designer"))
        card = self.connection.execute("SELECT status FROM hypothesis_cards").fetchone()[0]
        self.assertEqual(card, "designed")
        self.assertEqual(len(provider.calls), 3)

    def test_discovery_rejects_formula_instead_of_persisting_it(self):
        provider = FakeProvider([{"hypotheses": [{
            "family": "bad_card",
            "statement": "x", "mechanism": "x", "expected_direction": "x", "horizon": "x",
            "data_themes": ["sentiment"], "field_names": ["news_signal"],
            "operator_roles": ["time_position"], "falsifier": "x", "novelty": "x",
            "expression": "rank(news_signal)",
        }]}])
        with tempfile.TemporaryDirectory() as directory:
            result = discover(self.connection, 1, settings=test_settings(Path(directory)), provider=provider)
        self.assertEqual(result["accepted"], [])
        self.assertEqual(self.connection.execute("SELECT count(*) FROM hypothesis_cards").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
