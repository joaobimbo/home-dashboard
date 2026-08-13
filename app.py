import logging
import os
import subprocess
import uuid

from flask import Flask, jsonify, render_template, request
from modules.shelly import SceneStore, ShellyController
from modules.daikin import DaikinController
from modules.weather import get_weather
from modules.agent.client import DashboardError
from modules.agent.providers import ProviderError
from modules.agent.validation import PlanValidationError
from modules.agent.web import create_web_agent_from_environment


# The dashboard and automation agent poll several read-only endpoints. Keep
# request failures in the journal, but suppress Werkzeug's routine 200 access
# lines so they do not drown out device and application errors.
logging.getLogger("werkzeug").setLevel(logging.WARNING)

app = Flask(__name__)
controller = ShellyController.from_sources()
scene_store = SceneStore()
daikin_controller = DaikinController.from_sources()
daikin_controller.start_background_polling()
web_agent = create_web_agent_from_environment()


@app.route("/")
def index():
    configured = controller.list_configured_devices()
    daikin_devices = daikin_controller.list_configured_devices()
    rooms = sorted(
        {item.get("room", "Casa") for item in configured}
        | {item.get("room", "Casa") for item in daikin_devices}
    )
    return render_template(
        "index.html",
        devices=configured,
        daikin_devices=daikin_devices,
        rooms=rooms,
        web_agent_available=web_agent is not None,
    )


@app.route("/api/status")
def status():
    return jsonify(
        {
            "server": "running",
            "message": "Home dashboard online",
            "devices": len(controller.devices),
        }
    )


@app.route("/api/weather")
def weather():
    result = get_weather()
    status_code = 200 if result.get("ok") else 400
    return jsonify(result), status_code


def _web_agent_browser_id():
    browser_id = request.cookies.get("home_dashboard_agent_browser")
    return browser_id if browser_id and len(browser_id) <= 100 else uuid.uuid4().hex


def _web_agent_response(payload, browser_id, status_code=200):
    response = jsonify(payload)
    response.status_code = status_code
    response.set_cookie("home_dashboard_agent_browser", browser_id, max_age=60 * 60 * 24 * 30, httponly=True, samesite="Lax")
    return response


@app.route("/api/agent/request", methods=["POST"])
def agent_request():
    if web_agent is None:
        return jsonify({"ok": False, "error": "The web agent is not configured on this server"}), 503
    browser_id = _web_agent_browser_id()
    try:
        payload = request.get_json(silent=True) or {}
        return _web_agent_response(web_agent.submit(payload.get("message"), browser_id), browser_id)
    except (ValueError, DashboardError, ProviderError, PlanValidationError) as exc:
        return _web_agent_response({"ok": False, "error": str(exc)}, browser_id, 400)


@app.route("/api/agent/confirm", methods=["POST"])
def agent_confirm():
    if web_agent is None:
        return jsonify({"ok": False, "error": "The web agent is not configured on this server"}), 503
    browser_id = _web_agent_browser_id()
    try:
        payload = request.get_json(silent=True) or {}
        return _web_agent_response(web_agent.confirm(payload.get("token"), browser_id), browser_id)
    except (ValueError, DashboardError, ProviderError, PlanValidationError) as exc:
        return _web_agent_response({"ok": False, "error": str(exc)}, browser_id, 400)


@app.route("/api/shelly/devices")
def shelly_devices():
    return jsonify(controller.read_all())


@app.route("/api/shelly/configured")
def shelly_configured():
    return jsonify(controller.list_configured_devices())


@app.route("/api/shelly/<device_id>/config", methods=["POST"])
def shelly_update_config(device_id):
    payload = request.get_json(silent=True) or {}
    result = controller.update_device_config(device_id, payload)
    status_code = 200 if result.get("ok") else 400
    return jsonify(result), status_code


@app.route("/api/scenes")
def list_scenes():
    return jsonify(scene_store.list_scenes())


@app.route("/api/scenes", methods=["POST"])
def create_scene():
    payload = request.get_json(silent=True) or {}
    result = scene_store.create_scene(
        str(payload.get("name", "")),
        str(payload.get("action", "toggle")),
        str(payload.get("room", "all")),
    )
    status_code = 200 if result.get("ok") else 400
    return jsonify(result), status_code


@app.route("/api/scenes/<scene_id>/run", methods=["POST"])
def run_scene(scene_id):
    scene = scene_store.get_scene(scene_id)
    if not scene:
        return jsonify({"ok": False, "error": "Scene not found"}), 404

    result = controller.apply_action_to_devices(
        scene["action"], scene.get("room", "all")
    )
    return jsonify(result), 200


@app.route("/api/scenes/<scene_id>", methods=["DELETE"])
def delete_scene(scene_id):
    result = scene_store.delete_scene(scene_id)
    status_code = 200 if result.get("ok") else 404
    return jsonify(result), status_code


@app.route("/api/shelly/<device_id>/action", methods=["POST"])
def shelly_action(device_id):
    payload = request.get_json(silent=True) or {}
    action = payload.get("action", "toggle")

    if action not in {"on", "off", "toggle"}:
        return jsonify({"ok": False, "error": "Invalid action"}), 400

    result = controller.apply_action(device_id, action)
    status_code = 200 if result.get("ok") else 400
    return jsonify(result), status_code


@app.route("/api/shelly/<device_id>/position", methods=["POST"])
def shelly_cover_position(device_id):
    payload = request.get_json(silent=True) or {}
    try:
        position = int(payload.get("position"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid position"}), 400

    result = controller.set_cover_position(device_id, position)
    status_code = 200 if result.get("ok") else 400
    return jsonify(result), status_code


@app.route("/api/shelly/<device_id>/cover_action", methods=["POST"])
def shelly_cover_action(device_id):
    payload = request.get_json(silent=True) or {}
    command = str(payload.get("command", "")).strip().lower()
    result = controller.apply_cover_command(device_id, command)
    status_code = 200 if result.get("ok") else 400
    return jsonify(result), status_code


@app.route("/api/shelly/<device_id>/light_action", methods=["POST"])
def shelly_light_action(device_id):
    payload = request.get_json(silent=True) or {}
    command = str(payload.get("command", "")).strip().lower()
    result = controller.apply_light_command(device_id, command)
    status_code = 200 if result.get("ok") else 400
    return jsonify(result), status_code


@app.route("/api/shelly/<device_id>/light_level", methods=["POST"])
def shelly_light_level(device_id):
    payload = request.get_json(silent=True) or {}
    try:
        level = int(payload.get("brightness"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid brightness"}), 400

    result = controller.set_light_brightness(device_id, level)
    status_code = 200 if result.get("ok") else 400
    return jsonify(result), status_code


@app.route("/api/shelly/<device_id>/rgbcct", methods=["POST"])
def shelly_rgbcct(device_id):
    payload = request.get_json(silent=True) or {}
    result = controller.set_rgbcct(device_id, payload)
    status_code = 200 if result.get("ok") else 400
    return jsonify(result), status_code


@app.route("/api/daikin/devices")
def daikin_devices():
    return jsonify(daikin_controller.list_configured_devices())


@app.route("/api/daikin/<device_id>/status")
def daikin_status(device_id):
    if request.args.get("live") == "1":
        result = daikin_controller.get_status(device_id)
    else:
        result = daikin_controller.get_cached_status(device_id)
    status_code = 200 if result.get("ok") else 400
    return jsonify(result), status_code


@app.route("/api/daikin/<device_id>/power", methods=["POST"])
def daikin_power(device_id):
    payload = request.get_json(silent=True) or {}
    state = str(payload.get("state", "")).strip().lower()
    if state not in {"on", "off"}:
        return jsonify({"ok": False, "error": "Invalid state"}), 400
    result = daikin_controller.set_power(device_id, state == "on")
    status_code = 200 if result.get("ok") else 400
    return jsonify(result), status_code


@app.route("/api/daikin/<device_id>/mode", methods=["POST"])
def daikin_mode(device_id):
    payload = request.get_json(silent=True) or {}
    mode = str(payload.get("mode", "")).strip().lower()
    result = daikin_controller.set_mode(device_id, mode)
    status_code = 200 if result.get("ok") else 400
    return jsonify(result), status_code


@app.route("/api/daikin/<device_id>/setpoint", methods=["POST"])
def daikin_setpoint(device_id):
    payload = request.get_json(silent=True) or {}
    try:
        temperature = float(payload.get("temperature"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid temperature"}), 400
    result = daikin_controller.set_setpoint(device_id, temperature)
    status_code = 200 if result.get("ok") else 400
    return jsonify(result), status_code


@app.route("/api/daikin/<device_id>/fan", methods=["POST"])
def daikin_fan(device_id):
    payload = request.get_json(silent=True) or {}
    speed = str(payload.get("speed", "")).strip().lower()
    result = daikin_controller.set_fan_speed(device_id, speed)
    status_code = 200 if result.get("ok") else 400
    return jsonify(result), status_code


@app.route("/screen/off", methods=["GET","POST"])
def screen_off():
    subprocess.run(["xset", "-display", ":0", "dpms","force","off"])
    return {"ok": True}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
