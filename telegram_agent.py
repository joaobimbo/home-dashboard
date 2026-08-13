#!/usr/bin/env python3
"""Run the Telegram natural-language home automation service."""

import logging
import os

from modules.agent.bot import TelegramAgent
from modules.agent.client import DashboardClient
from modules.agent.providers import create_provider
from modules.agent.settings import AgentSettings
from modules.agent.store import AutomationStore


def main():
    requested_level = os.environ.get("AGENT_LOG_LEVEL", "INFO").strip().upper()
    log_level = getattr(logging, requested_level, logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # HTTP client request URLs can contain the Telegram bot token. Keep library
    # transport logs quiet while leaving our own stage logs at the chosen level.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    settings = AgentSettings.from_environment()
    logging.getLogger(__name__).info(
        "agent_starting provider=%s model=%s dashboard=%s allowed_chat_count=%d",
        settings.provider,
        settings.model,
        settings.dashboard_url,
        len(settings.allowed_chat_ids),
    )
    client = DashboardClient(settings.dashboard_url)
    store = AutomationStore(settings.data_dir)
    provider = create_provider(
        settings.provider,
        settings.model,
        settings.api_key,
        settings.timezone_name,
    )
    TelegramAgent(
        token=settings.telegram_token,
        allowed_chat_ids=settings.allowed_chat_ids,
        provider=provider,
        provider_name=settings.provider,
        provider_model=settings.model,
        client=client,
        store=store,
        timezone_name=settings.timezone_name,
        max_message_age_seconds=settings.max_message_age_seconds,
    ).run()


if __name__ == "__main__":
    main()
