# M5PaperS3 dashboard panel

A touch-control panel for the M5Stack PaperS3 (4.7" e-paper, capacitive touch,
ESP32-S3) that mirrors the web dashboard: weather, Spotify controls, and full
touch control of lights, blinds, and AC. One file, `hdashboard.py` — it only
calls the Flask API (`/api/shelly/*`, `/api/daikin/*`, `/api/spotify/*`,
`/api/weather`), never devices or Spotify directly.

## Quick start

1. Open `hdashboard.py`, find `SERVER_URL` near the top, and set it to your
   Flask server's LAN address (e.g. `http://192.168.1.50:5000` — same address
   `python app.py` prints on startup).
2. Open the UIFlow2 IDE, connect to the device, and upload `hdashboard.py`
   straight into the device's `apps` folder via the file manager (USB: click
   WebTerminal → File).
3. On the device, pick **hdashboard** from the app list (`APP.LIST`) to run it.

Individual apps on a UIFlow2 device are just single `.py` files sitting in
`apps/` — that's confirmed directly from M5Stack's own example
(`apps/helloworld.py`), not a guess. No packaging, no "Run Always" needed for
this — dropping the file in is enough, and it shows up in the launcher named
after the file.

If you'd rather it boot straight into the dashboard with no launcher/menu step
at all, paste it into the code editor instead and use **Run Always** — UIFlow2
writes whatever you deploy that way to `main.py`, which auto-runs at boot. Both
paths work; pick whichever fits how you want to use the device.

## Debugging over serial

Set `DEBUG = True` near the top of the file for an active debugging session:
connect over USB, open the UIFlow2 IDE's WebTerminal (or any serial monitor at
the device's baud rate), and re-run the app from the app list. You should see
lines like:

```
[hdashboard] hdashboard.py: starting
[hdashboard] setup(): calling hw_init()
[hdashboard] setup(): hw_init() done, WIDTH=960 HEIGHT=540
[hdashboard] setup(): fetching shelly devices from http://192.168.1.50:5000
[hdashboard] setup(): shelly online=True devices=7
...
[hdashboard] redraw(full=True) tab=ac modal=None
[hdashboard] redraw() done, 23 hit regions
```

If it crashes, the exception handler prints a full traceback
(`sys.print_exception(e)`) before attempting the on-screen error display —
so even if on-screen error rendering isn't working, the real cause (file,
line, exception type) is visible over serial.

**`DEBUG` defaults to `False` — leave it that way for normal use.** This isn't
just about log noise: `print()` over USB serial can block (or badly stall)
once its internal buffer fills up if nothing's actually reading the other
end, a known MicroPython/USB-CDC gotcha. With `DEBUG = True`, every
redraw/touch/network call prints — so disconnecting (or just closing the
serial monitor) partway through a session starves that buffer, and the whole
app slows to a crawl. This is exactly what "snappy for a minute, then slow
again" turned out to be — not an e-paper or network issue, just unread serial
output backing up. Only flip `DEBUG` on for an active session with a monitor
actually open, and back off when you unplug.

## Confirmed on real hardware so far

- **HTTP client is `requests2`, not `urequests`.** The first version of this
  app used `urequests`, which crashed immediately with
  `ImportError: no module named 'urequests'` — UIFlow2 renamed/replaced it
  platform-wide. Fixed; the API client section now uses `requests2.get/post`
  with a `json=` body instead of manually building one.
- **No client-side HTTP timeout.** `requests2`'s documented signature has no
  `timeout` parameter, so this app doesn't pass one (the whole `urequests`
  crash above was exactly this class of mistake — guessing at an unsupported
  kwarg — so it isn't worth repeating). In practice this is bounded by the
  Flask backend's own response times (fast for Shelly, ~25s worst case for
  Daikin), except a *fully unreachable* server, which could hang a request
  with no way for this app to detect or cancel it.
- **`Touch` is accessed as `M5.Touch.*`, not `from M5 import Touch`.** Only
  `Lcd`'s bare-import form is actually confirmed by a real M5Stack example;
  `Touch` was an unconfirmed extrapolation in an earlier version, and if wrong
  would have thrown an `ImportError` at the top of the file — before `setup()`
  even runs, before the try/except is reached — which looks exactly like a
  blank screen with no error. Reverted to the qualified, docs-confirmed form
  to close off that risk, whether or not it was the actual cause of a blank
  screen you saw.

## Fixed: ~5s to toggle a light (this was the real cause)

Confirmed on real hardware: without batching, each individual `fillRect`/
`drawRect`/`drawText` call was triggering its *own* separate e-paper panel
refresh. A single tile redraw makes something like 6-10 draw calls (tile
background, border, icon fill, icon border, 1-2 text lines, 1-2 buttons) - at
a few hundred ms per flash, that's the several seconds of lag reported, not a
one-off glitch.

Confirmed via the official UIFlow2 docs: `Lcd.startWrite()` / `Lcd.endWrite()`
batch everything drawn between them into one panel transaction. Every
`redraw*()` function now wraps its draw calls in `begin_batch()`/`end_batch()`
(thin wrappers around those two calls). If toggling still feels slow after
this, the panel itself may just be slow in `EPD_FASTEST` mode on this unit —
worth timing a redraw over serial (`DEBUG = True` already logs each
`redraw_tile()`/`redraw_ac_row()` call) to see whether it's the batching or
the hardware.

Also: the clock reads the device's RTC, which UIFlow2 normally syncs via NTP at
boot. If the clock shows a wrong/zero time, that's a device time-sync issue,
not something this app handles.

## Dimmer tiles: two explicit buttons, not one tile + a tiny corner

A dimmer ("light" component) tile used to make the *whole tile* an on/off
toggle, with only a small 50×26 corner carved out for brightness — easy to
miss, and conceptually one big region pretending to be two different actions.
Now it's two clearly bordered, roughly equal-width buttons side by side below
the name: **On/Off** on the left, **brightness%** (opens the preset picker) on
the right, plus the icon itself also toggles power. Plain switches/relays
(no brightness) still use the whole-tile-toggles pattern, since there's only
one action there.

Also bumped the gap between the device name and whatever's below it (state
text, or these buttons) from a cramped ~4px to a clearer ~12px across all
three tile types (cover/light/switch) — the name and the on/off indicator
were sitting close enough to read as one crowded line.

## State icons

Lights, switches, blinds, and the AC power button all show a square icon
instead of relying on small text alone. Two different, deliberately distinct
metaphors, not one:

- **Lights/switches/AC power**: `_draw_state_icon()`, a simple filled-or-not
  gauge. For lights/switches specifically, **white = on, black = off** (per
  request — this is the opposite of a typical "filled = active" convention,
  so don't "fix" it back). AC power keeps the more conventional filled=on.
- **Blinds**: `_draw_blind_icon()`, a different metaphor on purpose — black
  from the *top* down represents the fabric hanging over the window (the
  closed portion), white below is the open part letting light through. A
  60%-open blind shows ~40% black from the top, ~60% white below. This icon
  is also deliberately smaller (`COVER_ICON_SIZE`) than the lights/AC one
  (`TILE_ICON_SIZE`/`AC_ICON_SIZE`) — a blind is a thin strip, not a tank
  gauge.

Icon sizes are **fixed pixel constants, not derived from tile/row height**.
The first version sized them as `height - 20`, which looks fine in the
concrete example it was tested against but silently breaks in two ways once
you consider the actual range of real layouts: on a 4.7" panel at 960×540
(~235ppi) a size scaled to fill a *tall* row (e.g. an AC tab with only 1-2
units configured, giving each row 150-350px of height) produces a genuinely
huge square, and on the AC row specifically the icon and the device name were
both anchored to the same top-left corner, so a big enough icon there
literally drew over the name. Fixed sizes plus a strict "icon lives in its own
column, text lives in the other column" layout (rather than relying on the
icon happening to be small) closes off that whole class of bug regardless of
how many devices end up in a row.

## Text size

Bumped up across the board — this is a 4.7" panel at ~235ppi, so raw pixel
sizes that look reasonable on a desktop mockup (`size=1`, `size=2`) render
genuinely tiny in person. Rough scale now: `size=3` for the clock, tab labels,
and modal choice buttons (the most glanceable/tappable things); `size=2` for
everything else (names, state text, footer, small buttons). `_text_center_y()`
centers a line of text vertically within a given band, used anywhere text
needs to sit centered in a header/tab/button rather than at a fixed offset.

## Grid: 8 tiles per page

`GRID_COLS=2, GRID_ROWS=4` (was 3 rows / 6 tiles). Kept 2 columns rather than
going wider, since device names need the horizontal room; the row count is
what changed. This only works cleanly *because* icons are fixed-size now — a
shorter tile (~80px vs. the old ~110px) would have made a height-scaled icon
comically small, but a fixed 56px icon looks the same regardless.

## Snappier taps: optimistic UI

Toggling a light previously felt sluggish even though it's "just" a local HTTP
call — because the code waited for the full request/response round trip
*before* drawing anything, stacking network+backend time on top of the
e-paper redraw time. Fixed for the three simple, frequent interactions
(`switch_toggle`, `light_power`, `cover_cmd`): the tile is redrawn immediately
with the *guessed* new state (the on/off value being requested, or
opening/closing/stopped for covers), then the HTTP call fires, and the tile is
redrawn *again* only if the real response disagrees with the guess or the call
failed. In the common case there's exactly one redraw, and it happens before
the network call, not after. AC actions deliberately keep the old
wait-then-show-result behavior (with a visible "busy" state) instead of
guessing, since a real ~10s BLE round trip isn't something to fake instant
feedback for.

## Architecture: no background polling, every redraw is scoped

This got rewritten from an earlier version that polled Shelly/AC every 30s in
the background and did a full-screen redraw on every tap. Both were wrong for
an e-paper, battery-conscious device:

- **Nothing is polled in the background except weather** (every 15 min — one
  cheap call, already server-cached). Shelly/AC device state is fetched only
  when you switch tabs (which doubles as a manual "pull to refresh" — even
  re-tapping the already-active tab re-fetches it), and after your own actions
  it's patched directly from that action's own response — every Shelly/Daikin
  endpoint already returns the device's new state, so there's never a reason
  to re-fetch the whole list just to see the result of what you just did.
  **Exception**: a bounded retry-until-first-success safety net (every 5s,
  `INITIAL_SYNC_RETRY_MS`) for the *initial* boot fetch specifically. Without
  it, a failed first `refresh_shelly()` (e.g. Wi-Fi not fully up yet at boot)
  meant `available_tabs()` never showed Luzes/Estores at all — and since
  tapping one of those tabs is what would normally trigger a re-fetch, there
  was no tab button left to tap to ever recover. This isn't a return to
  background polling: `shelly_loaded`/`daikin_loaded` flip permanently true on
  first success and the retries stop for good.
- **Every redraw is scoped to the smallest region that actually changed**:
  `redraw_tile()` for a single Luzes/Estores tile, `redraw_ac_row()` for one
  AC row, `redraw_header_only()` for the clock/weather strip. Full-screen
  `redraw()` is reserved for moments where the whole screen legitimately
  changes anyway — initial boot, switching tabs, opening/closing a modal — not
  for routine taps.
- **The main loop's only frequent job is polling touch**, so a press feels
  immediate. Everything else (clock, weather) is "ambient": gated behind its
  own elapsed-time check inside the same loop (MicroPython here is
  single-threaded, no `uasyncio` — see below — so there isn't a second, truly
  independent loop; the separation is in what each check *does*, not in having
  two literal loops) so it does real, pixel-touching work only rarely. The
  clock is checked every 5s but only actually redrawn (scoped to the header)
  when the displayed minute changes — not every tick, and not full-screen.

**The scoped-redraw fix also fixed a real bug**, not just a performance
tweak: a scoped redraw only repaints one tile/row, so `app.hit_regions` (the
list `hit_test()` matches taps against) has to be patched to match — drop the
stale entries for that device, append the freshly drawn ones. The first version
of this rewrite forgot that step, which is exactly why AC stopped responding
after the first tap: the second tap was still being matched against the
pre-action hit region (e.g. a stale "turn on" region after the AC had already
turned on). `_replace_hit_regions()` fixes this and every scoped redraw goes
through it.

## Battery indicator + idle behaviour

Header now shows battery % (top-right), with a `+` suffix while charging -
`M5.Power.getBatteryLevel()` / `M5.Power.isCharging()`, confirmed via the
official UIFlow2 Power docs.

The panel **stays awake by default**. On this PaperS3/UIFlow2 setup, light
sleep can drop the Wi-Fi association; calling `M5.begin()` after wake to try to
recover it reinitializes the display and can leave it black. Keeping the radio
awake is therefore the reliable setting for a wall/mains-powered dashboard.
The idle loop uses a normal 1-second wait (`AWAKE_IDLE_MS`), preserving both
the server connection and responsive touch.

For battery experiments only, set `ENABLE_LIGHT_SLEEP = True` in
`hdashboard.py`. That uses `M5.Power.lightSleep(...)`, but only enable it if
your firmware demonstrably reconnects to Wi-Fi after every wake. The app never
calls `M5.begin()` after wake.

## Spotify controls

When Spotify is configured and authenticated in the Flask dashboard, the
Música tab shows the active track and output with **Anterior**, **Tocar/Pausa**
and **Seguinte** controls. **Escolher altifalante** fetches the current Spotify
Connect devices; selecting one transfers the active playback session without
starting a separate stream. A receiver only appears while Spotify reports it
as available, so Raspotify/librespot, Echo, or Google speakers may be absent
while offline.

With the default awake idle mode, `AWAKE_IDLE_MS` is **1 second**. This is a
small power trade-off for stable Wi-Fi. `TICK_MS` remains the 60-second
light-sleep duration if you explicitly enable that experimental battery mode.

## Clock timezone

`UTC_OFFSET_HOURS` (config section) is added to whatever the device's
NTP-synced RTC holds before formatting the clock — UIFlow2 syncs time at boot
but doesn't appear to apply a local offset on its own, so the clock shows raw
UTC unless corrected here. Defaults to `1`; adjust for your timezone/DST.

**Don't expect "a week" as a given** - that number came from the request, not
from a measured power budget. E-paper itself draws ~0 outside of a refresh
(bistable, holds the image with no power), but Wi-Fi + an ESP32-S3 CPU that's
awake all day, even briefly and even in light sleep between checks, adds up
in ways that are hard to predict without measuring current draw on the actual
unit. If a week turns out to be optimistic, the next lever (not implemented)
would be increasing `TICK_MS` and/or the various poll intervals further once
light-sleep wake-on-touch is confirmed - not deep sleep, given the risk above.

## Deliberate scope decisions

- **Single file**, organized in commented sections (config → hardware → Flask
  API client → app state → screen geometry/hit-testing → drawing → app
  logic/main loop) rather than a multi-file package.
- **Blocking HTTP calls, no `uasyncio`.** Matches this repo's general
  minimalism. AC commands take a real 7-10s BLE round trip; that row shows
  "..." *before* the call so you get instant feedback, and touch is naturally
  ignored while blocked (nothing polls it meanwhile — this is single-threaded).
- **Preset buttons instead of sliders** for position/brightness/setpoint/mode/
  fan — continuous drag doesn't work well against e-paper's slow refresh.
