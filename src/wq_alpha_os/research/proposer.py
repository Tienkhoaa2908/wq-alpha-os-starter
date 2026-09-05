from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from ..config import PROJECT_ROOT, Settings
from ..db import json_dumps
from ..providers import provider_for
from .artifacts import IngestResult, ingest_candidate
from .prompts import PROMPT_VERSION, PromptPacket, build_prompt


def write_prompt_packet(packet: PromptPacket, output: Path | None = None) -> Path:
    output = output or PROJECT_ROOT / "data" / "outbox" / "alpha_prompt.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json_dumps({"prompt_version": PROMPT_VERSION, "prompt_hash": packet.prompt_hash,
                                  "system": packet.system, "user": packet.user}), encoding="utf-8")
    return output


def parse_response(text: str) -> dict[str, Any]:
    clean = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", clean, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        clean = fenced.group(1).strip()
    try:
        data = json.loads(clean)
    except json.JSONDecodeError:
        start, end = clean.find("{"), clean.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("Không tìm thấy đối tượng JSON trong phản hồi mô hình")
        data = json.loads(clean[start:end + 1])
    if isinstance(data, list):
        data = {"proposals": data}
    if not isinstance(data, dict) or not isinstance(data.get("proposals"), list):
        raise ValueError("Phản hồi phải có khóa proposals là một danh sách")
    return data


def ingest_proposals(connection: sqlite3.Connection, data: dict[str, Any], *, generator: str,
                     model_name: str | None = None, prompt_hash: str | None = None) -> list[IngestResult]:
    results = []
    for item in data.get("proposals", []):
        if not isinstance(item, dict) or not str(item.get("expression") or "").strip():
            continue
        results.append(ingest_candidate(
            connection, expression=str(item["expression"]), family=str(item.get("family") or "llm_unclassified"),
            rationale=str(item.get("rationale") or "Đề xuất của mô hình; cần mô phỏng để xác minh."),
            mutation=item.get("mutation"), parent_id=item.get("parent_id"), generator=generator,
            model_name=model_name, prompt_hash=prompt_hash, prompt_version=PROMPT_VERSION,
        ))
    return results


def propose(connection: sqlite3.Connection, count: int, settings: Settings | None = None) -> tuple[Path, list[IngestResult]]:
    settings = settings or Settings.from_env()
    packet = build_prompt(connection, count)
    prompt_path = write_prompt_packet(packet)
    answer = provider_for(settings).complete(packet.system, packet.user)
    answer_path = prompt_path.with_name("alpha_response.json")
    answer_path.write_text(answer, encoding="utf-8")
    model_name = settings.gemini_model if settings.llm_provider.lower() == "gemini" else settings.llm_model
    return answer_path, ingest_proposals(connection, parse_response(answer), generator=settings.llm_provider,
                                         model_name=model_name, prompt_hash=packet.prompt_hash)
