import unittest

from modules.agent.web import WebAgent


CATALOG = [
    {
        "token": "S1",
        "id": "desk-light",
        "kind": "shelly",
        "component": "switch",
        "display_name": "Desk light",
        "capabilities": ["status", "power", "toggle"],
    }
]


class FakeProvider:
    def __init__(self, plan):
        self.plan = plan

    def interpret(self, _message, _catalog, _safety_identifier):
        return self.plan


class FakeClient:
    def catalog(self):
        return CATALOG

    def execute(self, _action):
        return {"ok": True, "state": "on"}

    def snapshot(self, _include_weather):
        return {"devices": {"desk-light": {"ok": True, "state": "on"}}}


class FakeStore:
    def __init__(self):
        self.rules = []

    def audit(self, *_args, **_kwargs):
        pass

    def list_rules(self):
        return list(self.rules)

    def create_rule(self, rule, **_kwargs):
        saved = dict(rule)
        saved["id"] = "rule-1"
        self.rules.append(saved)
        return saved

    def delete_rule(self, rule_id, **_kwargs):
        for rule in self.rules:
            if rule["id"] == rule_id:
                self.rules.remove(rule)
                return rule
        raise KeyError(rule_id)


class WebAgentTests(unittest.TestCase):
    def test_executes_validated_direct_action(self):
        agent = WebAgent(
            FakeProvider(
                {
                    "kind": "direct_actions",
                    "actions": [
                        {"device": "S1", "operation": "power", "parameters": {"state": "on"}}
                    ],
                }
            ),
            "test",
            "test-model",
            FakeClient(),
            FakeStore(),
            "Europe/Lisbon",
        )

        result = agent.submit("Turn on desk light", "browser-1")

        self.assertEqual(result["kind"], "direct_actions")
        self.assertEqual(result["message"], "Desk light: state=on")

    def test_requires_browser_bound_confirmation_for_automation(self):
        agent = WebAgent(
            FakeProvider(
                {
                    "kind": "automation",
                    "automation": {
                        "name": "Desk light morning",
                        "description": "Turn on the desk light",
                        "trigger": {"source": "schedule", "operator": "daily", "at": "07:00"},
                        "conditions": [],
                        "cancel_conditions": [],
                        "steps": [
                            {
                                "kind": "action",
                                "action": {
                                    "device": "S1",
                                    "operation": "power",
                                    "parameters": {"state": "on"},
                                },
                            }
                        ],
                        "repeat": "reusable",
                        "overlap": "ignore",
                    },
                }
            ),
            "test",
            "test-model",
            FakeClient(),
            FakeStore(),
            "Europe/Lisbon",
        )

        preview = agent.submit("Turn on desk light every morning", "browser-1")

        self.assertEqual(preview["kind"], "automation_confirmation")
        with self.assertRaisesRegex(ValueError, "another browser"):
            agent.confirm(preview["token"], "browser-2")
        saved = agent.confirm(preview["token"], "browser-1")
        self.assertEqual(saved["kind"], "automation_saved")
