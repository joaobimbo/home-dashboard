"""Synchronous web adapter for the validated home-automation agent."""

import hashlib
import json
import logging
import threading
import time
import uuid
from typing import Dict
from urllib import error, parse, request

from .client import DashboardClient, DashboardError
from .providers import LanguageProvider, ProviderError
from .store import AutomationStore
from .validation import PlanValidationError, validate_interpretation


logger = logging.getLogger(__name__)


class WebAgent:
    """Run web requests through the agent without exposing provider keys."""

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
        self._lock = threading.RLock()

    def submit(self, message: object, browser_id: str) -> Dict[str, object]:
        text = str(message or "").strip()
        if not 1 <= len(text) <= 1000:
            raise ValueError("Enter a request of up to 1000 characters")

        with self._lock:
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
        with self._lock:
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
        logger.info("web_automation_saved rule_id=%s name=%r", rule["id"], rule["name"])
        return {"ok": True, "kind": "automation_saved", "message": "Automation saved: " + rule["name"]}

    def _handle_plan(self, plan: Dict[str, object], original: str, browser_id: str) -> Dict[str, object]:
        kind = plan["kind"]
        if kind == "clarification":
            with self._lock:
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
        with self._lock:
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
        lines.append("Steps:")
        for step in rule.get("steps", []):
            if step.get("kind") == "wait": lines.append("• wait " + str(step.get("seconds")) + " seconds")
            else:
                action = step.get("action", {})
                lines.append("• " + str(action.get("display_name")) + ": " + str(action.get("operation")) + " " + str(action.get("parameters")))
        return "\n".join(line for line in lines if line)


class AgentBridgeError(RuntimeError):
    pass


class AgentBridgeClient:
    """Dashboard-side client for the localhost-only agent bridge."""

    def __init__(self, base_url: str = "http://127.0.0.1:5001"):
        parsed = parse.urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Agent bridge must use HTTP on the local host")
        self.base_url = base_url.rstrip("/")

    def submit(self, message: object, browser_id: str) -> Dict[str, object]:
        return self._post("/request", {"message": message}, browser_id)

    def confirm(self, token: object, browser_id: str) -> Dict[str, object]:
        return self._post("/confirm", {"token": token}, browser_id)

    def _post(self, path: str, payload: Dict[str, object], browser_id: str) -> Dict[str, object]:
        req = request.Request(
            self.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Home-Dashboard-Browser": browser_id},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=75) as response:
                result = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            try:
                result = json.loads(exc.read().decode("utf-8"))
                message = result.get("error") if isinstance(result, dict) else None
            except (json.JSONDecodeError, UnicodeDecodeError):
                message = None
            raise AgentBridgeError(str(message or "Agent request failed")) from exc
        except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise AgentBridgeError("Agent service is unavailable") from exc
        if not isinstance(result, dict):
            raise AgentBridgeError("Agent service returned an invalid response")
        return result


def create_agent_bridge_app(web_agent: WebAgent):
    """Create the agent's private HTTP bridge, bound to loopback by its runner."""
    from flask import Flask, jsonify, request as flask_request

    app = Flask(__name__)

    def browser_id():
        value = flask_request.headers.get("X-Home-Dashboard-Browser", "")
        if not value or len(value) > 100:
            raise ValueError("Invalid browser session")
        return value

    @app.post("/request")
    def submit():
        try:
            payload = flask_request.get_json(silent=True) or {}
            return jsonify(web_agent.submit(payload.get("message"), browser_id()))
        except (ValueError, DashboardError, ProviderError, PlanValidationError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.post("/confirm")
    def confirm():
        try:
            payload = flask_request.get_json(silent=True) or {}
            return jsonify(web_agent.confirm(payload.get("token"), browser_id()))
        except (ValueError, DashboardError, ProviderError, PlanValidationError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    return app


def start_agent_bridge(web_agent: WebAgent, port: int = 5001):
    """Start a threaded agent bridge on loopback and return its WSGI server."""
    from werkzeug.serving import make_server

    server = make_server("127.0.0.1", port, create_agent_bridge_app(web_agent), threaded=True)
    thread = threading.Thread(target=server.serve_forever, name="agent-web-bridge", daemon=True)
    thread.start()
    logger.info("agent_web_bridge_started host=127.0.0.1 port=%d", port)
    return server
