from __future__ import annotations

import json
import os
from typing import Any

from openai import OpenAI
from pydantic import BaseModel, Field


class AlphaReview(BaseModel):
    verdict: str = Field(description="test_now, mutate_first, reject")
    score: int = Field(ge=0, le=100)
    rationale: str
    risks: list[str]
    suggested_settings: dict[str, Any]
    mutations: list[str]


SYSTEM_PROMPT = """
You are a quantitative alpha research assistant for WorldQuant BRAIN-style alpha expressions.
Evaluate candidates using only the provided metadata. Prefer interpretable, low-turnover,
industry-neutral, coverage-safe candidates. Do not claim a candidate will pass. Return strict JSON.
"""


def review_alpha(candidate: dict, model: str = "gpt-5.5") -> AlphaReview:
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set")

    resp = client.responses.parse(
        model=model,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(candidate, ensure_ascii=False)},
        ],
        text_format=AlphaReview,
    )
    return resp.output_parsed
