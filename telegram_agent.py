#!/usr/bin/env python3
"""Run the Telegram natural-language home automation service."""

import logging
import os

from modules.agent.bot import TelegramAgent
from modules.agent.client import DashboardClient
from modules.agent.providers import create_provider
from modules.agent.settings import AgentSettings
from modules.agent.store import AutomationStore
from modules.agent.web import WebAgent, start_agent_bridge


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
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
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
    web_agent = WebAgent(
        provider=provider,
        provider_name=settings.provider,
        provider_model=settings.model,
        client=client,
        store=store,
        timezone_name=settings.timezone_name,
    )
    try:
        bridge_port = int(os.environ.get("AGENT_WEB_PORT", "5001"))
    except ValueError as exc:
        raise RuntimeError("AGENT_WEB_PORT must be an integer") from exc
    if not 1 <= bridge_port <= 65535:
        raise RuntimeError("AGENT_WEB_PORT must be between 1 and 65535")
    bridge = start_agent_bridge(web_agent, bridge_port)
    telegram_agent = TelegramAgent(
        token=settings.telegram_token,
        allowed_chat_ids=settings.allowed_chat_ids,
        provider=provider,
        provider_name=settings.provider,
        provider_model=settings.model,
        client=client,
        store=store,
        timezone_name=settings.timezone_name,
        max_message_age_seconds=settings.max_message_age_seconds,
    )
    try:
        telegram_agent.run()
    finally:
        bridge.shutdown()


if __name__ == "__main__":
    main()
