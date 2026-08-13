import unittest

from modules.agent.validation import (
    PlanValidationError,
    validate_action,
    validate_expression,
    validate_interpretation,
)


def parameters(**values):
    return values


CATALOG = [
    {
        "token": "S1",
        "id": "office-light",
        "kind": "shelly",
        "component": "switch",
        "display_name": "Luz Escritorio",
        "capabilities": ["status", "power", "toggle"],
    },
    {
        "token": "R1",
        "id": "rgb-light",
        "kind": "shelly",
        "component": "rgbcct",
        "display_name": "RGB",
        "capabilities": ["status", "power", "toggle", "rgbcct"],
    },
    {
        "token": "A1",
        "id": "office-ac",
        "kind": "daikin",
        "component": "ac",
        "display_name": "AC Escritorio",
        "capabilities": ["status", "power", "ac_mode", "ac_setpoint", "ac_fan"],
    },
    {
        "token": "S2",
        "id": "bedroom-cover",
        "kind": "shelly",
        "component": "cover",
        "display_name": "Estores Quarto",
        "capabilities": ["status", "cover", "position"],
    },
]


class ValidationTests(unittest.TestCase):
    def test_resolves_opaque_token_to_existing_device(self):
        action = validate_action(
            {"device": "A1", "operation": "power", "parameters": parameters(state="off")},
            CATALOG,
        )
        self.assertEqual(action["device_id"], "office-ac")
        self.assertEqual(action["parameters"], {"state": "off"})

    def test_rejects_unknown_device_and_parameter(self):
        with self.assertRaises(PlanValidationError):
            validate_action(
                {"device": "A99", "operation": "power", "parameters": parameters(state="off")},
                CATALOG,
            )
        with self.assertRaises(PlanValidationError):
            validate_action(
                {"device": "A1", "operation": "power", "parameters": {"state": "off", "url": "http://evil"}},
                CATALOG,
            )

    def test_rejects_toggle_in_persistent_rule(self):
        with self.assertRaises(PlanValidationError):
            validate_action(
                {"device": "S1", "operation": "toggle", "parameters": {}},
                CATALOG,
                persistent=True,
            )

    def test_validates_rgb_ranges(self):
        result = validate_action(
            {
                "device": "R1",
                "operation": "rgbcct",
                "parameters": {"mode": "rgb", "rgb": [255, 10, 0], "level": 60},
            },
            CATALOG,
            persistent=True,
        )
        self.assertEqual(result["parameters"]["rgb"], [255, 10, 0])
        hex_result = validate_action(
            {
                "device": "R1",
                "operation": "rgbcct",
                "parameters": {"state": "on", "rgb": "00FF00"},
            },
            CATALOG,
        )
        self.assertEqual(hex_result["parameters"]["rgb"], [0, 255, 0])
        hash_hex_result = validate_action(
            {
                "device": "R1",
                "operation": "rgbcct",
                "parameters": {"state": "on", "rgb": "#ff000a"},
            },
            CATALOG,
        )
        self.assertEqual(hash_hex_result["parameters"]["rgb"], [255, 0, 10])
        with self.assertRaises(PlanValidationError):
            validate_action(
                {"device": "R1", "operation": "rgbcct", "parameters": {"rgb": [256, 0, 0]}},
                CATALOG,
            )

    def test_validates_spotify_transfer(self):
        catalog = CATALOG + [{"token": "P1", "id": "echo", "kind": "spotify", "display_name": "Echo", "capabilities": ["spotify_transfer"]}]
        result = validate_action({"device": "P1", "operation": "spotify_transfer", "parameters": {}}, catalog, persistent=True)
        self.assertEqual(result["device_id"], "echo")
        with self.assertRaises(PlanValidationError):
            validate_action(
                {
                    "device": "R1",
                    "operation": "rgbcct",
                    "parameters": {"state": "on", "rgb": "green"},
                },
                CATALOG,
            )

    def test_validates_reusable_event_rule(self):
        raw = {
            "kind": "automation",
            "reply": "",
            "question": None,
            "assumptions": [],
            "actions": [],
            "automation": {
                "name": "AC after office light",
                "description": "Turn the office AC off after the light turns off",
                "trigger": {
                    "source": "device",
                    "device": "S1",
                    "field": "state",
                    "operator": "changes_to",
                    "value": "off",
                    "second_value": None,
                    "at": None,
                    "weekdays": [],
                },
                "conditions": [],
                "cancel_conditions": [],
                "steps": [
                    {"kind": "wait", "seconds": 1800, "action": None},
                    {
                        "kind": "action",
                        "seconds": None,
                        "action": {
                            "device": "A1",
                            "operation": "power",
                            "parameters": {"state": "off"},
                        },
                    },
                ],
                "repeat": "reusable",
                "overlap": "ignore",
            },
        }
        result = validate_interpretation(raw, CATALOG)
        rule = result["automation"]
        self.assertEqual(rule["trigger"]["device_id"], "office-light")
        self.assertEqual(rule["steps"][1]["action"]["device_id"], "office-ac")

    def test_validates_relative_one_time_schedule(self):
        raw = {
            "kind": "automation",
            "automation": {
                "name": "Office light pulse",
                "description": "Turn on after 20 seconds, then off 10 seconds later",
                "trigger": {
                    "source": "schedule",
                    "device": None,
                    "field": "local_time",
                    "operator": "after",
                    "value": 20,
                    "second_value": None,
                    "at": None,
                    "weekdays": [],
                },
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
                    },
                    {"kind": "wait", "seconds": 10},
                    {
                        "kind": "action",
                        "action": {
                            "device": "S1",
                            "operation": "power",
                            "parameters": {"state": "off"},
                        },
                    },
                ],
                "repeat": "one_time",
                "overlap": "single",
            },
        }
        result = validate_interpretation(raw, CATALOG)
        self.assertEqual(result["automation"]["trigger"]["operator"], "after")
        self.assertEqual(result["automation"]["trigger"]["value"], 20)
        self.assertEqual(result["automation"]["repeat"], "once")
        self.assertEqual(result["automation"]["overlap"], "ignore")

    def test_validates_daily_clock_schedule_for_cover(self):
        raw = {
            "kind": "automation",
            "automation": {
                "name": "Open bedroom blinds at seven",
                "description": "Open the bedroom blinds every day at 07:00",
                "trigger": {
                    "source": "schedule",
                    "field": "local_time",
                    "operator": "daily",
                    "value": None,
                    "second_value": None,
                    "at": "07:00",
                    "weekdays": [],
                },
                "conditions": [],
                "cancel_conditions": [],
                "steps": [
                    {
                        "kind": "action",
                        "action": {
                            "device": "S2",
                            "operation": "cover",
                            "parameters": {"command": "open"},
                        },
                    }
                ],
                "repeat": "reusable",
                "overlap": "ignore",
            },
        }

        result = validate_interpretation(raw, CATALOG)["automation"]

        self.assertEqual(result["trigger"]["at"], "07:00")
        self.assertEqual(result["steps"][0]["action"]["device_id"], "bedroom-cover")

    def test_normalizes_gemini_schedule_type_alias(self):
        raw = {
            "kind": "automation",
            "automation": {
                "name": "Turn RGB red at five",
                "description": "Sets the RGB light to red at 17:00",
                "trigger": {"source": "schedule", "type": "daily", "at": "17:00"},
                "conditions": [],
                "cancel_conditions": [],
                "steps": [
                    {
                        "kind": "action",
                        "action": {
                            "device": "R1",
                            "operation": "rgbcct",
                            "parameters": {"state": "on", "rgb": [255, 0, 0]},
                        },
                    }
                ],
                "repeat": "reusable",
                "overlap": "ignore",
            },
        }

        result = validate_interpretation(raw, CATALOG)["automation"]

        self.assertEqual(result["trigger"]["operator"], "daily")
        self.assertEqual(result["trigger"]["at"], "17:00")

    def test_validates_clock_comparison_conditions(self):
        for operator in ("eq", "ne", "gt", "gte", "lt", "lte"):
            result = validate_expression(
                {
                    "source": "time",
                    "field": "local_time",
                    "operator": operator,
                    "value": "07:00",
                    "second_value": None,
                },
                CATALOG,
            )
            self.assertEqual(result["operator"], operator)

        with self.assertRaisesRegex(PlanValidationError, "Invalid time value"):
            validate_expression(
                {
                    "source": "time",
                    "field": "local_time",
                    "operator": "gte",
                    "value": "25:00",
                },
                CATALOG,
            )

    def test_rejects_time_window_as_trigger(self):
        raw = {
            "kind": "automation",
            "automation": {
                "name": "Bad timer",
                "trigger": {
                    "source": "time",
                    "field": "local_time",
                    "operator": "between",
                    "value": "00:00",
                    "second_value": "00:01",
                },
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
                "repeat": "once",
                "overlap": "ignore",
            },
        }
        with self.assertRaisesRegex(PlanValidationError, "Clock comparisons are conditions"):
            validate_interpretation(raw, CATALOG)


if __name__ == "__main__":
    unittest.main()
