# Thin urequests wrapper around the Flask dashboard's JSON API.
#
# Mirrors skills/shelly.md, skills/daikin.md and skills/weather.md. Every function
# returns whatever the backend returned, parsed from JSON. Network-level failures
# (timeout, no route, connection refused) are caught here and turned into the same
# {"ok": False, "error": ...} shape the backend itself uses for failures, so callers
# never need to special-case "the server said no" vs. "we couldn't reach the server".
#
# Two endpoints (/api/shelly/configured, /api/daikin/devices) return a bare JSON
# array on success rather than a dict - on a network failure they still return the
# {"ok": False, ...} dict shape, so callers must check
# `isinstance(result, dict) and result.get("ok") is False` before assuming a list.

import ujson
import urequests

import config


def _get(path, timeout):
    try:
        resp = urequests.get(config.SERVER_URL + path, timeout=timeout)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    try:
        data = resp.json()
    finally:
        resp.close()
    return data


def _post(path, body, timeout):
    try:
        resp = urequests.post(
            config.SERVER_URL + path,
            data=ujson.dumps(body),
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    try:
        data = resp.json()
    finally:
        resp.close()
    return data


# --- Shelly -------------------------------------------------------------

def get_shelly_configured():
    return _get("/api/shelly/configured", config.HTTP_TIMEOUT_FAST)


def get_shelly_devices():
    return _get("/api/shelly/devices", config.HTTP_TIMEOUT_FAST)


def shelly_action(device_id, action):
    return _post("/api/shelly/%s/action" % device_id, {"action": action}, config.HTTP_TIMEOUT_FAST)


def shelly_cover_action(device_id, command):
    return _post("/api/shelly/%s/cover_action" % device_id, {"command": command}, config.HTTP_TIMEOUT_FAST)


def shelly_position(device_id, position):
    return _post("/api/shelly/%s/position" % device_id, {"position": position}, config.HTTP_TIMEOUT_FAST)


def shelly_light_action(device_id, command):
    return _post("/api/shelly/%s/light_action" % device_id, {"command": command}, config.HTTP_TIMEOUT_FAST)


def shelly_light_level(device_id, brightness):
    return _post("/api/shelly/%s/light_level" % device_id, {"brightness": brightness}, config.HTTP_TIMEOUT_FAST)


# --- Daikin ---------------------------------------------------------------

def get_daikin_devices():
    return _get("/api/daikin/devices", config.HTTP_TIMEOUT_FAST)


def get_daikin_status(device_id, live=False):
    path = "/api/daikin/%s/status" % device_id
    if live:
        path += "?live=1"
    return _get(path, config.HTTP_TIMEOUT_DAIKIN)


def daikin_power(device_id, state):
    return _post("/api/daikin/%s/power" % device_id, {"state": state}, config.HTTP_TIMEOUT_DAIKIN)


def daikin_mode(device_id, mode):
    return _post("/api/daikin/%s/mode" % device_id, {"mode": mode}, config.HTTP_TIMEOUT_DAIKIN)


def daikin_setpoint(device_id, temperature):
    return _post("/api/daikin/%s/setpoint" % device_id, {"temperature": temperature}, config.HTTP_TIMEOUT_DAIKIN)


def daikin_fan(device_id, speed):
    return _post("/api/daikin/%s/fan" % device_id, {"speed": speed}, config.HTTP_TIMEOUT_DAIKIN)


# --- Weather ----------------------------------------------------------------

def get_weather():
    return _get("/api/weather", config.HTTP_TIMEOUT_FAST)
