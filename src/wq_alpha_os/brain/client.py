from __future__ import annotations

import base64
import http.cookiejar
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..config import Settings


class BrainError(RuntimeError):
    pass


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    data: Any


class BrainClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings.from_env()
        jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        self.authenticated = False

    def new_evidence_directory(self, kind: str) -> Path:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        path = self.settings.evidence_dir / kind / stamp
        path.mkdir(parents=True, exist_ok=False)
        return path

    def authenticate(self) -> None:
        if not self.settings.brain_email or not self.settings.brain_password:
            raise BrainError("Thiếu BRAIN_EMAIL hoặc BRAIN_PASSWORD trong .env")
        token = base64.b64encode(
            f"{self.settings.brain_email}:{self.settings.brain_password}".encode()
        ).decode()
        response = self._request("POST", "/authentication", headers={"Authorization": f"Basic {token}"}, retry_auth=False)
        if response.status not in {200, 201}:
            raise BrainError(f"Đăng nhập BRAIN thất bại, mã {response.status}")
        self.authenticated = True

    def _request(self, method: str, path: str, *, payload: Any = None,
                 params: dict[str, Any] | None = None, headers: dict[str, str] | None = None,
                 retry_auth: bool = True, transient_retries: int = 8,
                 transient_attempt: int = 0) -> Response:
        if path.startswith("http://") or path.startswith("https://"):
            url = path
        else:
            url = f"{self.settings.brain_base_url}/{path.lstrip('/')}"
        if params:
            encoded = urllib.parse.urlencode([(k, v) for k, value in params.items()
                                               for v in (value if isinstance(value, list) else [value])])
            url += ("&" if "?" in url else "?") + encoded
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request_headers = {"Accept": "application/json", **(headers or {})}
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
        try:
            with self.opener.open(request, timeout=self.settings.brain_timeout_seconds) as raw:
                text = raw.read().decode("utf-8", errors="replace")
                data = json.loads(text) if text.strip() else {}
                return Response(raw.status, dict(raw.headers.items()), data)
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(text) if text.strip() else {}
            except json.JSONDecodeError:
                data = {"raw": text[:4000]}
            if exc.code == 401 and retry_auth:
                self.authenticate()
                return self._request(method, path, payload=payload, params=params, headers=headers,
                                     retry_auth=False, transient_retries=transient_retries,
                                     transient_attempt=transient_attempt)
            if exc.code in {429, 502, 503, 504} and transient_retries > 0:
                server_wait = self.wait_seconds(dict(exc.headers.items()), 0)
                wait = max(server_wait, min(60.0, 5.0 * (2 ** transient_attempt)))
                time.sleep(wait)
                return self._request(method, path, payload=payload, params=params, headers=headers,
                                     retry_auth=retry_auth, transient_retries=transient_retries - 1,
                                     transient_attempt=transient_attempt + 1)
            raise BrainError(f"BRAIN trả mã {exc.code} cho {method} {urllib.parse.urlsplit(url).path}: {data}") from exc
        except urllib.error.URLError as exc:
            raise BrainError(f"Không kết nối được BRAIN: {exc.reason}") from exc

    def get(self, path: str, params: dict[str, Any] | None = None) -> Response:
        if not self.authenticated:
            self.authenticate()
        return self._request("GET", path, params=params)

    def post(self, path: str, payload: Any) -> Response:
        if not self.authenticated:
            self.authenticate()
        return self._request("POST", path, payload=payload)

    def get_all(self, path: str, params: dict[str, Any] | None = None,
                *, progress_label: str | None = None, workers: int = 1) -> dict[str, Any]:
        query = dict(params or {})
        query.setdefault("limit", 50)
        query.setdefault("offset", 0)
        first_data = self.get(path, query).data
        if isinstance(first_data, list):
            first_page = first_data
            total = None
        elif isinstance(first_data, dict):
            first_page = first_data.get("results") or first_data.get("data") or []
            total = first_data.get("count")
        else:
            return {"results": [], "pages": 0, "count": 0}
        if not isinstance(first_page, list):
            return {"results": [], "pages": 1, "count": 0}
        limit = int(query["limit"])
        start_offset = int(query["offset"])
        if total is not None:
            total = int(total)
            offsets = list(range(start_offset + len(first_page), total, limit))
            if len(offsets) > 1000:
                raise BrainError(f"Danh mục có quá nhiều trang bất thường: {len(offsets) + 1}")
            page_map: dict[int, list[Any]] = {start_offset: first_page}
            completed = len(first_page)
            if progress_label:
                print(f"{progress_label}: {completed}/{total}", flush=True)
            with ThreadPoolExecutor(max_workers=max(1, min(workers, 4))) as pool:
                futures = {}
                for offset in offsets:
                    page_query = {**query, "offset": offset}
                    futures[pool.submit(self.get, path, page_query)] = offset
                for future in as_completed(futures):
                    offset = futures[future]
                    data = future.result().data
                    items = data if isinstance(data, list) else data.get("results") or data.get("data") or []
                    if not isinstance(items, list):
                        raise BrainError(f"Trang danh mục tại offset {offset} không phải danh sách")
                    page_map[offset] = items
                    completed += len(items)
                    if progress_label and (completed == total or completed // 500 != (completed - len(items)) // 500):
                        print(f"{progress_label}: {completed}/{total}", flush=True)
            results = [item for offset in sorted(page_map) for item in page_map[offset]]
            return {"results": results, "pages": len(page_map), "count": len(results)}

        results: list[Any] = list(first_page)
        pages = 1
        while True:
            if not results or len(results) % limit:
                break
            query["offset"] = start_offset + len(results)
            data = self.get(path, query).data
            if isinstance(data, list):
                page_items = data
            elif isinstance(data, dict):
                page_items = data.get("results") or data.get("data") or []
            else:
                break
            if not isinstance(page_items, list) or not page_items:
                break
            results.extend(page_items)
            pages += 1
            if pages > 1000:
                raise BrainError("Danh mục vượt giới hạn 1.000 trang")
        return {"results": results, "pages": pages, "count": len(results)}

    @staticmethod
    def wait_seconds(headers: dict[str, str], default: int) -> float:
        value = next((v for k, v in headers.items() if k.lower() == "retry-after"), None)
        try:
            return max(0.25, float(value)) if value is not None else float(default)
        except ValueError:
            return float(default)

    def poll(self, location: str) -> Response:
        last: Response | None = None
        for _ in range(self.settings.brain_max_polls):
            last = self.get(location)
            data = last.data if isinstance(last.data, dict) else {}
            status = str(data.get("status") or "").upper()
            if data.get("alpha") or status in {"COMPLETE", "COMPLETED", "ERROR", "FAILED", "CANCELLED"}:
                return last
            time.sleep(self.wait_seconds(last.headers, self.settings.brain_poll_seconds))
        raise BrainError(f"Mô phỏng chưa xong sau {self.settings.brain_max_polls} lần hỏi; phản hồi cuối: {last}")
