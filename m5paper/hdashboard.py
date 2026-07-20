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

import sys
import time

import M5
import requests2
from M5 import Lcd

# NOTE: only Lcd is imported this way - that's confirmed directly from
# M5Stack's own apps/helloworld.py example. `M5.Touch` (qualified, not
# `from M5 import Touch`) is used below instead, since that's the form
# actually confirmed by the official docs - importing a name from M5 that
# isn't really exported that way would throw here, before setup() even
# starts, which would look exactly like a blank screen with no on-screen
# error (see DEBUG below for why: this line runs before the try/except).

# Default False: print() over USB serial can block (or badly stall) once its
# internal buffer fills up if nothing's actually reading the other end - a
# known MicroPython/USB-CDC gotcha. With DEBUG on, every redraw/touch/network
# call prints, so unplugging (or just closing the serial monitor) part way
# through a session starves the buffer and the whole app slows to a crawl -
# not an e-paper or network issue, just unread serial output backing up. Only
# flip this to True for an active debugging session with a serial monitor
# open, and back to False afterwards.
DEBUG = False


def log(msg):
    if DEBUG:
        print("[hdashboard] " + msg)


# ============================================================
# Configuration - edit these before uploading
# ============================================================

# LAN address of the Flask dashboard server, e.g. "http://192.168.1.50:5000"
# (find it from what `python app.py` prints on startup, or `hostname -I` on the host).
SERVER_URL = "http://192.168.1.50:5000"

# Weather polling cadence, in milliseconds - the only thing polled on a timer.
# Shelly/AC device state is deliberately NOT polled in the background: e-paper
# refreshes are visible and somewhat costly, and this is a battery-conscious
# device, not a screen meant to be constantly repainting. Device state is
# fetched only on tab switch (which doubles as a manual "pull to refresh" -
# even re-tapping the already-active tab re-fetches it) and patched directly
# from each action's own response (every Shelly/Daikin action endpoint already
# returns the device's new state - no need to re-fetch the whole list after
# your own action).
WEATHER_POLL_MS = 900000

# Force a full (flash) e-paper refresh every N partial refreshes, to clear ghosting.
FULL_REFRESH_EVERY = 20

# Main loop tick, in milliseconds - how often touch is polled and timers are checked.
TICK_MS = 100


# ============================================================
# Hardware - the only section touching M5Unified/UIFlow2 APIs directly.
#
# `from M5 import Lcd` + Lcd.setCursor()/.print() for text match a real
# M5Stack-authored example (apps/helloworld.py), not just doc summaries.
# Lcd.setEpdMode() controls e-paper refresh quality/speed - there's no separate
# flush/push call, draws update the panel directly under whichever mode is
# currently set. Touch is M5.Touch.getCount() + M5.Touch.getDetail(0) (an
# 11-element TUPLE, not an object - index 5 is wasPressed) plus separate
# M5.Touch.getX()/getY() calls for coordinates (confirmed via the official
# UIFlow2 MicroPython docs, uiflow-micropython.readthedocs.io - kept
# M5.-qualified rather than `from M5 import Touch` since only Lcd's bare-import
# form is actually confirmed by a real example).
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


def begin_batch():
    """Wraps a group of draw calls into one panel transaction (confirmed via
    the official UIFlow2 docs: Lcd.startWrite()/endWrite()). Without this,
    each individual fillRect/drawRect/drawText call may trigger its own
    separate e-paper refresh - a single tile redraw makes ~6-10 draw calls, so
    that reads as multiple seconds of lag for what should be one instant
    update. Every redraw_*() function wraps its draw calls in
    begin_batch()/end_batch() for exactly this reason."""
    Lcd.startWrite()


def end_batch():
    Lcd.endWrite()


def poll_touch():
    """Return (x, y) of a new touch press (down-edge only), or None."""
    M5.update()
    if M5.Touch.getCount() > 0:
        detail = M5.Touch.getDetail(0)
        was_pressed = detail[5]  # wasPressed
        if was_pressed:
            return M5.Touch.getX(), M5.Touch.getY()
    return None


# ============================================================
# Flask API client - thin requests2 wrapper (requests2 is UIFlow2's own HTTP
# client; it replaced urequests platform-wide, confirmed on-device - urequests
# doesn't exist on this firmware at all).
#
# Mirrors skills/shelly.md, skills/daikin.md and skills/weather.md. Every
# function returns whatever the backend returned, parsed from JSON. Network-level
# failures (no route, connection refused) are caught here and turned into the
# same {"ok": False, "error": ...} shape the backend itself uses for failures,
# so callers never need to special-case "the server said no" vs. "we couldn't
# reach the server".
#
# No client-side timeout: requests2's documented signature doesn't have a
# timeout parameter, and guessing at an unsupported kwarg is exactly the kind
# of mistake that broke urequests in the first place. In practice this is
# bounded by the Flask backend's own response times (fast for Shelly, ~25s
# worst case for Daikin thanks to its ble_lock_timeout) - the only real gap is
# a fully unreachable server (not erroring, just gone), which could hang a
# request with no way for this app to detect or cancel it.
#
# Two endpoints (get_shelly_configured, get_daikin_devices) return a bare JSON
# array on success rather than a dict - on a network failure they still return
# the {"ok": False, ...} dict shape, so callers must check
# `isinstance(result, dict) and result.get("ok") is False` before assuming a list.
# ============================================================


def _get(path):
    try:
        resp = requests2.get(SERVER_URL + path)
    except Exception as exc:
        log("GET %s FAILED: %s" % (path, exc))
        return {"ok": False, "error": str(exc)}
    try:
        data = resp.json()
    finally:
        resp.close()
    return data


def _post(path, body):
    try:
        resp = requests2.post(SERVER_URL + path, json=body, headers={"Content-Type": "application/json"})
    except Exception as exc:
        log("POST %s FAILED: %s" % (path, exc))
        return {"ok": False, "error": str(exc)}
    try:
        data = resp.json()
    finally:
        resp.close()
    return data


def get_shelly_configured():
    return _get("/api/shelly/configured")


def get_shelly_devices():
    return _get("/api/shelly/devices")


def shelly_action(device_id, action):
    return _post("/api/shelly/%s/action" % device_id, {"action": action})


def shelly_cover_action(device_id, command):
    return _post("/api/shelly/%s/cover_action" % device_id, {"command": command})


def shelly_position(device_id, position):
    return _post("/api/shelly/%s/position" % device_id, {"position": position})


def shelly_light_action(device_id, command):
    return _post("/api/shelly/%s/light_action" % device_id, {"command": command})


def shelly_light_level(device_id, brightness):
    return _post("/api/shelly/%s/light_level" % device_id, {"brightness": brightness})


def get_daikin_devices():
    return _get("/api/daikin/devices")


def get_daikin_status(device_id, live=False):
    path = "/api/daikin/%s/status" % device_id
    if live:
        path += "?live=1"
    return _get(path)


def daikin_power(device_id, state):
    return _post("/api/daikin/%s/power" % device_id, {"state": state})


def daikin_mode(device_id, mode):
    return _post("/api/daikin/%s/mode" % device_id, {"mode": mode})


def daikin_setpoint(device_id, temperature):
    return _post("/api/daikin/%s/setpoint" % device_id, {"temperature": temperature})


def daikin_fan(device_id, speed):
    return _post("/api/daikin/%s/fan" % device_id, {"speed": speed})


def get_weather():
    return _get("/api/weather")


# ============================================================
# Shared tab identifiers
# ============================================================

TAB_AC = "ac"
TAB_LIGHTS = "lights"
TAB_COVERS = "covers"


# ============================================================
# App state.
#
# Deliberately no background-polling change detection here: device state is
# refreshed only on tab switch (a full re-fetch of that tab's devices) and
# patched directly from each action's own response afterwards - see
# patch_shelly_device()/patch_daikin_device() below. Every Shelly/Daikin action
# endpoint already returns the device's new state in its response, so there's
# never a need to re-fetch the whole list just to see the result of your own
# action.
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
        # Set True the first time each refresh succeeds. Used only to retry a
        # failed *initial* sync (see loop()) - if the very first refresh_shelly()
        # at boot fails (e.g. Wi-Fi not fully up yet), available_tabs() would
        # never show Luzes/Estores, and since those tabs' buttons are what
        # would normally trigger a re-fetch, there'd be no way to ever recover
        # without this. Once True, no further retries happen - this is a
        # boot-recovery safety net, not a return to background polling.
        self.shelly_loaded = False
        self.daikin_loaded = False

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

    # --- refresh (tab-switch-triggered, never on a timer) -------------------

    def refresh_shelly(self):
        configured = get_shelly_configured()
        if isinstance(configured, dict) and configured.get("ok") is False:
            self.online = False
            return
        live = get_shelly_devices()
        if isinstance(live, dict) and live.get("ok") is False:
            self.online = False
            return

        live_by_id = dict((d["id"], d) for d in live)
        merged = []
        for cfg in configured:
            row = dict(cfg)
            row.update(live_by_id.get(cfg["id"], {}))
            merged.append(row)

        self.shelly_devices = merged
        self.online = True
        self.shelly_loaded = True

    def refresh_daikin(self, live=False):
        configured = get_daikin_devices()
        if isinstance(configured, dict) and configured.get("ok") is False:
            self.online = False
            return

        merged = []
        for cfg in configured:
            status = get_daikin_status(cfg["id"], live=live)
            row = dict(cfg)
            if status.get("ok"):
                row.update(status)
            merged.append(row)

        self.daikin_devices = merged
        self.online = True
        self.daikin_loaded = True

    def refresh_weather(self):
        result = get_weather()
        if result.get("ok"):
            self.weather = result
            return True
        return False

    # --- lookup (used for optimistic UI updates - see handle_action) --------

    def get_shelly_device(self, device_id):
        for d in self.shelly_devices:
            if d["id"] == device_id:
                return d
        return None

    # --- patch a single device from its own action's response ---------------

    def patch_shelly_device(self, response):
        if not response.get("ok"):
            log("shelly action failed: %s" % response.get("error"))
            return
        for d in self.shelly_devices:
            if d["id"] == response.get("id"):
                d.update(response)
                return

    def patch_daikin_device(self, response):
        if not response.get("ok"):
            log("daikin action failed: %s" % response.get("error"))
            return
        for d in self.daikin_devices:
            if d["id"] == response.get("id"):
                d.update(response)
                return

    # --- busy tracking (mirrors static/app.js's is-busy class) --------------

    def set_busy(self, device_id, busy):
        if busy:
            self.busy_ids.add(device_id)
        else:
            self.busy_ids.discard(device_id)

    def is_busy(self, device_id):
        return device_id in self.busy_ids


# ============================================================
# Screen geometry and touch hit-testing. No hardware calls here - pure math.
# ============================================================

TAB_LABELS = {TAB_AC: "AC", TAB_LIGHTS: "Luzes", TAB_COVERS: "Estores"}

HEADER_H = 70
TABS_H = 60
FOOTER_H = 30

GRID_COLS = 2
GRID_ROWS = 4  # 8 tiles/page - kept 2 columns (not narrower) so device names have room
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

# Icon sizes are fixed constants, NOT derived from tile/row height - a 4.7"
# panel at 960x540 is ~235ppi, so a "square that fills the tile" scales into
# something huge on tall rows (e.g. only 1-2 AC devices configured) and starts
# overlapping the text drawn at fixed offsets from the top. Fixed sizes keep
# icons proportionate regardless of how many devices are on screen.
TILE_ICON_SIZE = 56
AC_ICON_SIZE = 72
COVER_ICON_SIZE = 40  # smaller than TILE_ICON_SIZE - a blind is a thin strip, not a big tank gauge


def _text_center_y(y, h, size):
    """Vertically center a line of `size`-scaled text (~8px tall per size
    unit) within a region of height h starting at y."""
    return y + h // 2 - 4 * size


def draw_header(app):
    x, y, w, h = header_rect()
    fill_rect(x, y, w, h, WHITE)
    draw_text(_clock_text(), x + 10, _text_center_y(y, h, 3), size=3)

    if app.weather and app.weather.get("ok"):
        label = "%s C  %s" % (app.weather["temp_c"], app.weather["condition"])
    else:
        label = "Weather --"
    draw_text(label, w - 340, _text_center_y(y, h, 2), size=2)
    return []


def draw_tabs(app):
    tabs = app.available_tabs()
    regions = []
    x, y, w, h = tabs_rect()
    fill_rect(x, y, w, h, WHITE)
    for i, tab in enumerate(tabs):
        rx, ry, rw, rh = tab_button_rect(i, len(tabs))
        active = tab == app.active_tab
        label_y = _text_center_y(ry, rh, 3)
        if active:
            fill_rect(rx, ry, rw, rh, BLACK)
            draw_text(TAB_LABELS[tab], rx + 16, label_y, color=WHITE, size=3)
        else:
            draw_rect(rx, ry, rw, rh, BLACK)
            draw_text(TAB_LABELS[tab], rx + 16, label_y, size=3)
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


def _draw_state_icon(icon_x, icon_y, icon_size, fill_fraction):
    """A square gauge: fills black from the bottom up by fill_fraction (0-1).
    fill_fraction=1 draws a fully filled (black) square, 0 a fully empty
    (white/outline-only) one - used for on/off state (lights, switches, AC
    power)."""
    fill_h = int(icon_size * fill_fraction)
    fill_rect(icon_x, icon_y, icon_size, icon_size, WHITE)
    if fill_h > 0:
        fill_rect(icon_x, icon_y + icon_size - fill_h, icon_size, fill_h, BLACK)
    draw_rect(icon_x, icon_y, icon_size, icon_size, BLACK)


def _draw_blind_icon(icon_x, icon_y, icon_size, position_pct):
    """A blind gauge - a different metaphor from _draw_state_icon on purpose:
    black from the TOP down represents the fabric hanging over the window
    (the closed portion), white below is the open part letting light through.
    position_pct is 0 (closed) - 100 (open)."""
    closed_h = int(icon_size * (100 - position_pct) / 100)
    fill_rect(icon_x, icon_y, icon_size, icon_size, WHITE)
    if closed_h > 0:
        fill_rect(icon_x, icon_y, icon_size, closed_h, BLACK)
    draw_rect(icon_x, icon_y, icon_size, icon_size, BLACK)


def draw_device_tile(rect, device, busy):
    x, y, w, h = rect
    fill_rect(x, y, w, h, WHITE)
    draw_rect(x, y, w, h, BLACK)
    name = device.get("display_name") or device.get("name") or device["id"]
    draw_text(name, x + 8, y + 6, size=2)

    if busy:
        draw_text("...", x + 8, y + 26, size=2)
        return []

    component = device.get("component")
    regions = []
    device_id = device["id"]

    # Icon on the right, name/state text on the left - a fixed icon size and a
    # strict left/right column split (rather than sizing the icon off tile
    # height) is what keeps the two from ever overlapping.

    if component == "cover":
        icon_size = COVER_ICON_SIZE
        icon_x = x + w - icon_size - 10
        icon_y = y + (h - icon_size) // 2

        position = device.get("position")
        if isinstance(position, int):
            pct = position
            state_text = "%s%%" % position
        else:
            state = device.get("state")
            pct = 100 if state == "open" else 0 if state == "closed" else 50
            state_text = str(state or "?")
        draw_text(state_text, x + 8, y + 32, size=2)
        _draw_blind_icon(icon_x, icon_y, icon_size, pct)

        btn_w = (icon_x - x) // 3
        btn_y = y + h - 30
        draw_text("Up", x + 4, btn_y, size=2)
        draw_text("Stop", x + btn_w + 4, btn_y, size=2)
        draw_text("Down", x + 2 * btn_w + 4, btn_y, size=2)
        regions.append(((x, btn_y - 4, btn_w, 28), {"kind": "cover_cmd", "device_id": device_id, "command": "open"}))
        regions.append(((x + btn_w, btn_y - 4, btn_w, 28), {"kind": "cover_cmd", "device_id": device_id, "command": "stop"}))
        regions.append(((x + 2 * btn_w, btn_y - 4, btn_w, 28), {"kind": "cover_cmd", "device_id": device_id, "command": "close"}))
        regions.append(((x, y, icon_x - x, btn_y - 4 - y), {"kind": "open_modal", "type": "position", "device_id": device_id}))
        regions.append(((icon_x, icon_y, icon_size, icon_size), {"kind": "open_modal", "type": "position", "device_id": device_id}))

    elif component == "light":
        icon_size = TILE_ICON_SIZE
        icon_x = x + w - icon_size - 10
        icon_y = y + (h - icon_size) // 2

        is_on = device.get("state") == "on"
        brightness = device.get("brightness")
        _draw_state_icon(icon_x, icon_y, icon_size, 0 if is_on else 1)  # white=on, black=off, per user preference

        # Two explicit side-by-side buttons - on/off and brightness% - rather
        # than the whole tile toggling power with only a tiny corner for
        # brightness. btn_top leaves a clear gap below the name instead of
        # sitting right under it.
        btn_top = y + 34
        btn_h = max(24, (y + h - 8) - btn_top)
        col_w = (icon_x - 8 - x) // 2

        onoff_label = "On" if is_on else "Off"
        pct_label = "%s%%" % brightness if isinstance(brightness, int) else "--"

        draw_rect(x + 4, btn_top, col_w - 4, btn_h, BLACK)
        draw_text(onoff_label, x + 12, _text_center_y(btn_top, btn_h, 2), size=2)

        draw_rect(x + col_w + 4, btn_top, col_w - 4, btn_h, BLACK)
        draw_text(pct_label, x + col_w + 12, _text_center_y(btn_top, btn_h, 2), size=2)

        next_command = "off" if is_on else "on"
        regions.append(((x, btn_top, col_w, btn_h), {"kind": "light_power", "device_id": device_id, "command": next_command}))
        regions.append(((x + col_w, btn_top, col_w, btn_h), {"kind": "open_modal", "type": "brightness", "device_id": device_id}))
        regions.append(((icon_x, icon_y, icon_size, icon_size), {"kind": "light_power", "device_id": device_id, "command": next_command}))

    else:  # switch/relay
        icon_size = TILE_ICON_SIZE
        icon_x = x + w - icon_size - 10
        icon_y = y + (h - icon_size) // 2

        is_on = device.get("state") == "on"
        state_text = "On" if is_on else "Off"
        draw_text(state_text, x + 8, y + 32, size=2)
        _draw_state_icon(icon_x, icon_y, icon_size, 0 if is_on else 1)  # white=on, black=off, per user preference
        regions.append(((x, y, w, h), {"kind": "switch_toggle", "device_id": device_id}))

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
    fill_rect(x, y, w, h, WHITE)
    draw_rect(x, y, w, h, BLACK)
    device_id = device["id"]

    # Icon is fixed-size (clamped to the row's actual height, since AC row
    # height varies a lot with device count - as few as 1, or all 4) and on
    # the left; all text (including the name) lives in the info column to its
    # right - the name used to be drawn at (x+8), directly on top of where
    # this same-side icon renders, which is the actual "square covering the
    # text" bug for AC rows specifically.
    icon_size = min(AC_ICON_SIZE, h - 10)
    icon_x = x + 10
    icon_y = y + max(0, (h - icon_size) // 2)
    info_x = icon_x + icon_size + 14

    name = device.get("display_name") or device.get("name") or device["id"]
    draw_text(name, info_x, y + 6, size=2)
    draw_text("Sync", x + w - 60, y + 6, size=2)

    if busy:
        draw_text("... (~10s)", info_x, y + 30, size=2)
        return [((x + w - 70, y, 70, 24), {"kind": "ac_live_refresh", "device_id": device_id})]

    power = device.get("power")
    is_on = bool(power)
    next_state = "off" if is_on else "on"
    _draw_state_icon(icon_x, icon_y, icon_size, 1 if is_on else 0)

    setpoint = device.get("setpoint")
    current = device.get("current_temp")
    mode_label = MODE_LABELS.get(device.get("mode"), "--")
    fan_label = FAN_LABELS.get(device.get("fan_speed"), "--")
    # One combined line, not three stacked ones - AC rows can be as short as
    # ~80px when all 4 units are configured, not enough room for separate
    # temps/mode/fan lines without them colliding with the button row below.
    info_line = "%s/%s  %s  Fan %s" % (
        current if current is not None else "--",
        setpoint if setpoint is not None else "--",
        mode_label,
        fan_label,
    )
    draw_text(info_line, info_x, y + 30, size=2)

    btn_w = (x + w - info_x) // 3
    btn_h = 26
    btn_y = y + h - btn_h - 4
    draw_text("Set", info_x + 8, btn_y + 4, size=2)
    draw_text("Mode", info_x + btn_w + 8, btn_y + 4, size=2)
    draw_text("Fan", info_x + 2 * btn_w + 8, btn_y + 4, size=2)

    return [
        ((icon_x, icon_y, icon_size, icon_size), {"kind": "ac_power", "device_id": device_id, "state": next_state}),
        ((info_x, btn_y, btn_w, btn_h), {"kind": "open_modal", "type": "setpoint", "device_id": device_id}),
        ((info_x + btn_w, btn_y, btn_w, btn_h), {"kind": "open_modal", "type": "mode", "device_id": device_id}),
        ((info_x + 2 * btn_w, btn_y, btn_w, btn_h), {"kind": "open_modal", "type": "fan", "device_id": device_id}),
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
        draw_text(label, x + 32, _text_center_y(by, btn_h, 3), size=3)
        regions.append(((x + 20, by, w - 40, btn_h), {"kind": "modal_choice", "value": choice}))

    close_y = y + h - 50
    draw_rect(x + 20, close_y, w - 40, 40, BLACK)
    draw_text("Close", x + 32, _text_center_y(close_y, 40, 3), size=3)
    regions.append(((x + 20, close_y, w - 40, 40), {"kind": "close_modal"}))
    return regions


def draw_footer(app):
    x, y, w, h = footer_rect()
    fill_rect(x, y, w, h, WHITE)
    status = "Online" if app.online else "Offline - showing last known state"
    draw_text(status, x + 8, _text_center_y(y, h, 2), size=2)

    regions = []
    if app.active_tab in (TAB_LIGHTS, TAB_COVERS):
        devices = app.devices_for_tab(app.active_tab)
        per_page = page_size()
        if len(devices) > per_page:
            total_pages = (len(devices) + per_page - 1) // per_page
            draw_text("Page %s/%s" % (app.page + 1, total_pages), w // 2 - 50, _text_center_y(y, h, 2), size=2)
            regions.append(((x + w - 140, y, 60, h), {"kind": "page", "delta": -1}))
            regions.append(((x + w - 70, y, 60, h), {"kind": "page", "delta": 1}))
    return regions


def _clock_text():
    t = time.localtime()
    return "%02d:%02d" % (t[3], t[4])


# ============================================================
# App logic + main loop.
#
# The loop's only frequent job is polling touch, so a press feels immediate -
# that's the "primary loop". Everything else (clock, weather) is "ambient":
# gated behind its own elapsed-time check so it does real work only rarely,
# and every redraw it causes is scoped to just the region that actually needs
# repainting (see redraw_tile/redraw_ac_row/redraw_header_only below) rather
# than a full-screen repaint. There's deliberately no polling of Shelly/AC
# device state at all - see the AppState comment above.
# ============================================================

app = None
last_weather = 0
last_clock_check = 0
last_displayed_minute = None
last_shelly_retry = 0
last_daikin_retry = 0
partial_redraws_since_full = 0

CLOCK_CHECK_MS = 5000  # how often we glance at the clock, not how often it redraws
INITIAL_SYNC_RETRY_MS = 5000  # boot-recovery only - see loop()


def _due_for_full_refresh():
    return partial_redraws_since_full >= FULL_REFRESH_EVERY


def redraw(full=False):
    """Full-screen redraw - reserved for moments where the whole screen
    legitimately changes anyway: initial boot, switching tabs, opening/closing
    a modal. Everything else uses a scoped redraw_*() below."""
    global partial_redraws_since_full
    if not full and _due_for_full_refresh():
        full = True
    log("redraw(full=%s) tab=%s modal=%s" % (full, app.active_tab, app.active_modal))
    begin_frame(full=full)
    begin_batch()
    hw_clear()
    regions = []
    regions += draw_header(app)
    regions += draw_tabs(app)
    if app.active_modal:
        regions += draw_modal(app)
    else:
        regions += draw_body(app)
    regions += draw_footer(app)
    end_batch()
    app.hit_regions = regions
    log("redraw() done, %d hit regions" % len(regions))
    partial_redraws_since_full = 0 if full else partial_redraws_since_full + 1


def _replace_hit_regions(device_id, new_regions):
    """Scoped redraws only repaint one tile/row, so app.hit_regions must be
    patched to match - drop any existing regions for this device_id (they may
    now be stale, e.g. an on/off button's next-command flipped) and append the
    freshly drawn ones. Skipping this was the actual bug behind "AC stops
    responding after the first tap": the second tap was still being matched
    against the pre-action hit region."""
    app.hit_regions = [(r, a) for (r, a) in app.hit_regions if a.get("device_id") != device_id] + new_regions


def redraw_tile(device_id):
    """Scoped redraw for one Luzes/Estores tile - used after every tap so a
    light/switch/cover toggle feels instant instead of waiting on a full
    screen repaint."""
    global partial_redraws_since_full
    if _due_for_full_refresh():
        redraw(full=True)
        return
    devices = app.devices_for_tab(app.active_tab)
    per_page = page_size()
    page_devices = devices[app.page * per_page:app.page * per_page + per_page]
    for slot, device in enumerate(page_devices):
        if device["id"] == device_id:
            log("redraw_tile(%s) slot=%s" % (device_id, slot))
            begin_frame(full=False)
            begin_batch()
            new_regions = draw_device_tile(tile_rect(slot), device, app.is_busy(device_id))
            end_batch()
            _replace_hit_regions(device_id, new_regions)
            partial_redraws_since_full += 1
            return
    redraw()  # device isn't on the currently visible page - fall back to a full redraw


def redraw_ac_row(device_id):
    """Scoped redraw for one AC row."""
    global partial_redraws_since_full
    if _due_for_full_refresh():
        redraw(full=True)
        return
    devices = app.daikin_devices
    for slot, device in enumerate(devices):
        if device["id"] == device_id:
            log("redraw_ac_row(%s) slot=%s" % (device_id, slot))
            begin_frame(full=False)
            begin_batch()
            new_regions = draw_ac_row(ac_row_rect(slot, max(len(devices), 1)), device, app.is_busy(device_id))
            end_batch()
            _replace_hit_regions(device_id, new_regions)
            partial_redraws_since_full += 1
            return
    redraw()


def redraw_header_only():
    """Scoped redraw for the clock/weather header - has no hit regions, so no
    hit_regions patching needed."""
    global partial_redraws_since_full
    if _due_for_full_refresh():
        redraw(full=True)
        return
    log("redraw_header_only()")
    begin_frame(full=False)
    begin_batch()
    draw_header(app)
    end_batch()
    partial_redraws_since_full += 1


def _with_busy_row(device_id, action_fn):
    """AC actions are real ~10s BLE round trips, so unlike lights/covers they
    get a visible busy state - scoped to just that row."""
    app.set_busy(device_id, True)
    redraw_ac_row(device_id)
    action_fn()
    app.set_busy(device_id, False)
    redraw_ac_row(device_id)


def _apply_modal_choice(modal, value):
    device_id = modal["device_id"]
    kind = modal["type"]
    if kind == "position":
        app.patch_shelly_device(shelly_position(device_id, value))
    elif kind == "brightness":
        app.patch_shelly_device(shelly_light_level(device_id, value))
    elif kind == "setpoint":
        app.patch_daikin_device(daikin_setpoint(device_id, value))
    elif kind == "mode":
        app.patch_daikin_device(daikin_mode(device_id, value))
    elif kind == "fan":
        app.patch_daikin_device(daikin_fan(device_id, value))


def handle_action(action):
    if action is None:
        return
    kind = action["kind"]

    if kind == "select_tab":
        app.active_tab = action["tab"]
        app.active_modal = None
        app.page = 0
        # Tab switch is the one moment we do fetch fresh device state - acts
        # as a manual "pull to refresh" too, since re-tapping the already
        # active tab still re-fetches it.
        if app.active_tab == TAB_AC:
            app.refresh_daikin()
        else:
            app.refresh_shelly()
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
        # Optimistic UI: draw the guessed new state immediately, before the
        # HTTP round trip, so the tap feels instant - then only redraw again
        # if the real response disagrees (or failed). Waiting for the
        # network response before drawing anything was the actual cause of
        # "not snappy": the visible delay was network+backend time stacked
        # on top of the e-paper redraw, instead of just the redraw.
        device_id = action["device_id"]
        device = app.get_shelly_device(device_id)
        guess = None
        if device:
            guess = "off" if device.get("state") == "on" else "on"
            device["state"] = guess
            redraw_tile(device_id)
        response = shelly_action(device_id, "toggle")
        app.patch_shelly_device(response)
        if not (response.get("ok") and response.get("state") == guess):
            redraw_tile(device_id)

    elif kind == "light_power":
        device_id = action["device_id"]
        command = action["command"]
        device = app.get_shelly_device(device_id)
        if device:
            device["state"] = command  # optimistic - see switch_toggle above
            redraw_tile(device_id)
        response = shelly_light_action(device_id, command)
        app.patch_shelly_device(response)
        if not (response.get("ok") and response.get("state") == command):
            redraw_tile(device_id)

    elif kind == "cover_cmd":
        device_id = action["device_id"]
        command = action["command"]
        guess = {"open": "opening", "close": "closing", "stop": "stopped"}.get(command)
        device = app.get_shelly_device(device_id)
        if device and guess:
            device["state"] = guess  # optimistic - see switch_toggle above
            redraw_tile(device_id)
        response = shelly_cover_action(device_id, command)
        app.patch_shelly_device(response)
        if not (response.get("ok") and response.get("state") == guess):
            redraw_tile(device_id)

    elif kind == "ac_power":
        device_id = action["device_id"]
        target_state = action["state"]

        def do():
            app.patch_daikin_device(daikin_power(device_id, target_state))

        _with_busy_row(device_id, do)

    elif kind == "ac_live_refresh":
        device_id = action["device_id"]

        def do():
            app.patch_daikin_device(get_daikin_status(device_id, live=True))

        _with_busy_row(device_id, do)

    elif kind == "modal_choice":
        modal = app.active_modal
        _apply_modal_choice(modal, action["value"])
        app.active_modal = None
        redraw()


def setup():
    global app, last_weather, last_clock_check, last_displayed_minute
    global last_shelly_retry, last_daikin_retry

    log("setup(): calling hw_init()")
    hw_init()
    log("setup(): hw_init() done, WIDTH=%s HEIGHT=%s" % (WIDTH, HEIGHT))
    app = AppState()

    log("setup(): fetching shelly devices from %s" % SERVER_URL)
    app.refresh_shelly()
    log("setup(): shelly online=%s devices=%d" % (app.online, len(app.shelly_devices)))

    log("setup(): fetching daikin devices")
    app.refresh_daikin()
    log("setup(): daikin online=%s devices=%d" % (app.online, len(app.daikin_devices)))

    log("setup(): fetching weather")
    app.refresh_weather()
    log("setup(): weather=%s" % (app.weather,))

    app.ensure_active_tab()
    log("setup(): active_tab=%s available_tabs=%s" % (app.active_tab, app.available_tabs()))
    redraw(full=True)
    log("setup(): done")

    now = time.ticks_ms()
    last_weather = now
    last_clock_check = now
    last_displayed_minute = time.localtime()[4]
    last_shelly_retry = now
    last_daikin_retry = now


def loop():
    global last_weather, last_clock_check, last_displayed_minute
    global last_shelly_retry, last_daikin_retry

    # Primary loop: touch. Checked every tick so a press feels immediate.
    touch = poll_touch()
    if touch:
        log("loop(): touch at %s" % (touch,))
        action = hit_test(touch[0], touch[1], app.hit_regions)
        log("loop(): action=%s" % (action,))
        handle_action(action)
        time.sleep_ms(200)  # debounce: ignore rapid repeat taps
        return  # prioritize the next touch poll over ambient checks below

    # Ambient: clock/weather. Gated behind their own elapsed-time checks so
    # they do real work (and touch a pixel) only rarely - not a device poll,
    # just a local clock/cache glance.
    now = time.ticks_ms()

    if time.ticks_diff(now, last_clock_check) >= CLOCK_CHECK_MS:
        last_clock_check = now
        current_minute = time.localtime()[4]
        if current_minute != last_displayed_minute:
            last_displayed_minute = current_minute
            redraw_header_only()

    if time.ticks_diff(now, last_weather) >= WEATHER_POLL_MS:
        last_weather = now
        if app.refresh_weather():
            redraw_header_only()

    # Boot-recovery retry: if the *initial* sync at setup() failed (e.g.
    # Wi-Fi wasn't fully up yet), keep retrying every INITIAL_SYNC_RETRY_MS
    # until it succeeds once - without this, a failed first fetch would mean
    # available_tabs() never shows Luzes/Estores, and since tapping one of
    # those tabs is what would normally trigger a re-fetch, there'd be no way
    # to ever recover. Stops permanently once loaded - not background polling.
    if not app.shelly_loaded and time.ticks_diff(now, last_shelly_retry) >= INITIAL_SYNC_RETRY_MS:
        last_shelly_retry = now
        log("loop(): retrying initial shelly sync")
        app.refresh_shelly()
        if app.shelly_loaded and not app.active_modal:
            app.ensure_active_tab()
            redraw(full=True)

    if not app.daikin_loaded and time.ticks_diff(now, last_daikin_retry) >= INITIAL_SYNC_RETRY_MS:
        last_daikin_retry = now
        log("loop(): retrying initial daikin sync")
        app.refresh_daikin()
        if app.daikin_loaded and not app.active_modal:
            app.ensure_active_tab()
            redraw(full=True)

    time.sleep_ms(TICK_MS)


log("hdashboard.py: starting")
try:
    setup()
    while True:
        loop()
except (Exception, KeyboardInterrupt) as e:
    print("[hdashboard] CRASHED - full traceback follows:")
    sys.print_exception(e)
    try:
        from utility import print_error_msg

        print_error_msg(e)
    except ImportError:
        print("[hdashboard] no utility.print_error_msg available on this firmware")
