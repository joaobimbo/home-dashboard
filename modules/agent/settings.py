"""Environment-only configuration for the Telegram agent."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import FrozenSet


@dataclass(frozen=True)
class AgentSettings:
    telegram_token: str
    allowed_chat_ids: FrozenSet[int]
    provider: str
    model: str
    api_key: str
    data_dir: str
    dashboard_url: str
    timezone_name: str
    max_message_age_seconds: int

    @classmethod
    def from_environment(cls):
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        provider = os.environ.get("LLM_PROVIDER", "").strip().lower()
        model = os.environ.get("LLM_MODEL", "").strip()
        raw_chats = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
        if not provider or not model:
            raise RuntimeError("LLM_PROVIDER and LLM_MODEL are required")
        try:
            chats = frozenset(int(value.strip()) for value in raw_chats.split(",") if value.strip())
        except ValueError as exc:
            raise RuntimeError("TELEGRAM_ALLOWED_CHAT_IDS must contain numeric chat IDs") from exc
        if not chats:
            raise RuntimeError("At least one TELEGRAM_ALLOWED_CHAT_IDS value is required")
        try:
            max_message_age_seconds = int(
                os.environ.get("AGENT_MAX_MESSAGE_AGE_SECONDS", "3600")
            )
        except ValueError as exc:
            raise RuntimeError("AGENT_MAX_MESSAGE_AGE_SECONDS must be an integer") from exc
        if max_message_age_seconds <= 0:
            raise RuntimeError("AGENT_MAX_MESSAGE_AGE_SECONDS must be positive")

        key_names = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "claude": "ANTHROPIC_API_KEY",
            "google": "GEMINI_API_KEY",
            "gemini": "GEMINI_API_KEY",
        }
        key_name = key_names.get(provider)
        if not key_name:
            raise RuntimeError(f"Unsupported LLM_PROVIDER: {provider}")
        api_key = os.environ.get(key_name, "").strip()
        if not api_key:
            raise RuntimeError(f"{key_name} is required for {provider}")

        default_data = Path(__file__).resolve().parents[2] / "var" / "agent"
        return cls(
            telegram_token=token,
            allowed_chat_ids=chats,
            provider=provider,
            model=model,
            api_key=api_key,
            data_dir=os.environ.get("AGENT_DATA_DIR", str(default_data)),
            dashboard_url=os.environ.get("DASHBOARD_URL", "http://127.0.0.1:5000"),
            timezone_name=os.environ.get("AGENT_TIMEZONE", "Europe/Lisbon"),
            max_message_age_seconds=max_message_age_seconds,
        )
