from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_dotenv(path: Path | None = None) -> None:
    """Load a small, dependency-free subset of dotenv syntax."""
    path = path or PROJECT_ROOT / ".env"
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    db_path: Path
    evidence_dir: Path
    brain_base_url: str
    brain_email: str
    brain_password: str
    brain_timeout_seconds: int
    brain_poll_seconds: int
    brain_max_polls: int
    llm_base_url: str
    llm_model: str
    llm_api_key: str
    llm_timeout_seconds: int
    llm_provider: str = "openai_compatible"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_model: str = "gemini-2.5-pro"
    gemini_api_key: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        return cls(
            db_path=project_path(os.getenv("ALPHA_OS_DB", "data/db/alpha_lab.sqlite")),
            evidence_dir=project_path(
                os.getenv("ALPHA_OS_EVIDENCE_DIR", "data/evidence")
            ),
            brain_base_url=os.getenv(
                "BRAIN_BASE_URL", "https://api.worldquantbrain.com"
            ).rstrip("/"),
            brain_email=os.getenv("BRAIN_EMAIL", ""),
            brain_password=os.getenv("BRAIN_PASSWORD", ""),
            brain_timeout_seconds=_int_env("BRAIN_TIMEOUT_SECONDS", 60),
            brain_poll_seconds=_int_env("BRAIN_POLL_SECONDS", 10),
            brain_max_polls=_int_env("BRAIN_MAX_POLLS", 120),
            llm_base_url=os.getenv(
                "ALPHA_LLM_BASE_URL", "http://localhost:11434/v1"
            ).rstrip("/"),
            llm_model=os.getenv("ALPHA_LLM_MODEL", "qwen3:1.7b"),
            llm_api_key=os.getenv("ALPHA_LLM_API_KEY", "ollama"),
            llm_timeout_seconds=_int_env("ALPHA_LLM_TIMEOUT_SECONDS", 300),
            llm_provider=os.getenv("ALPHA_LLM_PROVIDER", "openai_compatible"),
            gemini_base_url=os.getenv(
                "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
            ).rstrip("/"),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-pro"),
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        )


def load_defaults() -> dict[str, Any]:
    path = PROJECT_ROOT / "config" / "default.json"
    return json.loads(path.read_text(encoding="utf-8"))


def simulation_settings(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    load_dotenv()
    settings = dict(load_defaults()["simulation"])
    env_mapping: dict[str, tuple[str, Any]] = {
        "region": ("ALPHA_REGION", str),
        "universe": ("ALPHA_UNIVERSE", str),
        "delay": ("ALPHA_DELAY", int),
        "decay": ("ALPHA_DECAY", int),
        "truncation": ("ALPHA_TRUNCATION", float),
        "neutralization": ("ALPHA_NEUTRALIZATION", str),
        "pasteurization": ("ALPHA_PASTEURIZATION", str),
        "nanHandling": ("ALPHA_NAN_HANDLING", str),
        "unitHandling": ("ALPHA_UNIT_HANDLING", str),
    }
    for key, (env_name, caster) in env_mapping.items():
        if env_name in os.environ:
            settings[key] = caster(os.environ[env_name])
    if overrides:
        settings.update({k: v for k, v in overrides.items() if v is not None})
    return settings
