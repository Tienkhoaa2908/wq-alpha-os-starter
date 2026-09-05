from __future__ import annotations

import json
import unittest
import urllib.error
from argparse import Namespace
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

from wq_alpha_os import cli
from wq_alpha_os.config import Settings
from wq_alpha_os.providers import GeminiProvider, ProviderError, provider_for


class _Response:
    def __init__(self, data: dict):
        self._data = json.dumps(data).encode("utf-8")

    def read(self) -> bytes:
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


def _settings() -> Settings:
    return Settings(
        db_path=Path("data/db/test.sqlite"),  # Không dùng trong kiểm thử nguồn mô hình.
        evidence_dir=Path("data/evidence"),
        brain_base_url="https://brain.example",
        brain_email="",
        brain_password="",
        brain_timeout_seconds=60,
        brain_poll_seconds=10,
        brain_max_polls=1,
        llm_base_url="http://localhost:11434/v1",
        llm_model="local-model",
        llm_api_key="local-key",
        llm_timeout_seconds=15,
        llm_provider="gemini",
        gemini_base_url="https://generativelanguage.googleapis.com/v1beta",
        gemini_model="gemini-2.5-pro",
        gemini_api_key="secret-api-key",
    )


class GeminiProviderTests(unittest.TestCase):
    def test_missing_key_has_clear_message_without_request(self):
        with self.assertRaisesRegex(ProviderError, "GEMINI_API_KEY"):
            GeminiProvider(replace(_settings(), gemini_api_key="")).complete("hệ thống", "người dùng")

    @patch("wq_alpha_os.providers.gemini.urllib.request.urlopen")
    def test_calls_official_endpoint_with_key_in_header_only(self, urlopen):
        urlopen.return_value = _Response(
            {"candidates": [{"content": {"parts": [{"text": '{"proposals": []}'}]}}]}
        )

        answer = GeminiProvider(_settings()).complete("quy tắc", "nội dung")

        self.assertEqual(answer, '{"proposals": []}')
        request = urlopen.call_args.args[0]
        self.assertNotIn("secret-api-key", request.full_url)
        self.assertEqual(request.get_header("X-goog-api-key"), "secret-api-key")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["systemInstruction"]["parts"][0]["text"], "quy tắc")
        self.assertEqual(payload["contents"][0]["parts"][0]["text"], "nội dung")
        self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")

    @patch("wq_alpha_os.providers.gemini.urllib.request.urlopen")
    def test_authentication_failure_never_echoes_key(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError(
            "https://generativelanguage.googleapis.com", 403, "forbidden", {}, None
        )

        with self.assertRaises(ProviderError) as caught:
            GeminiProvider(_settings()).complete("quy tắc", "nội dung")

        self.assertIn("xác thực", str(caught.exception))
        self.assertNotIn("secret-api-key", str(caught.exception))

    def test_factory_selects_gemini(self):
        self.assertIsInstance(provider_for(_settings()), GeminiProvider)

    def test_factory_error_lists_all_supported_provider_names(self):
        with self.assertRaisesRegex(ProviderError, "ollama"):
            provider_for(replace(_settings(), llm_provider="khong_co"))

    @patch("wq_alpha_os.providers.gemini.urllib.request.urlopen")
    def test_malformed_response_has_clear_error(self, urlopen):
        urlopen.return_value = _Response([])

        with self.assertRaisesRegex(ProviderError, "không đúng dạng"):
            GeminiProvider(_settings()).complete("quy tắc", "nội dung")

    def test_cli_run_uses_env_provider_unless_command_overrides_it(self):
        connection = object()
        context = MagicMock()
        context.__enter__.return_value = connection
        settings = replace(_settings(), llm_provider="openai_compatible")
        with (
            patch("wq_alpha_os.cli.initialize"),
            patch("wq_alpha_os.cli.Settings.from_env", return_value=settings),
            patch("wq_alpha_os.cli.session", return_value=context),
            patch("wq_alpha_os.research.orchestrator.run_cycle", return_value={"ok": True}) as run_cycle,
            patch("wq_alpha_os.cli._print"),
        ):
            cli.cmd_run(Namespace(budget=2, provider="gemini"))

        self.assertIs(run_cycle.call_args.args[0], connection)
        self.assertEqual(run_cycle.call_args.args[1], 2)
        self.assertEqual(run_cycle.call_args.kwargs["settings"].llm_provider, "gemini")

    def test_cli_provider_is_optional_so_env_remains_the_default(self):
        self.assertIsNone(cli.parser().parse_args(["propose"]).provider)
        self.assertEqual(cli.parser().parse_args(["propose", "--provider", "gemini"]).provider, "gemini")


if __name__ == "__main__":
    unittest.main()
