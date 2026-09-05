"""Nguồn Gemini dùng REST trực tiếp, không cần cài thêm thư viện."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from ..config import Settings
from .base import ProviderError


class GeminiProvider:
    """Gọi Gemini qua khóa trong ``GEMINI_API_KEY``.

    Khóa luôn được gửi trong tiêu đề HTTP, không nằm trong địa chỉ gọi và không
    xuất hiện trong thông báo lỗi hay tệp bằng chứng.
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings.from_env()

    def complete(self, system: str, user: str) -> str:
        api_key = self.settings.gemini_api_key.strip()
        if not api_key:
            raise ProviderError(
                "Chưa có GEMINI_API_KEY. Hãy điền khóa Gemini vào tệp .env riêng tư."
            )

        model = self.settings.gemini_model.strip().removeprefix("models/")
        if not model:
            raise ProviderError("Chưa có GEMINI_MODEL. Ví dụ: gemini-2.5-pro.")

        url = f"{self.settings.gemini_base_url.rstrip('/')}/models/{model}:generateContent"
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": 0.55,
                "responseMimeType": "application/json",
            },
        }
        try:
            request = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": api_key,
                },
            )
        except ValueError as exc:
            raise ProviderError("GEMINI_BASE_URL không hợp lệ.") from exc
        try:
            with urllib.request.urlopen(request, timeout=self.settings.llm_timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ProviderError(_http_error_message(exc.code)) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderError(
                "Không kết nối được Gemini. Kiểm tra đường truyền, GEMINI_BASE_URL và thời gian chờ."
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError("Gemini trả về dữ liệu không đọc được.") from exc

        return _response_text(data)


def _http_error_message(status: int) -> str:
    """Thông báo hữu ích nhưng tuyệt đối không chép lại nội dung phản hồi HTTP."""
    if status in {401, 403}:
        return (
            f"Gemini từ chối xác thực (HTTP {status}). Kiểm tra GEMINI_API_KEY, "
            "quyền dự án Google AI Studio và mô hình đã chọn."
        )
    if status == 400:
        return "Gemini từ chối yêu cầu (HTTP 400). Kiểm tra GEMINI_MODEL và cấu hình lời gọi."
    if status == 404:
        return "Không tìm thấy mô hình Gemini (HTTP 404). Kiểm tra GEMINI_MODEL."
    if status == 429:
        return "Gemini đã chạm hạn mức (HTTP 429). Hãy đợi hạn mức được cấp lại rồi chạy lại."
    if status >= 500:
        return f"Dịch vụ Gemini đang gặp lỗi tạm thời (HTTP {status}). Hãy thử lại sau."
    return f"Không gọi được Gemini (HTTP {status})."


def _response_text(data: dict[str, Any]) -> str:
    """Lấy tất cả phần văn bản từ phản hồi Gemini hợp lệ."""
    if not isinstance(data, dict):
        raise ProviderError("Gemini trả về phản hồi không đúng dạng đối tượng.")
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        feedback = data.get("promptFeedback")
        if isinstance(feedback, dict) and feedback.get("blockReason"):
            raise ProviderError("Gemini đã chặn lời nhắc theo chính sách an toàn.")
        raise ProviderError("Gemini không trả về phương án nào.")

    content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    texts = [part.get("text", "") for part in parts or [] if isinstance(part, dict)]
    answer = "".join(str(text) for text in texts).strip()
    if not answer:
        reason = candidates[0].get("finishReason") if isinstance(candidates[0], dict) else None
        suffix = f" (lý do kết thúc: {reason})" if reason else ""
        raise ProviderError(f"Gemini không trả về văn bản{suffix}.")
    return answer
