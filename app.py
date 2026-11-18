import logging
import os
import subprocess
import threading
import secrets
import uuid

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException
from modules.shelly import SceneStore, ShellyController
from modules.daikin import DaikinController
from modules.weather import get_weather
from modules.agent.web import AgentBridgeClient, AgentBridgeError
from modules.spotify import SpotifyController


# The dashboard and automation agent poll several read-only endpoints. Keep
# request failures in the journal, but suppress Werkzeug's routine 200 access
# lines so they do not drown out device and application errors.
logging.getLogger("werkzeug").setLevel(logging.WARNING)

app = Flask(__name__)
restart_token = secrets.token_urlsafe(32)
server_instance = uuid.uuid4().hex
restart_lock = threading.Lock()
restart_pending = False


def exit_for_restart():
    # systemd Restart=always restarts the whole process, including stuck BLE threads.
    os._exit(0)

controller = ShellyController.from_sources()
scene_store = SceneStore()
daikin_controller = DaikinController.from_sources()
daikin_controller.start_background_polling()
web_agent = AgentBridgeClient(os.environ.get("AGENT_WEB_URL", "http://127.0.0.1:5001"))
spotify = SpotifyController()


@app.after_request
def log_failed_request(response):
    """Keep actionable failed requests visible in journalctl without 200 noise."""
    if response.status_code >= 400:
        payload = response.get_json(silent=True)
        error_message = payload.get("error") if isinstance(payload, dict) else None
        app.logger.warning(
            "request_failed method=%s path=%s status=%s error=%s",
            request.method,
            request.path,
            response.status_code,
            error_message or response.status,
        )
    return response


@app.errorhandler(Exception)
def log_unhandled_exception(exc):
    if isinstance(exc, HTTPException):
        return exc
    app.logger.exception(
        "request_crashed method=%s path=%s error=%s",
        request.method,
        request.path,
        exc,
    )
    return jsonify({"ok": False, "error": "Unexpected server error; check dashboard logs"}), 500


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
        web_agent_available=True,
        restart_token=restart_token,
        server_instance=server_instance,
    )


@app.route("/api/status")
def status():
    return jsonify(
        {
            "server": "running",
            "instance": server_instance,
            "message": "Home dashboard online",
            "devices": len(controller.devices),
        }
    )


@app.route("/api/service/restart", methods=["POST"])
def restart_service():
    global restart_pending
    payload = request.get_json(silent=True) or {}
    token = payload.get("token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not secrets.compare_digest(token, restart_token):
        return jsonify({"ok": False, "error": "Atualize a página antes de reiniciar."}), 403
    if not os.environ.get("INVOCATION_ID"):
        return jsonify({"ok": False, "error": "Restart requires the systemd service"}), 503
    with restart_lock:
        if not restart_pending:
            restart_pending = True
            app.logger.warning("Dashboard restart requested from the dashboard")
            timer = threading.Timer(1.0, exit_for_restart)
            timer.daemon = True
            timer.start()
    return jsonify({"ok": True, "instance": server_instance}), 202


@app.route("/api/service/logs")
def service_logs():
    units = {"dashboard": "home-dashboard.service", "agent": "home-dashboard-agent.service"}
    unit = units.get(request.args.get("service", "dashboard"))
    if unit is None:
        return jsonify({"ok": False, "error": "Unknown service"}), 400
    if not secrets.compare_digest(request.headers.get("X-Dashboard-Token", ""), restart_token):
        return jsonify({"ok": False, "error": "Atualize a página para ver os registos."}), 403
    try:
        logs = subprocess.run(
            ["journalctl", "--quiet", "--no-pager", "--unit", unit,
             "--lines", "150", "--output", "short-iso"],
            capture_output=True, text=True, timeout=5)
        state = subprocess.run(["systemctl", "is-active", unit],
                               capture_output=True, text=True, timeout=3)
        if logs.returncode != 0:
            return jsonify({"ok": False, "error": "Não foi possível ler os registos."}), 503
        response = jsonify({"ok": True, "unit": unit,
                            "state": state.stdout.strip() or "unknown",
                            "logs": logs.stdout[-100000:]})
        response.headers["Cache-Control"] = "no-store"
        return response
    except (OSError, subprocess.TimeoutExpired):
        return jsonify({"ok": False, "error": "Registos indisponíveis. A tentar novamente…"}), 503


@app.route("/api/weather")
def weather():
    result = get_weather()
    status_code = 200 if result.get("ok") else 400
    return jsonify(result), status_code

@app.route('/api/spotify/auth/status')
def spotify_auth_status(): return jsonify(spotify.auth_status())
@app.route('/api/spotify/login')
def spotify_login():
    from flask import redirect
    if not spotify.configured: return jsonify({'ok':False,'error':'Spotify is not configured'}),503
    return redirect(spotify.login_url())
@app.route('/api/spotify/callback')
def spotify_callback():
    from flask import redirect
    spotify.callback(request.args.get('code',''),request.args.get('state',''))
    return redirect('/')
@app.route('/api/spotify/status')
def spotify_status(): return jsonify(spotify.status())
@app.route('/api/spotify/devices')
def spotify_devices(): return jsonify(spotify.devices())
@app.route('/api/spotify/search')
def spotify_search(): return jsonify(spotify.search(request.args.get('q','')))
@app.route('/api/spotify/<command>',methods=['POST'])
def spotify_command(command):
    payload=request.get_json(silent=True) or {}
    try:
        if command in {'play','pause','next','previous'}: return jsonify(spotify.command(command,payload))
        if command=='device': return jsonify(spotify.transfer(payload.get('device_id')))
        if command=='volume': return jsonify(spotify.volume(payload.get('volume'),payload.get('device_id')))
        if command=='play-uri': return jsonify(spotify.play_uri(payload.get('uri'),payload.get('device_id')))
        if command=='play-playlist': return jsonify(spotify.play_playlist_query(payload.get('query'),payload.get('device_id')))
        return jsonify({'ok':False,'error':'Invalid Spotify command'}),404
    except Exception:
        app.logger.exception("spotify_command_failed command=%s", command)
        return jsonify({'ok':False,'error':'Spotify command failed; check dashboard logs'}),500


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
    browser_id = _web_agent_browser_id()
    try:
        payload = request.get_json(silent=True) or {}
        return _web_agent_response(web_agent.submit(payload.get("message"), browser_id), browser_id)
    except (ValueError, AgentBridgeError) as exc:
        return _web_agent_response({"ok": False, "error": str(exc)}, browser_id, 503)


@app.route("/api/agent/confirm", methods=["POST"])
def agent_confirm():
    browser_id = _web_agent_browser_id()
    try:
        payload = request.get_json(silent=True) or {}
        return _web_agent_response(web_agent.confirm(payload.get("token"), browser_id), browser_id)
    except (ValueError, AgentBridgeError) as exc:
        return _web_agent_response({"ok": False, "error": str(exc)}, browser_id, 503)


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


@app.route("/screen/off", methods=["GET", "POST"])
def screen_off():
    # The dashboard boots into tty1 without an X server. Console blanking
    # requires the exact command allowed by deploy/home-dashboard-screen.sudoers.
    try:
        with open("/dev/tty1", "r+b", buffering=0) as console:
            result = subprocess.run(
                ["sudo", "-n", "/usr/bin/setterm", "--term", "linux", "--blank", "force"],
                stdin=console,
                stdout=console,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )
        # setterm can report ioctl failures on stderr while returning zero.
        if result.returncode != 0 or result.stderr.strip():
            app.logger.error("Console screen-off failed: %s", result.stderr.strip())
            return {"ok": False, "error": "Console blanking failed; check screen-control sudo permissions and dashboard logs"}, 503
    except (OSError, subprocess.TimeoutExpired):
        app.logger.exception("Console screen-off failed")
        return {"ok": False, "error": "Console blanking unavailable; check dashboard logs"}, 503
    return {"ok": True}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
