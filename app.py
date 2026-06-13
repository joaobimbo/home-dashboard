from flask import Flask, jsonify, render_template, request

from modules.shelly import SceneStore, ShellyController
import os
import subprocess

app = Flask(__name__)
controller = ShellyController.from_sources()
scene_store = SceneStore()


@app.route("/")
def index():
    configured = controller.list_configured_devices()
    rooms = sorted({item.get("room", "Casa") for item in configured})
    return render_template(
        "index.html",
        devices=configured,
        rooms=rooms,
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


@app.route("/screen/off", methods=["GET","POST"])
def screen_off():
    subprocess.run(["xset","dpms","force","off"])
    return {"ok": True}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
