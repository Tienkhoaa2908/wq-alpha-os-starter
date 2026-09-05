"""Giao diện chung và lỗi an toàn cho nguồn mô hình."""

from __future__ import annotations

from typing import Protocol


class ProviderError(RuntimeError):
    """Lỗi có thể hiển thị cho người dùng mà không chứa khóa truy cập."""


class CompletionProvider(Protocol):
    """Nguồn mô hình trả về một câu trả lời văn bản cho một cặp lời nhắc."""

    def complete(self, system: str, user: str) -> str:
        """Sinh câu trả lời hoàn chỉnh."""

