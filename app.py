from flask import Flask, jsonify, render_template, request

from modules.shelly import ShellyController

app = Flask(__name__)
controller = ShellyController.from_sources()


@app.route("/")
def index():
    return render_template("index.html", devices=controller.devices)


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


@app.route("/api/shelly/<device_id>/action", methods=["POST"])
def shelly_action(device_id):
    payload = request.get_json(silent=True) or {}
    action = payload.get("action", "toggle")

    if action not in {"on", "off", "toggle"}:
        return jsonify({"ok": False, "error": "Invalid action"}), 400

    result = controller.apply_action(device_id, action)
    status_code = 200 if result.get("ok") else 400
    return jsonify(result), status_code


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
