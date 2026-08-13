"""Persistent, deterministic executor for validated automation rules."""

import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from .client import DashboardClient, DashboardError
from .store import AutomationStore


logger = logging.getLogger(__name__)


Notifier = Callable[[int, str], None]


class AutomationEngine:
    def __init__(
        self,
        store: AutomationStore,
        client: DashboardClient,
        notifier: Optional[Notifier] = None,
        timezone_name: str = "Europe/Lisbon",
        device_poll_seconds: int = 30,
        weather_poll_seconds: int = 15 * 60,
    ):
        self.store = store
        self.client = client
        self.notifier = notifier or (lambda _chat_id, _message: None)
        self.timezone = ZoneInfo(timezone_name)
        self.device_poll_seconds = max(1, int(device_poll_seconds))
        self.weather_poll_seconds = max(60, int(weather_poll_seconds))
        self._snapshot: Dict[str, object] = {"devices": {}, "weather": None}
        self._last_device_poll = 0.0
        self._last_weather_poll = 0.0
        self._stop = threading.Event()
        self._recovery_run_ids = {
            str(run.get("id")) for run in self.store.get_state().get("runs", [])
        }

    def stop(self):
        self._stop.set()

    def run_forever(self):
        logger.info("automation_engine_started")
        while not self._stop.wait(1.0):
            try:
                self.tick()
            except Exception as exc:
                logger.exception("automation_engine_error error=%s", exc)
                self.store.audit("engine_error", error=str(exc)[:500])
        logger.info("automation_engine_stopped")

    def tick(
        self,
        now: Optional[datetime] = None,
        snapshot: Optional[Dict[str, object]] = None,
    ):
        current = now or datetime.now(timezone.utc)
        monotonic_now = time.monotonic()
        if snapshot is not None:
            self._snapshot = snapshot
        else:
            if monotonic_now - self._last_device_poll >= self.device_poll_seconds:
                fresh = self.client.snapshot(include_weather=False)
                self._snapshot["devices"] = fresh.get("devices", {})
                self._last_device_poll = monotonic_now
            if monotonic_now - self._last_weather_poll >= self.weather_poll_seconds:
                self._snapshot["weather"] = self.client.weather()
                self._last_weather_poll = monotonic_now

        state = self.store.get_state()
        state.setdefault("last_triggered", {})
        changed = False
        rules = {rule["id"]: rule for rule in self.store.list_rules() if rule.get("enabled")}

        for rule in rules.values():
            fired, observation = self._triggered(
                rule["trigger"],
                state["observations"].get(rule["id"]),
                state["last_schedule"].get(rule["id"]),
                current,
                rule.get("schedule_anchor_at") or rule.get("created_at"),
            )
            if observation is not None and state["observations"].get(rule["id"]) != observation:
                state["observations"][rule["id"]] = observation
                changed = True
            if observation and observation.get("schedule_slot"):
                slot = observation["schedule_slot"]
                if state["last_schedule"].get(rule["id"]) != slot:
                    state["last_schedule"][rule["id"]] = slot
                    changed = True
            if fired and self._all_conditions(rule.get("conditions", []), current):
                changed = self._start_run(rule, state, current) or changed

        active_runs = []
        for run in list(state["runs"]):
            rule = rules.get(run.get("rule_id"))
            if rule is None:
                changed = True
                continue
            if self._any_condition(rule.get("cancel_conditions", []), current):
                self._notify(rule, f"Automation '{rule['name']}' cancelled by its conditions.")
                self.store.audit("run_cancelled", rule_id=rule["id"], run_id=run.get("id"))
                changed = True
                continue
            due_at = datetime.fromisoformat(str(run["due_at"]))
            if due_at.tzinfo is None:
                due_at = due_at.replace(tzinfo=timezone.utc)
            if current < due_at:
                active_runs.append(run)
                continue

            recovering = str(run.get("id")) in self._recovery_run_ids
            self._recovery_run_ids.discard(str(run.get("id")))
            if recovering and not self._all_conditions(rule.get("conditions", []), current):
                self._notify(rule, f"Automation '{rule['name']}' skipped after restart because its conditions no longer match.")
                self.store.audit("run_skipped_after_restart", rule_id=rule["id"], run_id=run.get("id"))
                changed = True
                continue

            keep = self._advance_run(rule, run, current)
            changed = True
            if keep:
                active_runs.append(run)
            elif rule.get("repeat") == "once":
                try:
                    self.store.set_enabled(str(rule["id"]), False, user_id=0)
                    state["observations"].pop(rule["id"], None)
                    state["last_schedule"].pop(rule["id"], None)
                    state["last_triggered"].pop(rule["id"], None)
                except KeyError:
                    pass

        if state["runs"] != active_runs:
            state["runs"] = active_runs
            changed = True
        if changed:
            self.store.save_state(state)

    def _start_run(self, rule: Dict[str, object], state: Dict[str, object], now: datetime) -> bool:
        previous_trigger = state["last_triggered"].get(rule["id"])
        if previous_trigger:
            try:
                elapsed = now.timestamp() - datetime.fromisoformat(previous_trigger).timestamp()
                if elapsed < 60:
                    return False
            except ValueError:
                pass
        existing = [run for run in state["runs"] if run.get("rule_id") == rule["id"]]
        if existing and rule.get("overlap") == "ignore":
            return False
        if existing and rule.get("overlap") == "restart":
            state["runs"] = [run for run in state["runs"] if run.get("rule_id") != rule["id"]]
        state["runs"].append(
            {
                "id": uuid.uuid4().hex[:12],
                "rule_id": rule["id"],
                "step_index": 0,
                "due_at": now.astimezone(timezone.utc).isoformat(),
                "started_at": now.astimezone(timezone.utc).isoformat(),
            }
        )
        state["last_triggered"][rule["id"]] = now.astimezone(timezone.utc).isoformat()
        self.store.audit("run_started", rule_id=rule["id"])
        logger.info(
            "automation_run_started rule_id=%s name=%r overlap=%s",
            rule["id"],
            rule.get("name"),
            rule.get("overlap"),
        )
        return True

    def _advance_run(self, rule: Dict[str, object], run: Dict[str, object], now: datetime) -> bool:
        steps = rule.get("steps", [])
        while int(run["step_index"]) < len(steps):
            step = steps[int(run["step_index"])]
            run["step_index"] = int(run["step_index"]) + 1
            if step.get("kind") == "wait":
                seconds = int(step.get("seconds", 0))
                run["due_at"] = datetime.fromtimestamp(
                    now.timestamp() + seconds, tz=timezone.utc
                ).isoformat()
                return True
            action = step.get("action")
            try:
                logger.info(
                    "automation_action_started rule_id=%s run_id=%s operation=%s device_id=%s parameters=%r",
                    rule["id"],
                    run.get("id"),
                    action.get("operation"),
                    action.get("device_id"),
                    action.get("parameters"),
                )
                result = self.client.execute(action)
                self.store.audit(
                    "action_succeeded",
                    rule_id=rule["id"],
                    run_id=run.get("id"),
                    operation=action.get("operation"),
                    device_id=action.get("device_id"),
                )
                if not result.get("ok"):
                    raise DashboardError(str(result.get("error") or "Action failed"))
                logger.info(
                    "automation_action_succeeded rule_id=%s run_id=%s operation=%s device_id=%s result=%r",
                    rule["id"],
                    run.get("id"),
                    action.get("operation"),
                    action.get("device_id"),
                    result,
                )
            except Exception as exc:
                logger.warning(
                    "automation_action_failed rule_id=%s run_id=%s operation=%s device_id=%s error=%s",
                    rule["id"],
                    run.get("id"),
                    action.get("operation"),
                    action.get("device_id"),
                    exc,
                )
                self.store.audit(
                    "action_failed",
                    rule_id=rule["id"],
                    run_id=run.get("id"),
                    error=str(exc)[:500],
                )
                self._notify(rule, f"Automation '{rule['name']}' failed: {exc}")
                return False
        self.store.audit("run_completed", rule_id=rule["id"], run_id=run.get("id"))
        self._notify(rule, f"Automation '{rule['name']}' completed successfully.")
        return False

    def _triggered(
        self,
        expression: Dict[str, object],
        previous: Optional[Dict[str, object]],
        last_schedule: Optional[str],
        now: datetime,
        created_at: Optional[str] = None,
    ):
        source = expression.get("source")
        if source == "schedule":
            slot, due = self._schedule_slot(expression, now, created_at)
            observation = {"schedule_slot": slot} if slot and due else None
            return bool(due and slot != last_schedule), observation

        current_value = self._expression_value(expression, now)
        current_match = self._compare(expression, current_value)
        observation = {"value": current_value, "matched": current_match}
        if previous is None:
            return False, observation
        operator = expression.get("operator")
        if operator == "changes_to":
            fired = previous.get("value") != current_value and current_value == expression.get("value")
        elif operator == "changes_from_to":
            fired = previous.get("value") == expression.get("value") and current_value == expression.get("second_value")
        else:
            fired = not bool(previous.get("matched")) and current_match
        return fired, observation

    def _schedule_slot(
        self,
        expression: Dict[str, object],
        now: datetime,
        created_at: Optional[str] = None,
    ):
        local_now = now.astimezone(self.timezone)
        operator = expression.get("operator")
        at = str(expression.get("at") or "")
        if operator in {"once", "after"}:
            if operator == "after":
                if not created_at:
                    return None, False
                scheduled = datetime.fromisoformat(created_at)
                scheduled = datetime.fromtimestamp(
                    scheduled.timestamp() + int(expression.get("value", 0)),
                    tz=timezone.utc,
                )
            else:
                scheduled = datetime.fromisoformat(at)
            if scheduled.tzinfo is None:
                scheduled = scheduled.replace(tzinfo=self.timezone)
            scheduled = scheduled.astimezone(self.timezone)
            delta = (local_now - scheduled).total_seconds()
            return scheduled.isoformat(), 0 <= delta < 60
        hour, minute = [int(value) for value in at.split(":", 1)]
        scheduled = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if operator == "weekly" and local_now.weekday() not in expression.get("weekdays", []):
            return None, False
        delta = (local_now - scheduled).total_seconds()
        slot = f"{scheduled.date().isoformat()}T{at}"
        return slot, 0 <= delta < 60

    def _all_conditions(self, expressions: List[Dict[str, object]], now: datetime) -> bool:
        return all(self._compare(item, self._expression_value(item, now)) for item in expressions)

    def _any_condition(self, expressions: List[Dict[str, object]], now: datetime) -> bool:
        return any(self._compare(item, self._expression_value(item, now)) for item in expressions)

    def _expression_value(self, expression: Dict[str, object], now: datetime):
        source = expression.get("source")
        if source == "device":
            device = self._snapshot.get("devices", {}).get(expression.get("device_id"), {})
            return device.get(expression.get("field")) if isinstance(device, dict) else None
        if source == "weather":
            weather = self._snapshot.get("weather")
            return weather.get(expression.get("field")) if isinstance(weather, dict) else None
        if source == "time":
            return now.astimezone(self.timezone).strftime("%H:%M")
        return None

    @staticmethod
    def _compare(expression: Dict[str, object], actual) -> bool:
        if actual is None:
            return False
        operator = expression.get("operator")
        expected = expression.get("value")
        second = expression.get("second_value")
        try:
            if operator in {"changes_to", "changes_from_to"}:
                return actual == (second if operator == "changes_from_to" else expected)
            if operator == "eq":
                return actual == expected
            if operator == "ne":
                return actual != expected
            if operator == "gt":
                return actual > expected
            if operator == "gte":
                return actual >= expected
            if operator == "lt":
                return actual < expected
            if operator == "lte":
                return actual <= expected
            if operator == "between":
                if isinstance(actual, str) and isinstance(expected, str) and isinstance(second, str):
                    if expected <= second:
                        return expected <= actual <= second
                    return actual >= expected or actual <= second
                return expected <= actual <= second
        except TypeError:
            return False
        return False

    def _notify(self, rule: Dict[str, object], message: str):
        try:
            self.notifier(int(rule["origin_chat_id"]), message)
        except Exception as exc:
            self.store.audit("notification_failed", rule_id=rule.get("id"), error=str(exc)[:500])
