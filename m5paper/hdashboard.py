# apps/hdashboard.py
#
# M5PaperS3 dashboard panel - single-file UIFlow2 MicroPython app.
#
# A touch-control panel mirroring the home-dashboard web UI: weather, and full
# touch control of lights, blinds, and AC. Pure client of the existing Flask API
# (/api/shelly/*, /api/daikin/*, /api/weather) - no backend changes, nothing here
# talks to devices directly. See README.md in this folder for deployment steps,
# config, and the on-device verification checklist.
#
# The try/except at the bottom keeps on-device errors visible via
# utility.print_error_msg instead of silently dying with no serial console
# attached.

import time

import M5
import ujson
import urequests
from M5 import Lcd, Touch


# ============================================================
# Configuration - edit these before uploading
# ============================================================

# LAN address of the Flask dashboard server, e.g. "http://192.168.1.50:5000"
# (find it from what `python app.py` prints on startup, or `hostname -I` on the host).
SERVER_URL = "http://192.168.1.50:5000"

# Polling cadence, in milliseconds. Matches static/app.js's cadence on the web dashboard.
SHELLY_POLL_MS = 30000
AC_POLL_MS = 30000
WEATHER_POLL_MS = 900000

# HTTP timeouts, in seconds. Daikin calls are slow on purpose (real BLE round trip).
HTTP_TIMEOUT_FAST = 10
HTTP_TIMEOUT_DAIKIN = 30

# Force a full (flash) e-paper refresh every N partial refreshes, to clear ghosting.
FULL_REFRESH_EVERY = 20

# Main loop tick, in milliseconds - how often touch is polled and timers are checked.
TICK_MS = 100


# ============================================================
# Hardware - the only section touching M5Unified/UIFlow2 APIs directly.
#
# `from M5 import Lcd, Touch` + Lcd.setCursor()/.print() for text match a real
# M5Stack-authored example (apps/helloworld.py), not just doc summaries.
# Lcd.setEpdMode() controls e-paper refresh quality/speed - there's no separate
# flush/push call, draws update the panel directly under whichever mode is
# currently set. Touch is Touch.getCount() + Touch.getDetail(0) (an 11-element
# TUPLE, not an object - index 5 is wasPressed) plus separate
# Touch.getX()/getY() calls for coordinates (confirmed via the official UIFlow2
# MicroPython docs, uiflow-micropython.readthedocs.io).
#
# Still unverified: whether individual draw calls each visibly flash the panel
# during a redraw, or whether some batching exists to make a frame atomic - see
# README.md's verification checklist.
# ============================================================

WIDTH = 960
HEIGHT = 540

BLACK = 0x000000
WHITE = 0xFFFFFF

EPD_QUALITY = 0
EPD_TEXT = 1
EPD_FAST = 2
EPD_FASTEST = 3


def hw_init():
    global WIDTH, HEIGHT
    M5.begin()
    WIDTH = Lcd.width()
    HEIGHT = Lcd.height()
    Lcd.setEpdMode(EPD_QUALITY)
    Lcd.clear(WHITE)


def hw_clear():
    Lcd.fillScreen(WHITE)


def fill_rect(x, y, w, h, color=WHITE):
    Lcd.fillRect(x, y, w, h, color)


def draw_rect(x, y, w, h, color=BLACK):
    Lcd.drawRect(x, y, w, h, color)


def draw_text(s, x, y, color=BLACK, size=1):
    Lcd.setTextSize(size)
    Lcd.setTextColor(color, WHITE)
    Lcd.setCursor(x, y)
    Lcd.print(s)


def begin_frame(full=False):
    """Sets the e-paper refresh mode for the draw calls that follow. full=True
    for a clean/ghost-clearing pass (tab switches, periodic ghost-clearing),
    full=False for quick updates (busy-state flips, polls)."""
    Lcd.setEpdMode(EPD_QUALITY if full else EPD_FASTEST)


def poll_touch():
    """Return (x, y) of a new touch press (down-edge only), or None."""
    M5.update()
    if Touch.getCount() > 0:
        detail = Touch.getDetail(0)
        was_pressed = detail[5]  # wasPressed
        if was_pressed:
            return Touch.getX(), Touch.getY()
    return None


# ============================================================
# Flask API client - thin urequests wrapper.
#
# Mirrors skills/shelly.md, skills/daikin.md and skills/weather.md. Every
# function returns whatever the backend returned, parsed from JSON. Network-level
# failures (timeout, no route, connection refused) are caught here and turned
# into the same {"ok": False, "error": ...} shape the backend itself uses for
# failures, so callers never need to special-case "the server said no" vs. "we
# couldn't reach the server".
#
# Two endpoints (get_shelly_configured, get_daikin_devices) return a bare JSON
# array on success rather than a dict - on a network failure they still return
# the {"ok": False, ...} dict shape, so callers must check
# `isinstance(result, dict) and result.get("ok") is False` before assuming a list.
# ============================================================


def _get(path, timeout):
    try:
        resp = urequests.get(SERVER_URL + path, timeout=timeout)
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
            SERVER_URL + path,
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


def get_shelly_configured():
    return _get("/api/shelly/configured", HTTP_TIMEOUT_FAST)


def get_shelly_devices():
    return _get("/api/shelly/devices", HTTP_TIMEOUT_FAST)


def shelly_action(device_id, action):
    return _post("/api/shelly/%s/action" % device_id, {"action": action}, HTTP_TIMEOUT_FAST)


def shelly_cover_action(device_id, command):
    return _post("/api/shelly/%s/cover_action" % device_id, {"command": command}, HTTP_TIMEOUT_FAST)


def shelly_position(device_id, position):
    return _post("/api/shelly/%s/position" % device_id, {"position": position}, HTTP_TIMEOUT_FAST)


def shelly_light_action(device_id, command):
    return _post("/api/shelly/%s/light_action" % device_id, {"command": command}, HTTP_TIMEOUT_FAST)


def shelly_light_level(device_id, brightness):
    return _post("/api/shelly/%s/light_level" % device_id, {"brightness": brightness}, HTTP_TIMEOUT_FAST)


def get_daikin_devices():
    return _get("/api/daikin/devices", HTTP_TIMEOUT_FAST)


def get_daikin_status(device_id, live=False):
    path = "/api/daikin/%s/status" % device_id
    if live:
        path += "?live=1"
    return _get(path, HTTP_TIMEOUT_DAIKIN)


def daikin_power(device_id, state):
    return _post("/api/daikin/%s/power" % device_id, {"state": state}, HTTP_TIMEOUT_DAIKIN)


def daikin_mode(device_id, mode):
    return _post("/api/daikin/%s/mode" % device_id, {"mode": mode}, HTTP_TIMEOUT_DAIKIN)


def daikin_setpoint(device_id, temperature):
    return _post("/api/daikin/%s/setpoint" % device_id, {"temperature": temperature}, HTTP_TIMEOUT_DAIKIN)


def daikin_fan(device_id, speed):
    return _post("/api/daikin/%s/fan" % device_id, {"speed": speed}, HTTP_TIMEOUT_DAIKIN)


def get_weather():
    return _get("/api/weather", HTTP_TIMEOUT_FAST)


# ============================================================
# Shared tab identifiers
# ============================================================

TAB_AC = "ac"
TAB_LIGHTS = "lights"
TAB_COVERS = "covers"


# ============================================================
# App state + change detection.
#
# Change detection matters here specifically because e-paper redraws are slow
# and visibly flicker - refresh_shelly()/refresh_daikin() return True only when
# something in the fetched data actually differs from the last poll, so the main
# loop can skip repainting (and skip the panel refresh entirely) on an unchanged
# poll tick.
# ============================================================


class AppState:
    def __init__(self):
        self.shelly_devices = []   # merged configured + live status, list of dicts
        self.daikin_devices = []   # merged configured + status, list of dicts
        self.weather = None
        self.online = True
        self.active_tab = None
        self.active_modal = None   # None or {"type": ..., "device_id": ...}
        self.busy_ids = set()
        self.page = 0
        self.hit_regions = []
        self._last_shelly_snapshot = {}
        self._last_daikin_snapshot = {}

    # --- tabs ---------------------------------------------------------------

    def available_tabs(self):
        tabs = []
        if self.daikin_devices:
            tabs.append(TAB_AC)
        if any(d.get("component") != "cover" for d in self.shelly_devices):
            tabs.append(TAB_LIGHTS)
        if any(d.get("component") == "cover" for d in self.shelly_devices):
            tabs.append(TAB_COVERS)
        return tabs

    def ensure_active_tab(self):
        tabs = self.available_tabs()
        if self.active_tab not in tabs:
            self.active_tab = tabs[0] if tabs else None

    def devices_for_tab(self, tab):
        if tab == TAB_AC:
            return self.daikin_devices
        if tab == TAB_COVERS:
            return [d for d in self.shelly_devices if d.get("component") == "cover"]
        if tab == TAB_LIGHTS:
            return [d for d in self.shelly_devices if d.get("component") != "cover"]
        return []

    # --- refresh + change detection -----------------------------------------

    def refresh_shelly(self):
        configured = get_shelly_configured()
        if isinstance(configured, dict) and configured.get("ok") is False:
            self.online = False
            return False
        live = get_shelly_devices()
        if isinstance(live, dict) and live.get("ok") is False:
            self.online = False
            return False

        live_by_id = dict((d["id"], d) for d in live)
        merged = []
        for cfg in configured:
            row = dict(cfg)
            row.update(live_by_id.get(cfg["id"], {}))
            merged.append(row)

        self.shelly_devices = merged
        self.online = True
        return self._diff_snapshot("_last_shelly_snapshot", merged)

    def refresh_daikin(self, live=False):
        configured = get_daikin_devices()
        if isinstance(configured, dict) and configured.get("ok") is False:
            self.online = False
            return False

        merged = []
        for cfg in configured:
            status = get_daikin_status(cfg["id"], live=live)
            row = dict(cfg)
            if status.get("ok"):
                row.update(status)
            merged.append(row)

        self.daikin_devices = merged
        self.online = True
        return self._diff_snapshot("_last_daikin_snapshot", merged)

    def refresh_weather(self):
        result = get_weather()
        if result.get("ok"):
            self.weather = result
            return True
        return False

    def _diff_snapshot(self, attr, rows):
        snapshot = dict((r["id"], _stable_repr(r)) for r in rows)
        changed = snapshot != getattr(self, attr)
        setattr(self, attr, snapshot)
        return changed

    # --- busy tracking (mirrors static/app.js's is-busy class) --------------

    def set_busy(self, device_id, busy):
        if busy:
            self.busy_ids.add(device_id)
        else:
            self.busy_ids.discard(device_id)

    def is_busy(self, device_id):
        return device_id in self.busy_ids


def _stable_repr(row):
    return tuple(sorted(row.items()))


# ============================================================
# Screen geometry and touch hit-testing. No hardware calls here - pure math.
# ============================================================

TAB_LABELS = {TAB_AC: "AC", TAB_LIGHTS: "Luzes", TAB_COVERS: "Estores"}

HEADER_H = 70
TABS_H = 60
FOOTER_H = 30

GRID_COLS = 2
GRID_ROWS = 3
TILE_PAD = 8


def header_rect():
    return (0, 0, WIDTH, HEADER_H)


def tabs_rect():
    return (0, HEADER_H, WIDTH, TABS_H)


def tab_button_rect(index, count):
    w = WIDTH // max(count, 1)
    x0, y0, _, h = tabs_rect()
    return (x0 + index * w, y0, w, h)


def body_rect():
    top = HEADER_H + TABS_H
    bottom = HEIGHT - FOOTER_H
    return (0, top, WIDTH, bottom - top)


def footer_rect():
    return (0, HEIGHT - FOOTER_H, WIDTH, FOOTER_H)


def page_size():
    return GRID_COLS * GRID_ROWS


def tile_rect(slot):
    """slot is 0-indexed position within the current grid page."""
    bx, by, bw, bh = body_rect()
    col = slot % GRID_COLS
    row = slot // GRID_COLS
    tw = bw // GRID_COLS
    th = bh // GRID_ROWS
    return (bx + col * tw + TILE_PAD, by + row * th + TILE_PAD, tw - 2 * TILE_PAD, th - 2 * TILE_PAD)


def ac_row_rect(slot, total_rows):
    bx, by, bw, bh = body_rect()
    rh = bh // max(total_rows, 1)
    return (bx + TILE_PAD, by + slot * rh + TILE_PAD, bw - 2 * TILE_PAD, rh - 2 * TILE_PAD)


def modal_rect():
    margin = 60
    return (margin, margin, WIDTH - 2 * margin, HEIGHT - 2 * margin)


def point_in_rect(x, y, rect):
    rx, ry, rw, rh = rect
    return rx <= x < rx + rw and ry <= y < ry + rh


def hit_test(x, y, regions):
    """regions: list of (rect, action) tuples. Last-drawn (most specific/on-top)
    wins on overlap, so scan in reverse."""
    for rect, action in reversed(regions):
        if point_in_rect(x, y, rect):
            return action
    return None


# ============================================================
# Drawing. Each draw_* function paints its region and returns the list of
# (rect, action) hit regions a tap in that area should trigger - the main loop
# collects these into app.hit_regions each frame, and hit_test() looks them up
# against touch input. Modals use preset buttons rather than sliders throughout
# (position/brightness/setpoint/mode/fan) since continuous drag feedback doesn't
# work well against e-paper's slow refresh.
# ============================================================

MODE_LABELS = {"auto": "Auto", "cool": "Frio", "heat": "Calor", "dry": "Seco", "fan": "Vent."}
FAN_LABELS = {"auto": "Auto", "low": "Low", "mid": "Mid", "high": "High"}


def draw_header(app):
    x, y, w, h = header_rect()
    fill_rect(x, y, w, h, WHITE)
    draw_text(_clock_text(), x + 10, y + h // 2 - 8, size=2)

    if app.weather and app.weather.get("ok"):
        label = "%s C  %s" % (app.weather["temp_c"], app.weather["condition"])
    else:
        label = "Weather --"
    draw_text(label, w - 260, y + h // 2 - 8, size=2)
    return []


def draw_tabs(app):
    tabs = app.available_tabs()
    regions = []
    x, y, w, h = tabs_rect()
    fill_rect(x, y, w, h, WHITE)
    for i, tab in enumerate(tabs):
        rx, ry, rw, rh = tab_button_rect(i, len(tabs))
        active = tab == app.active_tab
        if active:
            fill_rect(rx, ry, rw, rh, BLACK)
            draw_text(TAB_LABELS[tab], rx + 12, ry + rh // 2 - 8, color=WHITE, size=2)
        else:
            draw_rect(rx, ry, rw, rh, BLACK)
            draw_text(TAB_LABELS[tab], rx + 12, ry + rh // 2 - 8, size=2)
        regions.append(((rx, ry, rw, rh), {"kind": "select_tab", "tab": tab}))
    return regions


def draw_body(app):
    if app.active_tab == TAB_AC:
        return draw_ac_list(app)
    devices = app.devices_for_tab(app.active_tab)
    return draw_device_grid(app, devices)


def draw_device_grid(app, devices):
    regions = []
    per_page = page_size()
    start = app.page * per_page
    page_devices = devices[start:start + per_page]
    for slot, device in enumerate(page_devices):
        rect = tile_rect(slot)
        regions += draw_device_tile(rect, device, app.is_busy(device["id"]))
    return regions


def draw_device_tile(rect, device, busy):
    x, y, w, h = rect
    draw_rect(x, y, w, h, BLACK)
    name = device.get("display_name") or device.get("name") or device["id"]
    draw_text(name, x + 8, y + 8, size=1)

    if busy:
        draw_text("...", x + 8, y + 28, size=2)
        return []

    component = device.get("component")
    regions = []

    if component == "cover":
        position = device.get("position")
        state_text = "%s%%" % position if isinstance(position, int) else str(device.get("state", "?"))
        draw_text(state_text, x + 8, y + 28, size=2)

        btn_w = w // 3
        btn_y = y + h - 28
        draw_text("Up", x + 4, btn_y, size=1)
        draw_text("Stop", x + btn_w + 4, btn_y, size=1)
        draw_text("Down", x + 2 * btn_w + 4, btn_y, size=1)
        device_id = device["id"]
        regions.append(((x, btn_y - 4, btn_w, 24), {"kind": "cover_cmd", "device_id": device_id, "command": "open"}))
        regions.append(((x + btn_w, btn_y - 4, btn_w, 24), {"kind": "cover_cmd", "device_id": device_id, "command": "stop"}))
        regions.append(((x + 2 * btn_w, btn_y - 4, btn_w, 24), {"kind": "cover_cmd", "device_id": device_id, "command": "close"}))
        regions.append(((x, y, w, h - 32), {"kind": "open_modal", "type": "position", "device_id": device_id}))

    elif component == "light":
        brightness = device.get("brightness")
        state_text = "%s%%" % brightness if isinstance(brightness, int) else str(device.get("state", "?"))
        draw_text(state_text, x + 8, y + 28, size=2)
        next_command = "off" if device.get("state") == "on" else "on"
        device_id = device["id"]
        pct_rect = (x + w - 50, y + h - 28, 46, 24)
        draw_text("%", pct_rect[0] + 14, pct_rect[1] + 2, size=1)
        regions.append((pct_rect, {"kind": "open_modal", "type": "brightness", "device_id": device_id}))
        body = (x, y, w - 50, h)
        regions.append((body, {"kind": "light_power", "device_id": device_id, "command": next_command}))

    else:  # switch/relay
        state_text = str(device.get("state", "?"))
        draw_text(state_text, x + 8, y + 28, size=2)
        regions.append(((x, y, w, h), {"kind": "switch_toggle", "device_id": device["id"]}))

    return regions


def draw_ac_list(app):
    devices = app.daikin_devices
    regions = []
    for i, device in enumerate(devices):
        rect = ac_row_rect(i, max(len(devices), 1))
        regions += draw_ac_row(rect, device, app.is_busy(device["id"]))
    return regions


def draw_ac_row(rect, device, busy):
    x, y, w, h = rect
    draw_rect(x, y, w, h, BLACK)
    name = device.get("display_name") or device.get("name") or device["id"]
    draw_text(name, x + 8, y + 6, size=1)

    if busy:
        draw_text("... (BLE call in progress, ~10s)", x + 8, y + h // 2 - 8, size=1)
        return []

    device_id = device["id"]
    power = device.get("power")
    power_label = "On" if power else "Off"
    next_state = "off" if power else "on"

    setpoint = device.get("setpoint")
    current = device.get("current_temp")
    temps = "%s / %s" % (current if current is not None else "--", setpoint if setpoint is not None else "--")
    mode_label = MODE_LABELS.get(device.get("mode"), "--")
    fan_label = FAN_LABELS.get(device.get("fan_speed"), "--")

    col_w = w // 4
    draw_text(power_label, x + 8, y + h - 28, size=2)
    draw_text(temps, x + col_w + 8, y + h - 28, size=1)
    draw_text(mode_label, x + 2 * col_w + 8, y + h - 28, size=1)
    draw_text(fan_label, x + 3 * col_w + 8, y + h - 28, size=1)
    draw_text("Refresh", x + w - 60, y + 6, size=1)

    return [
        ((x, y + h - 34, col_w, 34), {"kind": "ac_power", "device_id": device_id, "state": next_state}),
        ((x + col_w, y + h - 34, col_w, 34), {"kind": "open_modal", "type": "setpoint", "device_id": device_id}),
        ((x + 2 * col_w, y + h - 34, col_w, 34), {"kind": "open_modal", "type": "mode", "device_id": device_id}),
        ((x + 3 * col_w, y + h - 34, col_w, 34), {"kind": "open_modal", "type": "fan", "device_id": device_id}),
        ((x + w - 70, y, 70, 24), {"kind": "ac_live_refresh", "device_id": device_id}),
    ]


def draw_modal(app):
    modal = app.active_modal
    x, y, w, h = modal_rect()
    fill_rect(x, y, w, h, WHITE)
    draw_rect(x, y, w, h, BLACK)

    kind = modal["type"]
    if kind == "position" or kind == "brightness":
        choices = [0, 25, 50, 75, 100]
    elif kind == "setpoint":
        choices = [18, 20, 22, 24, 26]
    elif kind == "mode":
        choices = ["auto", "cool", "heat", "dry", "fan"]
    elif kind == "fan":
        choices = ["auto", "low", "mid", "high"]
    else:
        choices = []

    regions = []
    btn_h = 50
    for i, choice in enumerate(choices):
        by = y + 40 + i * (btn_h + 10)
        label = MODE_LABELS.get(choice, FAN_LABELS.get(choice, str(choice)))
        draw_rect(x + 20, by, w - 40, btn_h, BLACK)
        draw_text(label, x + 32, by + 16, size=2)
        regions.append(((x + 20, by, w - 40, btn_h), {"kind": "modal_choice", "value": choice}))

    close_y = y + h - 50
    draw_rect(x + 20, close_y, w - 40, 40, BLACK)
    draw_text("Close", x + 32, close_y + 10, size=2)
    regions.append(((x + 20, close_y, w - 40, 40), {"kind": "close_modal"}))
    return regions


def draw_footer(app):
    x, y, w, h = footer_rect()
    fill_rect(x, y, w, h, WHITE)
    status = "Online" if app.online else "Offline - showing last known state"
    draw_text(status, x + 8, y + 6, size=1)

    regions = []
    if app.active_tab in (TAB_LIGHTS, TAB_COVERS):
        devices = app.devices_for_tab(app.active_tab)
        per_page = page_size()
        if len(devices) > per_page:
            total_pages = (len(devices) + per_page - 1) // per_page
            draw_text("Page %s/%s" % (app.page + 1, total_pages), w // 2 - 40, y + 6, size=1)
            regions.append(((x + w - 140, y, 60, h), {"kind": "page", "delta": -1}))
            regions.append(((x + w - 70, y, 60, h), {"kind": "page", "delta": 1}))
    return regions


def _clock_text():
    t = time.localtime()
    return "%02d:%02d" % (t[3], t[4])


# ============================================================
# App logic + main loop
# ============================================================

app = None
last_shelly = 0
last_ac = 0
last_weather = 0
partial_redraws_since_full = 0


def redraw(full=False):
    global partial_redraws_since_full
    if not full and partial_redraws_since_full >= FULL_REFRESH_EVERY:
        full = True
    begin_frame(full=full)
    hw_clear()
    regions = []
    regions += draw_header(app)
    regions += draw_tabs(app)
    if app.active_modal:
        regions += draw_modal(app)
    else:
        regions += draw_body(app)
    regions += draw_footer(app)
    app.hit_regions = regions
    partial_redraws_since_full = 0 if full else partial_redraws_since_full + 1


def _with_busy(device_id, action_fn):
    app.set_busy(device_id, True)
    redraw()
    action_fn()
    app.set_busy(device_id, False)


def _apply_modal_choice(modal, value):
    device_id = modal["device_id"]
    kind = modal["type"]
    if kind == "position":
        shelly_position(device_id, value)
        app.refresh_shelly()
    elif kind == "brightness":
        shelly_light_level(device_id, value)
        app.refresh_shelly()
    elif kind == "setpoint":
        daikin_setpoint(device_id, value)
        app.refresh_daikin()
    elif kind == "mode":
        daikin_mode(device_id, value)
        app.refresh_daikin()
    elif kind == "fan":
        daikin_fan(device_id, value)
        app.refresh_daikin()


def handle_action(action):
    if action is None:
        return
    kind = action["kind"]

    if kind == "select_tab":
        app.active_tab = action["tab"]
        app.active_modal = None
        app.page = 0
        redraw()

    elif kind == "close_modal":
        app.active_modal = None
        redraw()

    elif kind == "open_modal":
        app.active_modal = {"type": action["type"], "device_id": action["device_id"]}
        redraw()

    elif kind == "page":
        app.page = max(0, app.page + action["delta"])
        redraw()

    elif kind == "switch_toggle":
        device_id = action["device_id"]

        def do():
            shelly_action(device_id, "toggle")
            app.refresh_shelly()

        _with_busy(device_id, do)
        redraw()

    elif kind == "light_power":
        device_id = action["device_id"]
        command = action["command"]

        def do():
            shelly_light_action(device_id, command)
            app.refresh_shelly()

        _with_busy(device_id, do)
        redraw()

    elif kind == "cover_cmd":
        device_id = action["device_id"]
        command = action["command"]

        def do():
            shelly_cover_action(device_id, command)
            app.refresh_shelly()

        _with_busy(device_id, do)
        redraw()

    elif kind == "ac_power":
        device_id = action["device_id"]
        target_state = action["state"]

        def do():
            daikin_power(device_id, target_state)
            app.refresh_daikin()

        _with_busy(device_id, do)
        redraw()

    elif kind == "ac_live_refresh":
        device_id = action["device_id"]

        def do():
            app.refresh_daikin(live=True)

        _with_busy(device_id, do)
        redraw()

    elif kind == "modal_choice":
        modal = app.active_modal
        value = action["value"]

        def do():
            _apply_modal_choice(modal, value)

        _with_busy(modal["device_id"], do)
        app.active_modal = None
        redraw()


def setup():
    global app, last_shelly, last_ac, last_weather

    hw_init()
    app = AppState()

    app.refresh_shelly()
    app.refresh_daikin()
    app.refresh_weather()
    app.ensure_active_tab()
    redraw(full=True)

    now = time.ticks_ms()
    last_shelly = now
    last_ac = now
    last_weather = now


def loop():
    global last_shelly, last_ac, last_weather

    touch = poll_touch()
    if touch:
        action = hit_test(touch[0], touch[1], app.hit_regions)
        handle_action(action)
        time.sleep_ms(200)  # debounce: ignore rapid repeat taps

    now = time.ticks_ms()

    if time.ticks_diff(now, last_shelly) >= SHELLY_POLL_MS:
        last_shelly = now
        if app.refresh_shelly() and not app.active_modal:
            redraw()

    if time.ticks_diff(now, last_ac) >= AC_POLL_MS:
        last_ac = now
        if app.refresh_daikin() and not app.active_modal:
            redraw()

    if time.ticks_diff(now, last_weather) >= WEATHER_POLL_MS:
        last_weather = now
        if app.refresh_weather():
            redraw()

    time.sleep_ms(TICK_MS)


try:
    setup()
    while True:
        loop()
except (Exception, KeyboardInterrupt) as e:
    try:
        from utility import print_error_msg

        print_error_msg(e)
    except ImportError:
        print("please update to latest firmware")
