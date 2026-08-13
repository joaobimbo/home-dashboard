"""Local authorization and semantic validation for model-produced plans."""

import re
from datetime import datetime
from typing import Dict, List, Optional


class PlanValidationError(ValueError):
    pass


DEVICE_FIELDS = {
    "shelly": {"state", "brightness", "position", "mode", "color_temp"},
    "daikin": {"power", "mode", "setpoint", "current_temp", "fan_speed"},
}
WEATHER_FIELDS = {"temp_c", "condition"}
COMPARISON_OPERATORS = {"eq", "ne", "gt", "gte", "lt", "lte", "between"}
TRANSITION_OPERATORS = {"changes_to", "changes_from_to"}


def _require(condition: bool, message: str):
    if not condition:
        raise PlanValidationError(message)


def _device_index(catalog: List[Dict[str, object]]) -> Dict[str, Dict[str, object]]:
    return {str(item["token"]): item for item in catalog}


def _compact_parameters(parameters: object) -> Dict[str, object]:
    _require(isinstance(parameters, dict), "Action parameters must be an object")
    allowed = {
        "state",
        "level",
        "command",
        "position",
        "mode",
        "rgb",
        "color_temp",
        "temperature",
        "speed",
    }
    _require(set(parameters).issubset(allowed), "Unknown action parameter")
    return {key: value for key, value in parameters.items() if value is not None}


def validate_action(
    action: object,
    catalog: List[Dict[str, object]],
    persistent: bool = False,
) -> Dict[str, object]:
    _require(isinstance(action, dict), "Action must be an object")
    token = str(action.get("device", ""))
    device = _device_index(catalog).get(token)
    _require(device is not None, f"Unknown device token: {token}")
    operation = str(action.get("operation", ""))
    if persistent:
        _require(operation not in {"toggle", "status"}, "Unsafe persistent action")
    capabilities = set(device.get("capabilities", []))
    _require(operation in capabilities, f"{device['display_name']} cannot {operation}")
    params = _compact_parameters(action.get("parameters", {}))

    if operation == "status":
        _require(not params, "Status does not accept parameters")
    elif operation == "power":
        _require(params == {"state": params.get("state")}, "Power only accepts state")
        _require(params.get("state") in {"on", "off"}, "Invalid power state")
    elif operation == "toggle":
        _require(not params, "Toggle does not accept parameters")
    elif operation == "brightness":
        _require(set(params) == {"level"}, "Brightness requires level")
        _require(type(params["level"]) is int and 1 <= params["level"] <= 100, "Invalid brightness")
    elif operation == "cover":
        _require(set(params) == {"command"}, "Cover requires command")
        _require(params["command"] in {"open", "close", "stop"}, "Invalid cover command")
    elif operation == "position":
        _require(set(params) == {"position"}, "Position requires position")
        _require(type(params["position"]) is int and 0 <= params["position"] <= 100, "Invalid position")
    elif operation == "rgbcct":
        _validate_rgbcct(params)
    elif operation == "ac_mode":
        _require(set(params) == {"mode"}, "AC mode requires mode")
        _require(params["mode"] in {"auto", "cool", "heat", "dry", "fan"}, "Invalid AC mode")
    elif operation == "ac_setpoint":
        _require(set(params) == {"temperature"}, "Setpoint requires temperature")
        _require(isinstance(params["temperature"], (int, float)) and not isinstance(params["temperature"], bool), "Invalid setpoint")
        _require(10 <= float(params["temperature"]) <= 32, "Setpoint out of range")
    elif operation == "ac_fan":
        _require(set(params) == {"speed"}, "Fan requires speed")
        _require(params["speed"] in {"auto", "low", "mid", "high"}, "Invalid fan speed")

    return {
        "device_id": device["id"],
        "device_kind": device["kind"],
        "component": device.get("component"),
        "display_name": device["display_name"],
        "operation": operation,
        "parameters": params,
    }


def _validate_rgbcct(params: Dict[str, object]):
    allowed = {"state", "level", "mode", "rgb", "color_temp"}
    _require(params and set(params).issubset(allowed), "Invalid RGBCCT parameters")
    _require("state" in params or "level" in params, "RGBCCT requires state or brightness")
    if "state" in params:
        _require(params["state"] in {"on", "off"}, "Invalid RGBCCT state")
    if "level" in params:
        _require(type(params["level"]) is int and 1 <= params["level"] <= 100, "Invalid RGBCCT brightness")
    if "mode" in params:
        _require(params["mode"] in {"rgb", "cct"}, "Invalid RGBCCT mode")
    if "rgb" in params:
        rgb = params["rgb"]
        if isinstance(rgb, str):
            match = re.fullmatch(r"#?([0-9a-fA-F]{6})", rgb)
            _require(match is not None, "Invalid RGB value")
            value = match.group(1)
            rgb = [int(value[index : index + 2], 16) for index in (0, 2, 4)]
            params["rgb"] = rgb
        _require(isinstance(rgb, list) and len(rgb) == 3, "Invalid RGB value")
        _require(all(type(value) is int and 0 <= value <= 255 for value in rgb), "Invalid RGB value")
    if "color_temp" in params:
        value = params["color_temp"]
        _require(type(value) is int and 2700 <= value <= 6500, "Invalid color temperature")


def validate_expression(
    expression: object,
    catalog: List[Dict[str, object]],
    trigger: bool = False,
) -> Dict[str, object]:
    _require(isinstance(expression, dict), "Expression must be an object")
    source = str(expression.get("source", ""))
    operator = str(expression.get("operator", ""))
    result = {
        "source": source,
        "field": str(expression.get("field", "")),
        "operator": operator,
        "value": expression.get("value"),
        "second_value": expression.get("second_value"),
        "at": expression.get("at"),
        "weekdays": expression.get("weekdays") or [],
    }

    if source == "device":
        token = str(expression.get("device") or "")
        device = _device_index(catalog).get(token)
        _require(device is not None, f"Unknown device token: {token}")
        _require(result["field"] in DEVICE_FIELDS[device["kind"]], "Invalid device field")
        allowed = COMPARISON_OPERATORS | (TRANSITION_OPERATORS if trigger else set())
        _require(operator in allowed, "Invalid device operator")
        result.update(
            {
                "device_id": device["id"],
                "device_kind": device["kind"],
                "display_name": device["display_name"],
            }
        )
    elif source == "weather":
        _require(result["field"] in WEATHER_FIELDS, "Invalid weather field")
        allowed = COMPARISON_OPERATORS | (TRANSITION_OPERATORS if trigger else set())
        _require(operator in allowed, "Invalid weather operator")
    elif source == "schedule":
        _require(trigger, "Schedule is only valid as a trigger")
        _require(operator in {"once", "after", "daily", "weekly"}, "Invalid schedule")
        if operator == "after":
            seconds = result["value"]
            _require(
                type(seconds) is int and 0 <= seconds <= 365 * 24 * 60 * 60,
                "Invalid relative schedule",
            )
        elif operator == "once":
            at = str(result["at"] or "")
            try:
                datetime.fromisoformat(at)
            except ValueError as exc:
                raise PlanValidationError("Invalid one-time schedule") from exc
        else:
            at = str(result["at"] or "")
            _require(_valid_hhmm(at), "Invalid schedule time")
        if operator == "weekly":
            _require(bool(result["weekdays"]), "Weekly schedule requires weekdays")
    elif source == "time":
        _require(not trigger, "Clock comparisons are conditions, not triggers")
        _require(result["field"] == "local_time", "Invalid time field")
        _require(operator in COMPARISON_OPERATORS, "Invalid time condition")
        _require(_valid_hhmm(str(result["value"])), "Invalid time value")
        if operator == "between":
            _require(
                _valid_hhmm(str(result["second_value"])),
                "Invalid time window",
            )
    else:
        raise PlanValidationError("Invalid expression source")
    return result


def _valid_hhmm(value: str) -> bool:
    try:
        datetime.strptime(value, "%H:%M")
        return True
    except ValueError:
        return False


def validate_interpretation(
    raw: object,
    catalog: List[Dict[str, object]],
) -> Dict[str, object]:
    _require(isinstance(raw, dict), "Provider response must be an object")
    kind = str(raw.get("kind", ""))
    _require(
        kind in {"direct_actions", "status_query", "automation", "clarification", "unsupported"},
        "Invalid interpretation kind",
    )
    result: Dict[str, object] = {
        "kind": kind,
        "reply": str(raw.get("reply", "")).strip()[:1000],
        "question": str(raw.get("question") or "").strip()[:500],
        "assumptions": [str(item)[:300] for item in raw.get("assumptions", [])][:10],
    }

    if kind in {"direct_actions", "status_query"}:
        actions = raw.get("actions")
        _require(isinstance(actions, list) and 1 <= len(actions) <= 10, "No actions supplied")
        validated = [validate_action(item, catalog) for item in actions]
        if kind == "status_query":
            _require(all(item["operation"] == "status" for item in validated), "Status query may only read")
        else:
            _require(all(item["operation"] != "status" for item in validated), "Direct action may not mix status")
        result["actions"] = validated
    elif kind == "automation":
        result["automation"] = validate_automation(raw.get("automation"), catalog)
    elif kind == "clarification":
        _require(bool(result["question"]), "Clarification question is empty")
    return result


def validate_automation(raw: object, catalog: List[Dict[str, object]]) -> Dict[str, object]:
    _require(isinstance(raw, dict), "Automation is missing")
    name = str(raw.get("name", "")).strip()
    _require(1 <= len(name) <= 80, "Invalid automation name")
    conditions = raw.get("conditions", [])
    cancel_conditions = raw.get("cancel_conditions", [])
    steps = raw.get("steps", [])
    _require(isinstance(conditions, list) and len(conditions) <= 10, "Too many conditions")
    _require(isinstance(cancel_conditions, list) and len(cancel_conditions) <= 10, "Too many cancel conditions")
    _require(isinstance(steps, list) and 1 <= len(steps) <= 20, "Invalid automation steps")
    validated_steps = []
    action_count = 0
    for step in steps:
        _require(isinstance(step, dict), "Invalid automation step")
        if step.get("kind") == "wait":
            seconds = step.get("seconds")
            _require(type(seconds) is int and 0 <= seconds <= 365 * 24 * 60 * 60, "Invalid wait")
            validated_steps.append({"kind": "wait", "seconds": seconds})
        elif step.get("kind") == "action":
            action_count += 1
            validated_steps.append(
                {"kind": "action", "action": validate_action(step.get("action"), catalog, persistent=True)}
            )
        else:
            raise PlanValidationError("Invalid automation step kind")
    _require(1 <= action_count <= 10, "Automation must contain actions")
    trigger = validate_expression(raw.get("trigger"), catalog, trigger=True)
    if trigger["source"] == "schedule" and trigger["operator"] in {"after", "once"}:
        # These triggers identify a single schedule slot. Their execution policy
        # is deterministic, so do not depend on provider-specific vocabulary such
        # as "one_time" versus "once".
        repeat = "once"
        overlap = "ignore"
    else:
        repeat = str(raw.get("repeat", ""))
        overlap = str(raw.get("overlap", ""))
        _require(repeat in {"once", "reusable"}, "Invalid repeat policy")
        _require(overlap in {"ignore", "restart"}, "Invalid overlap policy")
    return {
        "schema_version": 1,
        "name": name,
        "description": str(raw.get("description", "")).strip()[:500],
        "trigger": trigger,
        "conditions": [validate_expression(item, catalog) for item in conditions],
        "cancel_conditions": [validate_expression(item, catalog) for item in cancel_conditions],
        "steps": validated_steps,
        "repeat": repeat,
        "overlap": overlap,
        "enabled": True,
    }
