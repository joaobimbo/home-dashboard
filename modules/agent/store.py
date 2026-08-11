"""Atomic JSON persistence for rules, pending runs, and audit events."""

import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


class AutomationStore:
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.rules_path = self.data_dir / "rules.json"
        self.state_path = self.data_dir / "state.json"
        self.audit_path = self.data_dir / "audit.jsonl"
        self._lock = threading.RLock()
        self._rules = self._load(
            self.rules_path, {"schema_version": 1, "rules": []}, "rules"
        )
        self._state = self._load(
            self.state_path,
            {
                "schema_version": 1,
                "observations": {},
                "runs": [],
                "last_schedule": {},
                "last_triggered": {},
            },
            "state",
        )

    @staticmethod
    def _load(path: Path, default: Dict[str, object], label: str) -> Dict[str, object]:
        if not path.exists():
            return default
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Invalid automation {label} file: {path}") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise RuntimeError(f"Unsupported automation {label} schema")
        return payload

    @staticmethod
    def _copy(value):
        return json.loads(json.dumps(value))

    def list_rules(self) -> List[Dict[str, object]]:
        with self._lock:
            return self._copy(self._rules["rules"])

    def get_rule(self, rule_id: str) -> Optional[Dict[str, object]]:
        with self._lock:
            for rule in self._rules["rules"]:
                if rule.get("id") == rule_id:
                    return self._copy(rule)
        return None

    def create_rule(
        self,
        rule: Dict[str, object],
        creator_user_id: int,
        origin_chat_id: int,
    ) -> Dict[str, object]:
        with self._lock:
            if len(self._rules["rules"]) >= 100:
                raise ValueError("The automation limit of 100 rules has been reached")
            saved = self._copy(rule)
            created_at = datetime.now(timezone.utc).isoformat()
            saved.update(
                {
                    "id": uuid.uuid4().hex[:10],
                    "creator_user_id": int(creator_user_id),
                    "origin_chat_id": int(origin_chat_id),
                    "created_at": created_at,
                    "enabled": True,
                }
            )
            if self._is_relative_schedule(saved):
                saved["schedule_anchor_at"] = created_at
            self._rules["rules"].append(saved)
            self._write_json(self.rules_path, self._rules)
            self.audit("rule_created", rule_id=saved["id"], user_id=creator_user_id)
            return self._copy(saved)

    def set_enabled(self, rule_id: str, enabled: bool, user_id: int) -> Dict[str, object]:
        with self._lock:
            rule = self._find_rule(rule_id)
            rule["enabled"] = bool(enabled)
            updated_at = datetime.now(timezone.utc).isoformat()
            rule["updated_at"] = updated_at
            if enabled and self._is_relative_schedule(rule):
                rule["schedule_anchor_at"] = updated_at
            if not enabled:
                self._state["runs"] = [
                    run for run in self._state["runs"] if run.get("rule_id") != rule_id
                ]
            self._state["observations"].pop(rule_id, None)
            self._state["last_schedule"].pop(rule_id, None)
            self._state.setdefault("last_triggered", {}).pop(rule_id, None)
            self._write_json(self.state_path, self._state)
            self._write_json(self.rules_path, self._rules)
            self.audit(
                "rule_enabled" if enabled else "rule_disabled",
                rule_id=rule_id,
                user_id=user_id,
            )
            return self._copy(rule)

    @staticmethod
    def _is_relative_schedule(rule: Dict[str, object]) -> bool:
        trigger = rule.get("trigger")
        return bool(
            isinstance(trigger, dict)
            and trigger.get("source") == "schedule"
            and trigger.get("operator") == "after"
        )

    def delete_rule(self, rule_id: str, user_id: int) -> Dict[str, object]:
        with self._lock:
            rule = self._find_rule(rule_id)
            self._rules["rules"] = [
                item for item in self._rules["rules"] if item.get("id") != rule_id
            ]
            self._state["runs"] = [
                run for run in self._state["runs"] if run.get("rule_id") != rule_id
            ]
            self._state["observations"].pop(rule_id, None)
            self._state["last_schedule"].pop(rule_id, None)
            self._state.setdefault("last_triggered", {}).pop(rule_id, None)
            self._write_json(self.rules_path, self._rules)
            self._write_json(self.state_path, self._state)
            self.audit("rule_deleted", rule_id=rule_id, user_id=user_id)
            return self._copy(rule)

    def get_state(self) -> Dict[str, object]:
        with self._lock:
            return self._copy(self._state)

    def save_state(self, state: Dict[str, object]):
        if state.get("schema_version") != 1:
            raise ValueError("Invalid automation state schema")
        with self._lock:
            self._state = self._copy(state)
            self._write_json(self.state_path, self._state)

    def audit(self, event: str, **fields):
        payload = {
            "at": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **fields,
        }
        line = json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n"
        with self._lock:
            with self.audit_path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())

    def _find_rule(self, rule_id: str) -> Dict[str, object]:
        for rule in self._rules["rules"]:
            if rule.get("id") == rule_id:
                return rule
        raise KeyError(f"Unknown rule: {rule_id}")

    @staticmethod
    def _write_json(path: Path, payload: Dict[str, object]):
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(
            prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
