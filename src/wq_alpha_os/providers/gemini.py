"""Nguồn Gemini dùng REST trực tiếp, không cần cài thêm thư viện."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ..config import Settings
from .base import ProviderError


# Ưu tiên mô hình reasoning/chất lượng trước, sau đó mới hạ xuống Flash.
# Danh sách chỉ là preference; model thực tế luôn được đối chiếu với
# ``GET /models`` của chính API key tại thời điểm chạy.
_MODEL_PREFERENCE = (
    "gemini-3.1-pro-preview",
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
)

_NON_TEXT_MARKERS = (
    "embedding",
    "image",
    "live",
    "tts",
    "transcribe",
    "audio",
    "robotics",
    "veo",
    "imagen",
    "lyria",
)


class GeminiProvider:
    """Gọi Gemini qua khóa trong ``GEMINI_API_KEY``.

    Khóa luôn được gửi trong tiêu đề HTTP, không nằm trong địa chỉ gọi và không
    xuất hiện trong thông báo lỗi hay tệp bằng chứng. Provider có thể tự hỏi
    ``/models`` để chọn model ``generateContent`` mà API key hiện tại thực sự
    được quyền dùng; vì vậy một model cũ bị 404 không làm hỏng cả research run.
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings.from_env()
        self.selected_model: str | None = None

    def _api_key(self) -> str:
        api_key = self.settings.gemini_api_key.strip()
        if not api_key:
            raise ProviderError(
                "Chưa có GEMINI_API_KEY. Hãy điền khóa Gemini vào tệp .env riêng tư."
            )
        return api_key

    def list_generate_models(self) -> list[str]:
        """Liệt kê model mà chính API key hiện tại hỗ trợ ``generateContent``."""
        api_key = self._api_key()
        base = self.settings.gemini_base_url.rstrip("/")
        url = f"{base}/models?pageSize=1000"
        request = urllib.request.Request(
            url,
            method="GET",
            headers={"x-goog-api-key": api_key},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.settings.llm_timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ProviderError(_http_error_message(exc.code)) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderError(
                "Không kết nối được Gemini khi kiểm tra danh sách mô hình."
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError("Gemini trả về danh sách mô hình không đọc được.") from exc

        rows = data.get("models") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise ProviderError("Gemini không trả về danh sách mô hình hợp lệ.")
        result: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            methods = row.get("supportedGenerationMethods")
            if not isinstance(methods, list) or "generateContent" not in methods:
                continue
            name = str(row.get("name") or "").strip().removeprefix("models/")
            if not name:
                continue
            result.append(name)
        return sorted(set(result))

    def resolve_model(self, *, exclude: set[str] | None = None) -> str:
        """Chọn model text/reasoning tốt nhất đang khả dụng cho API key.

        Nếu ``GEMINI_MODEL`` hiện tại còn hợp lệ thì giữ nguyên. Nếu không, chọn
        theo ``_MODEL_PREFERENCE`` rồi mới dùng model Gemini text khác. Kết quả
        được cache trong provider cho cả research run.
        """
        excluded = {item.removeprefix("models/") for item in (exclude or set())}
        configured = self.settings.gemini_model.strip().removeprefix("models/")
        if self.selected_model and self.selected_model not in excluded:
            return self.selected_model

        available = [name for name in self.list_generate_models() if name not in excluded]
        if configured and configured.lower() != "auto" and configured in available:
            self.selected_model = configured
            return configured

        for preferred in _MODEL_PREFERENCE:
            if preferred in available:
                self.selected_model = preferred
                return preferred

        text_candidates = [
            name
            for name in available
            if name.startswith("gemini-")
            and not any(marker in name.lower() for marker in _NON_TEXT_MARKERS)
        ]
        if text_candidates:
            # API thường đặt version cao hơn theo số/tên; đảo thứ tự để ưu tiên
            # model mới thay vì model cũ nếu preference table chưa kịp cập nhật.
            self.selected_model = sorted(text_candidates, reverse=True)[0]
            return self.selected_model

        raise ProviderError(
            "API key Gemini hiện tại không có mô hình văn bản hỗ trợ generateContent."
        )

    def _generate(self, model: str, system: str, user: str) -> str:
        api_key = self._api_key()
        base = self.settings.gemini_base_url.rstrip("/")
        safe_model = urllib.parse.quote(model.removeprefix("models/"), safe="-._")
        url = f"{base}/models/{safe_model}:generateContent"
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
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderError(
                "Không kết nối được Gemini. Kiểm tra đường truyền, GEMINI_BASE_URL và thời gian chờ."
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError("Gemini trả về dữ liệu không đọc được.") from exc
        return _response_text(data)

    def complete(self, system: str, user: str) -> str:
        configured = self.settings.gemini_model.strip().removeprefix("models/")
        if not configured:
            raise ProviderError("Chưa có GEMINI_MODEL. Có thể đặt GEMINI_MODEL=auto.")

        model = self.selected_model or configured
        if model.lower() == "auto":
            model = self.resolve_model()

        try:
            answer = self._generate(model, system, user)
            self.selected_model = model
            return answer
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise ProviderError(_http_error_message(exc.code)) from exc

        # Model cấu hình đã biến mất hoặc API key không được quyền dùng. Tự
        # resolve từ /models và retry đúng một lần với model khác.
        fallback = self.resolve_model(exclude={model})
        try:
            answer = self._generate(fallback, system, user)
            self.selected_model = fallback
            return answer
        except urllib.error.HTTPError as exc:
            raise ProviderError(_http_error_message(exc.code)) from exc


def _http_error_message(status: int) -> str:
    """Thông báo hữu ích nhưng tuyệt đối không chép lại nội dung phản hồi HTTP."""
    if status in {401, 403}:
        return (
            f"Gemini từ chối xác thực (HTTP {status}). Kiểm tra GEMINI_API_KEY và quyền dự án Google AI Studio."
        )
    if status == 400:
        return "Gemini từ chối yêu cầu (HTTP 400). Kiểm tra cấu hình lời gọi."
    if status == 404:
        return "Không tìm thấy mô hình Gemini phù hợp (HTTP 404)."
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
