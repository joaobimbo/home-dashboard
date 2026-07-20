# Entry point for the M5PaperS3 dashboard client - upload this alongside the other
# .py files in this folder to the device root, then "Run Always" (not just "Run
# Once") from UIFlow2 so it persists and auto-runs as main.py at boot. See
# README.md for the deployment steps and the on-device verification checklist.
#
# setup()/loop() + the try/except wrapper below match UIFlow2's standard project
# skeleton (what ships on a fresh device) so on-device errors still surface via
# utility.print_error_msg instead of silently dying.

import time

import api_client
import config
import hw
import layout
import state as state_mod
import ui

app = None
last_shelly = 0
last_ac = 0
last_weather = 0
partial_redraws_since_full = 0


def redraw(full=False):
    global partial_redraws_since_full
    if not full and partial_redraws_since_full >= config.FULL_REFRESH_EVERY:
        full = True
    hw.begin_frame(full=full)
    hw.clear()
    regions = []
    regions += ui.draw_header(app)
    regions += ui.draw_tabs(app)
    if app.active_modal:
        regions += ui.draw_modal(app)
    else:
        regions += ui.draw_body(app)
    regions += ui.draw_footer(app)
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
        api_client.shelly_position(device_id, value)
        app.refresh_shelly()
    elif kind == "brightness":
        api_client.shelly_light_level(device_id, value)
        app.refresh_shelly()
    elif kind == "setpoint":
        api_client.daikin_setpoint(device_id, value)
        app.refresh_daikin()
    elif kind == "mode":
        api_client.daikin_mode(device_id, value)
        app.refresh_daikin()
    elif kind == "fan":
        api_client.daikin_fan(device_id, value)
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
            api_client.shelly_action(device_id, "toggle")
            app.refresh_shelly()

        _with_busy(device_id, do)
        redraw()

    elif kind == "light_power":
        device_id = action["device_id"]
        command = action["command"]

        def do():
            api_client.shelly_light_action(device_id, command)
            app.refresh_shelly()

        _with_busy(device_id, do)
        redraw()

    elif kind == "cover_cmd":
        device_id = action["device_id"]
        command = action["command"]

        def do():
            api_client.shelly_cover_action(device_id, command)
            app.refresh_shelly()

        _with_busy(device_id, do)
        redraw()

    elif kind == "ac_power":
        device_id = action["device_id"]
        target_state = action["state"]

        def do():
            api_client.daikin_power(device_id, target_state)
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

    hw.init()
    app = state_mod.AppState()

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

    touch = hw.poll_touch()
    if touch:
        action = layout.hit_test(touch[0], touch[1], app.hit_regions)
        handle_action(action)
        time.sleep_ms(200)  # debounce: ignore rapid repeat taps

    now = time.ticks_ms()

    if time.ticks_diff(now, last_shelly) >= config.SHELLY_POLL_MS:
        last_shelly = now
        if app.refresh_shelly() and not app.active_modal:
            redraw()

    if time.ticks_diff(now, last_ac) >= config.AC_POLL_MS:
        last_ac = now
        if app.refresh_daikin() and not app.active_modal:
            redraw()

    if time.ticks_diff(now, last_weather) >= config.WEATHER_POLL_MS:
        last_weather = now
        if app.refresh_weather():
            redraw()

    time.sleep_ms(config.TICK_MS)


if __name__ == "__main__":
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
