"""Các nguồn mô hình sinh đề xuất."""

from __future__ import annotations

from ..config import Settings
from .base import CompletionProvider, ProviderError
from .free_stack import FreeStackProvider
from .gemini import GeminiProvider
from .openai_compatible import OpenAICompatibleProvider


def provider_for(settings: Settings | None = None) -> CompletionProvider:
    """Chọn nguồn mô hình theo ``ALPHA_LLM_PROVIDER`` trong tệp ``.env``."""
    settings = settings or Settings.from_env()
    provider = settings.llm_provider.strip().lower().replace("-", "_")
    if provider in {"openai", "openai_compatible", "ollama"}:
        return OpenAICompatibleProvider(settings)
    if provider == "gemini":
        return GeminiProvider(settings)
    if provider in {"auto_free", "free_stack", "free"}:
        return FreeStackProvider(settings)
    raise ProviderError(
        "ALPHA_LLM_PROVIDER không hợp lệ. Chỉ dùng auto_free, gemini, ollama hoặc openai_compatible."
    )


__all__ = [
    "CompletionProvider",
    "FreeStackProvider",
    "GeminiProvider",
    "OpenAICompatibleProvider",
    "ProviderError",
    "provider_for",
]
