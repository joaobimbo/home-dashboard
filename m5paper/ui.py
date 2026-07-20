# Drawing functions. Each draw_* function paints its region and returns the list of
# (rect, action) hit regions a tap in that area should trigger - main.py collects
# these into app.hit_regions each frame, and layout.hit_test() looks them up
# against touch input. Modals use preset buttons rather than sliders throughout
# (position/brightness/setpoint/mode/fan) since continuous drag feedback doesn't
# work well against e-paper's slow refresh.

import time

import hw
import layout

MODE_LABELS = {"auto": "Auto", "cool": "Frio", "heat": "Calor", "dry": "Seco", "fan": "Vent."}
FAN_LABELS = {"auto": "Auto", "low": "Low", "mid": "Mid", "high": "High"}


def draw_header(app):
    x, y, w, h = layout.header_rect()
    hw.fill_rect(x, y, w, h, hw.WHITE)
    hw.text(_clock_text(), x + 10, y + h // 2 - 8, size=2)

    if app.weather and app.weather.get("ok"):
        label = "%s C  %s" % (app.weather["temp_c"], app.weather["condition"])
    else:
        label = "Weather --"
    hw.text(label, w - 260, y + h // 2 - 8, size=2)
    return []


def draw_tabs(app):
    tabs = app.available_tabs()
    regions = []
    x, y, w, h = layout.tabs_rect()
    hw.fill_rect(x, y, w, h, hw.WHITE)
    for i, tab in enumerate(tabs):
        rx, ry, rw, rh = layout.tab_button_rect(i, len(tabs))
        active = tab == app.active_tab
        if active:
            hw.fill_rect(rx, ry, rw, rh, hw.BLACK)
            hw.text(layout.TAB_LABELS[tab], rx + 12, ry + rh // 2 - 8, color=hw.WHITE, size=2)
        else:
            hw.rect(rx, ry, rw, rh, hw.BLACK)
            hw.text(layout.TAB_LABELS[tab], rx + 12, ry + rh // 2 - 8, size=2)
        regions.append(((rx, ry, rw, rh), {"kind": "select_tab", "tab": tab}))
    return regions


def draw_body(app):
    if app.active_tab == layout.TAB_AC:
        return draw_ac_list(app)
    devices = app.devices_for_tab(app.active_tab)
    return draw_device_grid(app, devices)


def draw_device_grid(app, devices):
    regions = []
    per_page = layout.page_size()
    start = app.page * per_page
    page_devices = devices[start:start + per_page]
    for slot, device in enumerate(page_devices):
        rect = layout.tile_rect(slot)
        regions += draw_device_tile(rect, device, app.is_busy(device["id"]))
    return regions


def draw_device_tile(rect, device, busy):
    x, y, w, h = rect
    hw.rect(x, y, w, h, hw.BLACK)
    name = device.get("display_name") or device.get("name") or device["id"]
    hw.text(name, x + 8, y + 8, size=1)

    if busy:
        hw.text("...", x + 8, y + 28, size=2)
        return []

    component = device.get("component")
    regions = []

    if component == "cover":
        position = device.get("position")
        state_text = "%s%%" % position if isinstance(position, int) else str(device.get("state", "?"))
        hw.text(state_text, x + 8, y + 28, size=2)

        btn_w = w // 3
        btn_y = y + h - 28
        hw.text("Up", x + 4, btn_y, size=1)
        hw.text("Stop", x + btn_w + 4, btn_y, size=1)
        hw.text("Down", x + 2 * btn_w + 4, btn_y, size=1)
        device_id = device["id"]
        regions.append(((x, btn_y - 4, btn_w, 24), {"kind": "cover_cmd", "device_id": device_id, "command": "open"}))
        regions.append(((x + btn_w, btn_y - 4, btn_w, 24), {"kind": "cover_cmd", "device_id": device_id, "command": "stop"}))
        regions.append(((x + 2 * btn_w, btn_y - 4, btn_w, 24), {"kind": "cover_cmd", "device_id": device_id, "command": "close"}))
        regions.append(((x, y, w, h - 32), {"kind": "open_modal", "type": "position", "device_id": device_id}))

    elif component == "light":
        brightness = device.get("brightness")
        state_text = "%s%%" % brightness if isinstance(brightness, int) else str(device.get("state", "?"))
        hw.text(state_text, x + 8, y + 28, size=2)
        next_command = "off" if device.get("state") == "on" else "on"
        device_id = device["id"]
        pct_rect = (x + w - 50, y + h - 28, 46, 24)
        hw.text("%", pct_rect[0] + 14, pct_rect[1] + 2, size=1)
        regions.append((pct_rect, {"kind": "open_modal", "type": "brightness", "device_id": device_id}))
        body = (x, y, w - 50, h)
        regions.append((body, {"kind": "light_power", "device_id": device_id, "command": next_command}))

    else:  # switch/relay
        state_text = str(device.get("state", "?"))
        hw.text(state_text, x + 8, y + 28, size=2)
        regions.append(((x, y, w, h), {"kind": "switch_toggle", "device_id": device["id"]}))

    return regions


def draw_ac_list(app):
    devices = app.daikin_devices
    regions = []
    for i, device in enumerate(devices):
        rect = layout.ac_row_rect(i, max(len(devices), 1))
        regions += draw_ac_row(rect, device, app.is_busy(device["id"]))
    return regions


def draw_ac_row(rect, device, busy):
    x, y, w, h = rect
    hw.rect(x, y, w, h, hw.BLACK)
    name = device.get("display_name") or device.get("name") or device["id"]
    hw.text(name, x + 8, y + 6, size=1)

    if busy:
        hw.text("... (BLE call in progress, ~10s)", x + 8, y + h // 2 - 8, size=1)
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
    hw.text(power_label, x + 8, y + h - 28, size=2)
    hw.text(temps, x + col_w + 8, y + h - 28, size=1)
    hw.text(mode_label, x + 2 * col_w + 8, y + h - 28, size=1)
    hw.text(fan_label, x + 3 * col_w + 8, y + h - 28, size=1)
    hw.text("Refresh", x + w - 60, y + 6, size=1)

    return [
        ((x, y + h - 34, col_w, 34), {"kind": "ac_power", "device_id": device_id, "state": next_state}),
        ((x + col_w, y + h - 34, col_w, 34), {"kind": "open_modal", "type": "setpoint", "device_id": device_id}),
        ((x + 2 * col_w, y + h - 34, col_w, 34), {"kind": "open_modal", "type": "mode", "device_id": device_id}),
        ((x + 3 * col_w, y + h - 34, col_w, 34), {"kind": "open_modal", "type": "fan", "device_id": device_id}),
        ((x + w - 70, y, 70, 24), {"kind": "ac_live_refresh", "device_id": device_id}),
    ]


def draw_modal(app):
    modal = app.active_modal
    x, y, w, h = layout.modal_rect()
    hw.fill_rect(x, y, w, h, hw.WHITE)
    hw.rect(x, y, w, h, hw.BLACK)

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
        hw.rect(x + 20, by, w - 40, btn_h, hw.BLACK)
        hw.text(label, x + 32, by + 16, size=2)
        regions.append(((x + 20, by, w - 40, btn_h), {"kind": "modal_choice", "value": choice}))

    close_y = y + h - 50
    hw.rect(x + 20, close_y, w - 40, 40, hw.BLACK)
    hw.text("Close", x + 32, close_y + 10, size=2)
    regions.append(((x + 20, close_y, w - 40, 40), {"kind": "close_modal"}))
    return regions


def draw_footer(app):
    x, y, w, h = layout.footer_rect()
    hw.fill_rect(x, y, w, h, hw.WHITE)
    status = "Online" if app.online else "Offline - showing last known state"
    hw.text(status, x + 8, y + 6, size=1)

    regions = []
    if app.active_tab in (layout.TAB_LIGHTS, layout.TAB_COVERS):
        devices = app.devices_for_tab(app.active_tab)
        per_page = layout.page_size()
        if len(devices) > per_page:
            total_pages = (len(devices) + per_page - 1) // per_page
            hw.text("Page %s/%s" % (app.page + 1, total_pages), w // 2 - 40, y + 6, size=1)
            regions.append(((x + w - 140, y, 60, h), {"kind": "page", "delta": -1}))
            regions.append(((x + w - 70, y, 60, h), {"kind": "page", "delta": 1}))
    return regions


def _clock_text():
    t = time.localtime()
    return "%02d:%02d" % (t[3], t[4])
