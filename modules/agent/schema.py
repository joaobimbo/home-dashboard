"""Provider-neutral structured-output schema and prompt."""

import json
from datetime import datetime, timezone
from typing import Dict, List
from zoneinfo import ZoneInfo


SCALAR_SCHEMA = {"type": ["string", "number", "boolean", "null"]}

ACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "device": {"type": "string"},
        "operation": {
            "type": "string",
            "enum": [
                "status",
                "power",
                "toggle",
                "brightness",
                "cover",
                "position",
                "rgbcct",
                "ac_mode",
                "ac_setpoint",
                "ac_fan",
            ],
        },
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "state": {"type": ["string", "null"]},
                "level": {"type": ["integer", "null"]},
                "command": {"type": ["string", "null"]},
                "position": {"type": ["integer", "null"]},
                "mode": {"type": ["string", "null"]},
                "rgb": {
                    "type": ["array", "null"],
                    "items": {"type": "integer"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "color_temp": {"type": ["integer", "null"]},
                "temperature": {"type": ["number", "null"]},
                "speed": {"type": ["string", "null"]},
            },
            "required": [
                "state",
                "level",
                "command",
                "position",
                "mode",
                "rgb",
                "color_temp",
                "temperature",
                "speed",
            ],
        },
    },
    "required": ["device", "operation", "parameters"],
}

EXPRESSION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "source": {
            "type": "string",
            "enum": ["device", "weather", "schedule", "time"],
        },
        "device": {"type": ["string", "null"]},
        "field": {"type": "string"},
        "operator": {
            "type": "string",
            "enum": [
                "eq",
                "ne",
                "gt",
                "gte",
                "lt",
                "lte",
                "between",
                "changes_to",
                "changes_from_to",
                "once",
                "after",
                "daily",
                "weekly",
            ],
        },
        "value": SCALAR_SCHEMA,
        "second_value": SCALAR_SCHEMA,
        "at": {"type": ["string", "null"]},
        "weekdays": {
            "type": "array",
            "items": {"type": "integer", "minimum": 0, "maximum": 6},
            "maxItems": 7,
        },
    },
    "required": [
        "source",
        "device",
        "field",
        "operator",
        "value",
        "second_value",
        "at",
        "weekdays",
    ],
}

STEP_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "kind": {"type": "string", "enum": ["action", "wait"]},
        "seconds": {"type": ["integer", "null"], "minimum": 0},
        "action": {**ACTION_SCHEMA, "type": ["object", "null"]},
    },
    "required": ["kind", "seconds", "action"],
}

AUTOMATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "trigger": EXPRESSION_SCHEMA,
        "conditions": {
            "type": "array",
            "items": EXPRESSION_SCHEMA,
            "maxItems": 10,
        },
        "cancel_conditions": {
            "type": "array",
            "items": EXPRESSION_SCHEMA,
            "maxItems": 10,
        },
        "steps": {"type": "array", "items": STEP_SCHEMA, "maxItems": 20},
        "repeat": {"type": "string", "enum": ["once", "reusable"]},
        "overlap": {"type": "string", "enum": ["ignore", "restart"]},
    },
    "required": [
        "name",
        "description",
        "trigger",
        "conditions",
        "cancel_conditions",
        "steps",
        "repeat",
        "overlap",
    ],
}

INTERPRETATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "kind": {
            "type": "string",
            "enum": [
                "direct_actions",
                "status_query",
                "automation",
                "clarification",
                "unsupported",
            ],
        },
        "reply": {"type": "string"},
        "question": {"type": ["string", "null"]},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "actions": {"type": "array", "items": ACTION_SCHEMA, "maxItems": 10},
        "automation": {**AUTOMATION_SCHEMA, "type": ["object", "null"]},
    },
    "required": [
        "kind",
        "reply",
        "question",
        "assumptions",
        "actions",
        "automation",
    ],
}


SYSTEM_PROMPT = """You translate household requests into a strict home-automation plan.
You never write code and never invent a device or capability. Use only the opaque
device tokens and operations in the supplied catalog. Device names may be Portuguese.

Choose kind=clarification and ask one focused question when materially different
interpretations could change device behaviour. Use direct_actions for immediate
changes, status_query for reads, and automation for persistent rules.

Automations can use device changes, weather, schedules, time/weather/device
conditions, cancellation conditions, waits, and ordered actions. Infer sensible
rule semantics from the request, but expose every material assumption. Use repeat
reusable for event/schedule rules unless the request is explicitly one-time.

Expression rules:
- device fields: state, brightness, position, mode, power, setpoint,
  current_temp, fan_speed, color_temp
- weather fields: temp_c, condition
- device transitions use changes_to or changes_from_to
- relative schedules use source=schedule, operator=after, and value as the
  number of seconds after the user confirms the rule
- clock schedules use source=schedule, operator once/daily/weekly, and at as
  ISO-8601 local datetime for once or HH:MM for daily/weekly; Monday is weekday 0
- use source=schedule (not source=time) for actions at a clock time; for example,
  "open the blinds every day at 7am" is operator=daily with at=07:00
- time conditions use source=time and field=local_time. Use eq/ne/gt/gte/lt/lte
  with value as HH:MM, or between with value and second_value as HH:MM. These
  restrict another trigger; they do not replace a clock schedule trigger
- unused nullable fields must be null and unused weekday lists must be empty

Action parameters not used by an operation must be null. Never use toggle in a
persistent automation. If the request asks for anything outside the catalog or
home control, return unsupported without actions."""


def _clock_context(timezone_name: str) -> str:
    local_now = datetime.now(timezone.utc).astimezone(ZoneInfo(timezone_name))
    return (
        "Current local date/time: "
        + local_now.isoformat(timespec="minutes")
        + f" ({timezone_name})"
    )


def build_user_prompt(
    message: str,
    catalog: List[Dict[str, object]],
    timezone_name: str = "Europe/Lisbon",
) -> str:
    safe_catalog = [
        {
            "token": item["token"],
            "name": item["display_name"],
            "aliases": item.get("other_names", []),
            "room": item.get("room", "Casa"),
            "kind": item["kind"],
            "component": item.get("component"),
            "capabilities": item["capabilities"],
        }
        for item in catalog
    ]
    return (
        _clock_context(timezone_name)
        + "\nCurrent device catalog:\n"
        + json.dumps(safe_catalog, ensure_ascii=False, separators=(",", ":"))
        + "\n\nUser request:\n"
        + message
    )


def build_gemini_prompt(
    message: str,
    catalog: List[Dict[str, object]],
    timezone_name: str = "Europe/Lisbon",
) -> str:
    device_lines = []
    for item in catalog:
        aliases = ", ".join(str(value) for value in item.get("other_names", []))
        device_lines.append(
            "- {token}: name={name}; aliases={aliases}; room={room}; type={kind}/{component}; functions={functions}".format(
                token=item["token"],
                name=json.dumps(item["display_name"], ensure_ascii=False),
                aliases=json.dumps(aliases, ensure_ascii=False),
                room=json.dumps(item.get("room", "Casa"), ensure_ascii=False),
                kind=item["kind"],
                component=item.get("component"),
                functions=",".join(item["capabilities"]),
            )
        )

    return """{clock}

Translate the request into calls using only these devices:
{devices}

Available calls:
status(device); power(device,state=on|off); toggle(device, immediate only);
brightness(device,level=1..100); cover(device,command=open|close|stop);
position(device,position=0..100);
rgbcct(device,state?,level?,mode?,rgb=[red,green,blue]?,color_temp?);
ac_mode(device,mode=auto|cool|heat|dry|fan);
ac_setpoint(device,temperature=10..32); ac_fan(device,speed=auto|low|mid|high).

RGB components must be integer JSON arrays from 0 to 255, for example green is
[0,255,0], never a hex string. Include state="on" when asked to set a colour.

Return only a JSON object, without Markdown. For an immediate request use
{{"kind":"direct_actions","actions":[{{"device":"S1","operation":"power","parameters":{{"state":"off"}}}}]}}.
Use kind=status_query with status actions for reads. If ambiguous, return
{{"kind":"clarification","question":"..."}}. If outside home control, return
{{"kind":"unsupported","reply":"..."}}. Device must always be its token, never its name.

For a saved rule use kind=automation and automation={{name,description,trigger,
conditions,cancel_conditions,steps,repeat,overlap}}. An expression has source
(device/weather/schedule/time), optional device token, field, operator, value,
second_value, at, and weekdays. Device transitions use changes_to or
changes_from_to. Relative requests such as "in 20 seconds" use a schedule
trigger with operator=after and value=20; the countdown begins after confirmation.
For "in 20 seconds turn it on, then 10 seconds later turn it off", use after=20
then action-on, wait=10, action-off. Actions at a clock time must use a schedule
trigger: for example, "open the blinds every day at 7am" uses daily and at=07:00.
Clock schedules use once/daily/weekly and at. Time conditions use source=time,
field=local_time, and eq/ne/gt/gte/lt/lte/between; they are conditions, never
triggers. Steps are
{{"kind":"wait","seconds":1800}} or
{{"kind":"action","action":<call object>}}. The only repeat values are exactly
"once" and "reusable"; relative after rules must use "once". The only overlap
values are exactly "ignore" and "restart". Never use toggle in a rule.

User request: {message}""".format(
        clock=_clock_context(timezone_name),
        devices="\n".join(device_lines),
        message=message,
    )
