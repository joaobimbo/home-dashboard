# M5PaperS3 dashboard panel

A touch-control panel for the M5Stack PaperS3 (4.7" e-paper, capacitive touch,
ESP32-S3) that mirrors the web dashboard: weather, and full touch control of
lights, blinds, and AC. Written for UIFlow2 (MicroPython). It's a pure client of
the existing Flask API (`/api/shelly/*`, `/api/daikin/*`, `/api/weather`) — no
backend changes, nothing here talks to devices directly.

## Files

| File | Role |
|---|---|
| `config.py` | Edit this: server URL, poll intervals, timeouts. |
| `hw.py` | The only file touching M5Unified/UIFlow2 APIs directly (display + touch). **Not yet verified on real hardware — see below.** |
| `api_client.py` | HTTP calls to the Flask backend, one function per endpoint. |
| `state.py` | In-memory device state + change detection (skip repainting on unchanged polls). |
| `layout.py` | Screen geometry (rects) and touch hit-testing — pure math, no hardware calls. |
| `ui.py` | Drawing functions; each returns the tap regions it just drew. |
| `main.py` | Entry point / main loop — upload and run this. |

## Before deploying: edit `config.py`

Set `SERVER_URL` to the Flask server's LAN address, e.g. `http://192.168.1.50:5000`
(same address `python app.py` prints on startup, per the main repo's README).

## Deploying (OTA via UIFlow2 IDE)

1. Make sure the PaperS3 is already running UIFlow2 firmware and joined to the
   home Wi-Fi (per the project's own setup — not handled by this code).
2. Open the UIFlow2 IDE (uiflow2.m5stack.com or the desktop app) and connect to
   the device over the network.
3. Upload **all** `.py` files in this folder to the device's root filesystem —
   `main.py` imports the others as sibling modules, so it's not enough to upload
   `main.py` alone.
4. Use **Download** (burns to flash, persists across reboots and auto-runs as
   `main.py` at boot), not just **Run** (RAM-only, lost on reboot), once you're
   past initial testing.

**Fallback:** if the UIFlow2 IDE's OTA flow doesn't handle multi-file uploads
well, the firmware is standard MicroPython underneath — `mpremote connect <port>
fs cp *.py :` over USB works too.

## Known risk: `hw.py` is unverified

Everything here was written against the *documented* Flask API (confirmed exact
endpoint shapes) and general UIFlow2/M5Unified MicroPython conventions, but I
could not test against the real PaperS3 firmware. `hw.py` isolates every
hardware-specific call so that if a method name is wrong (e.g. `M5.Display.*`,
`M5.Touch.*` signatures), only that one file needs fixing — nothing else in the
app touches `M5.*` directly.

Specific things likely to need adjusting on first run:
- **Screen resolution** — `hw.py` reads it from `M5.Display.width()/height()` at
  `init()`, so `layout.py`'s hardcoded 960×540 defaults get overwritten
  automatically; just confirm the resulting layout looks right.
- **E-paper refresh modes** — `hw.refresh()` currently always calls
  `M5.Display.display()`. If the firmware exposes distinct fast/partial vs.
  full/flash refresh calls (it likely does, e-paper panels usually do), wire
  `refresh(full=...)` to use them — this is what actually saves the visible
  flicker/lag, on top of the software-level "skip redraw if nothing changed"
  logic already in `state.py`.
- **Touch API** — `poll_touch()` assumes `M5.Touch.getCount()` /
  `M5.Touch.getDetail(0)` with `.x`/`.y`/`.isPressed()`/`.wasPressed()`. Confirm
  against a simple crosshair test.
- **`urequests` timeout support** — `api_client.py` passes `timeout=` to
  `urequests.get/post`. If this UIFlow2 firmware's bundled `urequests` doesn't
  accept that kwarg, every call will fail immediately with a clear `TypeError`
  message shown as "Offline" — easy to spot, but worth checking early (step 3
  below) rather than after building the rest of the UI.
- **Clock** (`ui._clock_text()`) reads `time.localtime()`, assuming UIFlow2's
  normal boot-time NTP sync already set the RTC. If the panel shows a wrong/zero
  time, the device isn't syncing time — not something this app itself handles.

## Suggested build/verification order

1. **`hw.py` smoke test**: `hw.init()`, draw some text, `hw.clear()`,
   `hw.refresh()`. Fix any wrong method names here first.
2. **Touch test**: `hw.poll_touch()` against an on-screen crosshair — confirm
   coordinates and orientation match what's drawn.
3. **`api_client.py` test**: call `get_weather()` and `get_shelly_configured()`
   against the real Flask server, print the results to the screen. Confirms
   networking + `urequests` timeout behavior before any UI is built on top.
4. **Build up the screens incrementally**: header → tabs → Luzes/Estores grids →
   AC rows → modals. Test real taps against one real device (e.g. a single
   Shelly light) end-to-end before trusting the rest.
5. **Full-loop validation**: trigger a real AC command and confirm the "busy"
   state blocks input for the ~10s BLE round trip; confirm unchanged poll ticks
   don't cause a visible refresh; stop the Flask server and confirm the panel
   shows stale data + "Offline" instead of crashing.

## Deliberate scope decisions

- **No per-tile partial redraw / dirty-rects.** `state.py`'s change detection is
  coarse: a poll either changed *something* (full repaint of the frame buffer,
  cheap — it's just software drawing) or changed nothing (skip the panel refresh
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
