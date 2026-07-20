# M5PaperS3 dashboard panel

A touch-control panel for the M5Stack PaperS3 (4.7" e-paper, capacitive touch,
ESP32-S3) that mirrors the web dashboard: weather, and full touch control of
lights, blinds, and AC. Written for UIFlow2 (MicroPython) as a single
self-contained file (`main.py`), matching how UIFlow2's on-device app storage
(`/flash/apps`) expects an app. It's a pure client of the existing Flask API
(`/api/shelly/*`, `/api/daikin/*`, `/api/weather`) — no backend changes, nothing
here talks to devices directly.

`main.py` is organized top-to-bottom in clearly commented sections: config →
hardware (M5Unified/UIFlow2 calls) → Flask API client → app state/change
detection → screen geometry/hit-testing → drawing → app logic/main loop.

## Before deploying: edit the config section

Near the top of `main.py`, set `SERVER_URL` to the Flask server's LAN address,
e.g. `http://192.168.1.50:5000` (same address `python app.py` prints on
startup, per the main repo's README). Poll intervals and timeouts are right
below it if you want to tune those too.

## Deploying via the UIFlow2 IDE

1. Make sure the PaperS3 is already running UIFlow2 firmware and joined to the
   home Wi-Fi (per the project's own setup — not handled by this code).
2. Open the UIFlow2 IDE (uiflow2.m5stack.com or the desktop app) and connect to
   the device (USB, or Wi-Fi using the access code shown on the device's startup
   screen).
3. Paste/upload `main.py` as your project's code.
4. Use **Run Always** (persists to flash, auto-runs at boot), not just
   **Run Once** (RAM-only, lost on reboot), once you're past initial testing.
   UIFlow2 also stores it under `/flash/apps` as part of this — that's handled
   by the IDE itself, no separate step needed on your end.

**Fallback:** the firmware is standard MicroPython underneath, so `mpremote
connect <port> fs cp main.py :` over USB works too if the IDE's upload flow is
ever awkward.

## Two things still worth confirming on real hardware

Everything hardware-facing (display object name, drawing methods, e-paper
refresh-mode API, touch API — see the "Hardware" section near the top of
`main.py`) was verified against the official UIFlow2 MicroPython docs
(uiflow-micropython.readthedocs.io) — not guessed. Two things weren't
confirmable from docs alone:

- **Whether draws batch into one atomic panel update, or each `fillRect`/
  `drawString` call visibly flashes the panel individually** during a redraw.
  Not blocking either way — worst case is a slightly busier-looking redraw.
  If it's an issue, look for a `startWrite()`/`endWrite()`-style batching call.
- **`urequests` timeout support** — the API client section passes `timeout=` to
  `urequests.get/post`. If this firmware's bundled `urequests` doesn't accept
  that kwarg, every call will fail immediately with a clear `TypeError` message
  shown as "Offline" — easy to spot, worth checking early (step 2 below) rather
  than after building the rest of the UI.

Also: the clock (`_clock_text()`) reads `time.localtime()`, assuming UIFlow2's
normal boot-time NTP sync already set the RTC. If the panel shows a wrong/zero
time, the device isn't syncing time — not something this app itself handles.

## Suggested verification order

1. **Hardware smoke test**: `hw_init()`, draw some text/rects, confirm
   `begin_frame(full=True)` vs `begin_frame(full=False)` visibly change
   refresh quality/speed.
2. **Touch test**: `poll_touch()` against an on-screen crosshair — confirm
   coordinates and orientation match what's drawn.
3. **API client test**: call `get_weather()` and `get_shelly_configured()`
   against the real Flask server, print the results to the screen. Confirms
   networking + `urequests` timeout behavior before trusting the rest of the UI.
4. **Full-loop validation**: tap through header → tabs → Luzes/Estores grids →
   AC rows → modals against real devices (start with one Shelly light);
   trigger a real AC command and confirm the "busy" state blocks input for the
   ~10s BLE round trip; confirm unchanged poll ticks don't cause a visible
   refresh; stop the Flask server and confirm the panel shows stale data +
   "Offline" instead of crashing.

## Deliberate scope decisions

- **Single file.** Everything lives in `main.py`, organized in commented
  sections, to match UIFlow2's app model (one app = one uploadable unit) rather
  than a multi-file package.
- **No per-tile partial redraw / dirty-rects.** Change detection is coarse: a
  poll either changed *something* (full repaint of the frame buffer, cheap —
  it's just software drawing) or changed nothing (skip the panel refresh
  entirely, which is the actually expensive/flickery part on e-paper). This
  avoids a fragile per-tile dirty-rect system that would be hard to get right
  without hardware in hand to test against.
- **Blocking HTTP calls, no `uasyncio`.** Matches the rest of this repo's
  minimalism. AC commands (7–10s BLE round trip) block the main loop; the UI
  draws a "busy" state on that tile *before* making the call so the user gets
  immediate feedback, and touch is naturally ignored while blocked since nothing
  polls it meanwhile.
- **Preset buttons instead of sliders** for cover position, brightness, AC
  setpoint, mode, and fan — matches the web dashboard's options but avoids
  continuous-drag interaction, which doesn't work well against e-paper's slow
  refresh.
