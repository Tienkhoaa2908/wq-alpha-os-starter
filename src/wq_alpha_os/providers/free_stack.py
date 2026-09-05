"""Resilient free-provider stack for bounded research reasoning.

The project must not depend on one vendor's free quota.  This module tries only
providers for which a local API key exists and never exposes keys, response
bodies from HTTP errors, or account metadata in exceptions.

Current preferred order:
1. Groq free tier: GPT-OSS 120B, then Qwen 3.8 27B.
2. OpenRouter free endpoints: finance-specialized Ling, MiniMax M2.7, then
   Nemotron 3 Ultra.

All endpoints are OpenAI-chat compatible.  The stack requests JSON mode when
supported and transparently retries once without ``response_format`` when a
provider/model rejects that option.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from ..config import Settings
from .base import ProviderError


@dataclass(frozen=True)
class FreeEndpoint:
    provider: str
    base_url: str
    model: str
    api_key: str
    json_mode: bool = True


class FreeStackProvider:
    """Try configured free inference endpoints in deterministic order."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings.from_env()
        self.last_provider: str | None = None
        self.last_model: str | None = None
        self.failures: list[dict[str, str]] = []

    @property
    def model_name(self) -> str:
        if self.last_provider and self.last_model:
            return f"{self.last_provider}:{self.last_model}"
        return "auto_free"

    def _endpoints(self) -> list[FreeEndpoint]:
        result: list[FreeEndpoint] = []

        groq_key = os.getenv("GROQ_API_KEY", "").strip()
        if groq_key:
            configured = os.getenv("GROQ_MODELS", "").strip()
            models = [item.strip() for item in configured.split(",") if item.strip()] or [
                "openai/gpt-oss-120b",
                "qwen/qwen3.8-27b",
            ]
            result.extend(
                FreeEndpoint("groq", "https://api.groq.com/openai/v1", model, groq_key, True)
                for model in models
            )

        openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if openrouter_key:
            configured = os.getenv("OPENROUTER_FREE_MODELS", "").strip()
            models = [item.strip() for item in configured.split(",") if item.strip()] or [
                "inclusionai/ling-3.0-flash-fin:free",
                "minimax/minimax-m2.7:free",
                "nvidia/nemotron-3-ultra-550b-a55b:free",
            ]
            for model in models:
                result.append(
                    FreeEndpoint(
                        "openrouter",
                        "https://openrouter.ai/api/v1",
                        model,
                        openrouter_key,
                        # Nemotron's current free endpoint does not expose
                        # response_format; other entries normally do.
                        "nemotron-3-ultra" not in model,
                    )
                )

        return result

    def complete(self, system: str, user: str) -> str:
        endpoints = self._endpoints()
        if not endpoints:
            raise ProviderError(
                "Không có free inference key. Điền GROQ_API_KEY hoặc OPENROUTER_API_KEY trong .env."
            )

        self.failures = []
        for endpoint in endpoints:
            try:
                answer = self._complete_endpoint(endpoint, system, user)
            except ProviderError as exc:
                self.failures.append({
                    "provider": endpoint.provider,
                    "model": endpoint.model,
                    "error": str(exc),
                })
                continue
            self.last_provider = endpoint.provider
            self.last_model = endpoint.model
            return answer

        summary = "; ".join(
            f"{item['provider']}:{item['model']} -> {item['error']}"
            for item in self.failures[-5:]
        )
        raise ProviderError("Mọi free provider đều thất bại. " + summary)

    def _complete_endpoint(self, endpoint: FreeEndpoint, system: str, user: str) -> str:
        payload: dict[str, Any] = {
            "model": endpoint.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.45,
        }
        if endpoint.json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            return self._post(endpoint, payload)
        except _ModelRejectedJsonMode:
            payload.pop("response_format", None)
            return self._post(endpoint, payload)

    def _post(self, endpoint: FreeEndpoint, payload: dict[str, Any]) -> str:
        url = endpoint.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {endpoint.api_key}",
        }
        if endpoint.provider == "openrouter":
            headers["X-Title"] = "wq-alpha-os"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.settings.llm_timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 400 and "response_format" in payload:
                raise _ModelRejectedJsonMode() from exc
            if exc.code == 429:
                raise ProviderError("hết hạn mức tạm thời (HTTP 429)") from exc
            if exc.code in {401, 403}:
                raise ProviderError(f"khóa bị từ chối (HTTP {exc.code})") from exc
            if exc.code == 404:
                raise ProviderError("model/endpoint không khả dụng (HTTP 404)") from exc
            if exc.code >= 500:
                raise ProviderError(f"dịch vụ lỗi tạm thời (HTTP {exc.code})") from exc
            raise ProviderError(f"HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderError("không kết nối được hoặc quá thời gian chờ") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError("phản hồi không phải JSON API hợp lệ") from exc

        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("phản hồi không có choices[0].message.content") from exc
        answer = re.sub(r"<think>.*?</think>", "", str(text), flags=re.DOTALL).strip()
        if not answer:
            raise ProviderError("model trả nội dung rỗng")
        return answer


class _ModelRejectedJsonMode(RuntimeError):
    pass


__all__ = ["FreeEndpoint", "FreeStackProvider"]
