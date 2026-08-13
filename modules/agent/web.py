"""Synchronous web adapter for the validated home-automation agent."""

import hashlib
import logging
import time
import uuid
from typing import Dict, Optional

from .client import DashboardClient, DashboardError
from .providers import LanguageProvider, ProviderError
from .store import AutomationStore
from .validation import PlanValidationError, validate_interpretation


logger = logging.getLogger(__name__)


class WebAgent:
    """Run the agent from the local dashboard without exposing provider keys."""

    def __init__(
        self,
        provider: LanguageProvider,
        provider_name: str,
        provider_model: str,
        client: DashboardClient,
        store: AutomationStore,
        timezone_name: str,
    ):
        self.provider = provider
        self.provider_name = provider_name
        self.provider_model = provider_model
        self.client = client
        self.store = store
        self.timezone_name = timezone_name
        self._pending: Dict[str, Dict[str, object]] = {}
        self._clarifications: Dict[str, Dict[str, object]] = {}

    def submit(self, message: object, browser_id: str) -> Dict[str, object]:
        text = str(message or "").strip()
        if not 1 <= len(text) <= 1000:
            raise ValueError("Enter a request of up to 1000 characters")

        previous = self._clarifications.pop(browser_id, None)
        prompt = text
        if previous and float(previous["expires_at"]) > time.monotonic():
            prompt = (
                f"Original request: {previous['request']}\n"
                f"Clarifying question: {previous['question']}\n"
                f"User answer: {text}"
            )

        request_id = uuid.uuid4().hex[:10]
        logger.info("web_request_received request_id=%s text=%r", request_id, text)
        catalog = self.client.catalog()
        raw = self.provider.interpret(
            prompt,
            catalog,
            hashlib.sha256(("web:" + browser_id).encode("utf-8")).hexdigest()[:32],
        )
        plan = validate_interpretation(raw, catalog)
        self.store.audit(
            "web_request_interpreted",
            kind=plan["kind"],
            provider=self.provider_name,
            model=self.provider_model,
        )
        return self._handle_plan(plan, text, browser_id)

    def confirm(self, token: object, browser_id: str) -> Dict[str, object]:
        token = str(token or "")
        pending = self._pending.get(token)
        if not pending or float(pending["expires_at"]) < time.monotonic():
            raise ValueError("This confirmation expired")
        if pending["browser_id"] != browser_id:
            raise ValueError("This confirmation belongs to another browser")
        self._pending.pop(token, None)

        replace_id = pending.get("replace_rule_id")
        if replace_id:
            try:
                self.store.delete_rule(str(replace_id), user_id=0)
            except KeyError:
                pass
        rule = self.store.create_rule(pending["automation"], creator_user_id=0, origin_chat_id=0)
        return {"ok": True, "kind": "automation_saved", "message": "Automation saved: " + rule["name"]}

    def _handle_plan(self, plan: Dict[str, object], original: str, browser_id: str) -> Dict[str, object]:
        kind = plan["kind"]
        if kind == "clarification":
            self._clarifications[browser_id] = {
                "request": original,
                "question": plan["question"],
                "expires_at": time.monotonic() + 10 * 60,
            }
            return {"ok": True, "kind": kind, "message": plan["question"]}
        if kind == "unsupported":
            return {"ok": True, "kind": kind, "message": plan.get("reply") or "That request is outside home control."}
        if kind in {"direct_actions", "status_query"}:
            results = []
            snapshot = self.client.snapshot(False) if kind == "status_query" else None
            for action in plan["actions"]:
                if snapshot is not None:
                    result = snapshot["devices"].get(action["device_id"])
                    if not isinstance(result, dict):
                        raise DashboardError("Device status is unavailable")
                else:
                    result = self.client.execute(action)
                results.append(self._format_status(action["display_name"], result))
            return {"ok": True, "kind": kind, "message": "\n".join(results)}

        automation = plan["automation"]
        existing = next(
            (rule for rule in self.store.list_rules() if rule["name"].casefold() == automation["name"].casefold()),
            None,
        )
        token = uuid.uuid4().hex
        self._pending[token] = {
            "browser_id": browser_id,
            "automation": automation,
            "replace_rule_id": existing["id"] if existing else None,
            "expires_at": time.monotonic() + 10 * 60,
        }
        message = self._format_automation(automation)
        if plan.get("assumptions"):
            message += "\nAssumptions: " + "; ".join(plan["assumptions"])
        if existing:
            message += "\nThis replaces existing rule " + existing["id"] + "."
        return {"ok": True, "kind": "automation_confirmation", "message": message, "token": token}

    @staticmethod
    def _format_status(name: str, status: Dict[str, object]) -> str:
        if not status or not status.get("ok"):
            return name + ": unavailable"
        fields = []
        for key in ("state", "power", "mode", "brightness", "position", "setpoint", "current_temp", "fan_speed", "color_temp"):
            if key in status:
                fields.append(key + "=" + str(status[key]))
        return name + ": " + (", ".join(fields) if fields else "ok")

    def _format_automation(self, rule: Dict[str, object]) -> str:
        trigger = rule["trigger"]
        operator = trigger.get("operator")
        if operator == "daily":
            trigger_text = "every day at " + str(trigger.get("at"))
        elif operator == "weekly":
            trigger_text = "weekly at " + str(trigger.get("at"))
        elif operator == "after":
            trigger_text = str(trigger.get("value")) + " seconds after confirmation"
        else:
            trigger_text = "once at " + str(trigger.get("at"))
        lines = ["Save automation: " + rule["name"], rule.get("description") or "", "Trigger: " + trigger_text]
        lines.append("Time zone: " + self.timezone_name)
        lines.append("Repeat: " + rule["repeat"] + "; overlap: " + rule["overlap"])
        return "\n".join(line for line in lines if line)


def create_web_agent_from_environment() -> Optional[WebAgent]:
    """Create the optional web adapter when the LLM settings are available."""
    import os
    from pathlib import Path

    from .providers import create_provider

    provider_name = os.environ.get("LLM_PROVIDER", "").strip().lower()
    model = os.environ.get("LLM_MODEL", "").strip()
    key_names = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "claude": "ANTHROPIC_API_KEY", "google": "GEMINI_API_KEY", "gemini": "GEMINI_API_KEY"}
    key_name = key_names.get(provider_name)
    api_key = os.environ.get(key_name, "").strip() if key_name else ""
    if not provider_name or not model or not api_key:
        return None
    timezone_name = os.environ.get("AGENT_TIMEZONE", "Europe/Lisbon")
    data_dir = os.environ.get("AGENT_DATA_DIR", str(Path(__file__).resolve().parents[2] / "var" / "agent"))
    return WebAgent(
        create_provider(provider_name, model, api_key, timezone_name),
        provider_name,
        model,
        DashboardClient(os.environ.get("DASHBOARD_URL", "http://127.0.0.1:5000")),
        AutomationStore(data_dir),
        timezone_name,
    )
