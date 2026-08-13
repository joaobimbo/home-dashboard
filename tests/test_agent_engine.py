import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from modules.agent.engine import AutomationEngine
from modules.agent.store import AutomationStore


class FakeDashboard:
    def __init__(self):
        self.actions = []

    def execute(self, action):
        self.actions.append(action)
        return {"ok": True}


def event_rule():
    return {
        "schema_version": 1,
        "name": "Delayed AC off",
        "description": "",
        "enabled": True,
        "trigger": {
            "source": "device",
            "field": "state",
            "operator": "changes_to",
            "value": "off",
            "second_value": None,
            "device_id": "light-1",
            "device_kind": "shelly",
            "display_name": "Light",
            "at": None,
            "weekdays": [],
        },
        "conditions": [],
        "cancel_conditions": [],
        "steps": [
            {"kind": "wait", "seconds": 1800},
            {
                "kind": "action",
                "action": {
                    "device_id": "ac-1",
                    "device_kind": "daikin",
                    "component": "ac",
                    "display_name": "AC",
                    "operation": "power",
                    "parameters": {"state": "off"},
                },
            },
        ],
        "repeat": "reusable",
        "overlap": "ignore",
    }


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = AutomationStore(self.temp.name)
        self.rule = self.store.create_rule(event_rule(), 10, -100)
        self.client = FakeDashboard()
        self.messages = []
        self.engine = AutomationEngine(
            self.store,
            self.client,
            notifier=lambda chat, message: self.messages.append((chat, message)),
        )
        self.assertEqual(self.engine.device_poll_seconds, 30)
        self.start = datetime(2026, 8, 11, 20, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def snapshot(state):
        return {"devices": {"light-1": {"ok": True, "state": state}}, "weather": None}

    def test_transition_wait_and_action(self):
        self.engine.tick(self.start, self.snapshot("on"))
        self.engine.tick(self.start + timedelta(seconds=10), self.snapshot("off"))
        pending = self.store.get_state()["runs"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(self.client.actions, [])

        self.engine.tick(self.start + timedelta(minutes=29), self.snapshot("off"))
        self.assertEqual(self.client.actions, [])
        self.engine.tick(self.start + timedelta(minutes=31), self.snapshot("off"))
        self.assertEqual(len(self.client.actions), 1)
        self.assertFalse(self.store.get_state()["runs"])
        self.assertIn("completed", self.messages[-1][1])

    def test_initial_off_state_does_not_trigger(self):
        self.engine.tick(self.start, self.snapshot("off"))
        self.assertFalse(self.store.get_state()["runs"])

    def test_disable_cancels_pending_run(self):
        self.engine.tick(self.start, self.snapshot("on"))
        self.engine.tick(self.start + timedelta(seconds=10), self.snapshot("off"))
        self.store.set_enabled(self.rule["id"], False, 10)
        self.assertFalse(self.store.get_state()["runs"])

    def test_recovered_overdue_run_rechecks_conditions(self):
        rule = self.store.get_rule(self.rule["id"])
        rule["conditions"] = [
            {
                "source": "device",
                "field": "state",
                "operator": "eq",
                "value": "off",
                "second_value": None,
                "device_id": "light-1",
                "device_kind": "shelly",
                "display_name": "Light",
                "at": None,
                "weekdays": [],
            }
        ]
        # Replace persisted copy for this isolated recovery test.
        self.store.delete_rule(self.rule["id"], 10)
        saved = self.store.create_rule(rule, 10, -100)
        state = self.store.get_state()
        state["runs"] = [
            {
                "id": "recovered",
                "rule_id": saved["id"],
                "step_index": 1,
                "due_at": (self.start - timedelta(minutes=1)).isoformat(),
                "started_at": (self.start - timedelta(minutes=31)).isoformat(),
            }
        ]
        self.store.save_state(state)
        engine = AutomationEngine(
            self.store,
            self.client,
            notifier=lambda chat, message: self.messages.append((chat, message)),
        )
        engine.tick(self.start, self.snapshot("on"))
        self.assertEqual(self.client.actions, [])
        self.assertFalse(self.store.get_state()["runs"])
        self.assertIn("skipped after restart", self.messages[-1][1])

    def test_daily_schedule_fires_at_due_time_not_during_baseline(self):
        schedule = event_rule()
        schedule["name"] = "Daily AC off"
        schedule["trigger"] = {
            "source": "schedule",
            "field": "local_time",
            "operator": "daily",
            "value": None,
            "second_value": None,
            "at": "21:00",
            "weekdays": [],
        }
        schedule["steps"] = schedule["steps"][1:]
        self.store.create_rule(schedule, 10, -100)
        self.engine.tick(
            datetime(2026, 8, 11, 19, 0, tzinfo=timezone.utc),
            self.snapshot("on"),
        )
        self.assertEqual(self.client.actions, [])
        self.engine.tick(
            datetime(2026, 8, 11, 20, 0, 10, tzinfo=timezone.utc),
            self.snapshot("on"),
        )
        self.assertEqual(len(self.client.actions), 1)

    def test_relative_schedule_runs_sequence_from_rule_creation(self):
        schedule = event_rule()
        schedule["name"] = "Office light pulse"
        schedule["trigger"] = {
            "source": "schedule",
            "field": "local_time",
            "operator": "after",
            "value": 20,
            "second_value": None,
            "at": None,
            "weekdays": [],
        }
        light_action = {
            "device_id": "light-1",
            "device_kind": "shelly",
            "component": "switch",
            "display_name": "Light",
            "operation": "power",
        }
        schedule["steps"] = [
            {"kind": "action", "action": {**light_action, "parameters": {"state": "on"}}},
            {"kind": "wait", "seconds": 10},
            {"kind": "action", "action": {**light_action, "parameters": {"state": "off"}}},
        ]
        schedule["repeat"] = "once"
        saved = self.store.create_rule(schedule, 10, -100)
        created = datetime.fromisoformat(saved["schedule_anchor_at"])

        self.engine.tick(created + timedelta(seconds=19), self.snapshot("on"))
        self.assertEqual(self.client.actions, [])
        self.engine.tick(created + timedelta(seconds=20), self.snapshot("on"))
        self.assertEqual(self.client.actions[-1]["parameters"], {"state": "on"})
        self.engine.tick(created + timedelta(seconds=29), self.snapshot("on"))
        self.assertEqual(len(self.client.actions), 1)
        self.engine.tick(created + timedelta(seconds=30), self.snapshot("on"))
        self.assertEqual(self.client.actions[-1]["parameters"], {"state": "off"})
        self.assertFalse(self.store.get_rule(saved["id"])["enabled"])

        self.client.actions = []
        reenabled = self.store.set_enabled(saved["id"], True, 10)
        restarted = datetime.fromisoformat(reenabled["schedule_anchor_at"])
        self.assertNotIn(saved["id"], self.store.get_state()["last_schedule"])
        self.engine.tick(restarted + timedelta(seconds=19), self.snapshot("on"))
        self.assertEqual(self.client.actions, [])
        self.engine.tick(restarted + timedelta(seconds=20), self.snapshot("on"))
        self.assertEqual(self.client.actions[-1]["parameters"], {"state": "on"})


if __name__ == "__main__":
    unittest.main()
