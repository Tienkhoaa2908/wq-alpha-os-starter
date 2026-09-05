from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from ..config import Settings
from .base import ProviderError


class OpenAICompatibleProvider:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings.from_env()

    def complete(self, system: str, user: str) -> str:
        url = f"{self.settings.llm_base_url}/chat/completions"
        payload = {
            "model": self.settings.llm_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.55,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.settings.llm_api_key}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.settings.llm_timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError, KeyError) as exc:
            raise ProviderError(f"Không gọi được mô hình tại {url}: {exc}") from exc
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"Phản hồi mô hình không đúng dạng: {data}") from exc
        return re.sub(r"<think>.*?</think>", "", str(text), flags=re.DOTALL).strip()
