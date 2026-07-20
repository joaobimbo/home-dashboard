# M5PaperS3 dashboard panel

A touch-control panel for the M5Stack PaperS3 (4.7" e-paper, capacitive touch,
ESP32-S3) that mirrors the web dashboard: weather, and full touch control of
lights, blinds, and AC. One file, `hdashboard.py` — no backend changes, nothing
here talks to devices directly, it only calls the same Flask API
(`/api/shelly/*`, `/api/daikin/*`, `/api/weather`) the web dashboard uses.

## Quick start

1. Open `hdashboard.py`, find `SERVER_URL` near the top, and set it to your
   Flask server's LAN address (e.g. `http://192.168.1.50:5000` — same address
   `python app.py` prints on startup).
2. Open the UIFlow2 IDE, connect to the device, paste in the contents of
   `hdashboard.py`.
3. Click **Run Always**.

That's it — the device will boot straight into the dashboard from now on.

(UIFlow2 always runs whatever you deploy this way as `main.py` on the device,
regardless of what the file was called before you pasted it in — that's a
UIFlow2/MicroPython platform convention, not something this app controls. The
file is named `hdashboard.py` here in the repo purely so it's recognizable
next to everything else in this project.)

## Two things worth confirming the first time you run it

Everything hardware-facing (display calls, e-paper refresh-mode API, touch API
— see the "Hardware" section near the top of the file) was checked against the
official UIFlow2 MicroPython docs, not guessed. Two things weren't confirmable
from docs alone, so watch for these on first run:

- **`urequests` timeout support.** The API client section passes `timeout=` to
  `urequests.get/post`. If this firmware's bundled `urequests` doesn't accept
  that kwarg, every call fails immediately and the panel just shows "Offline"
  — easy to spot, and would mean every screen looks empty/stale from the start.
- **Whether draws batch into one atomic screen update, or each shape/text call
  visibly flashes individually** during a redraw. Not a bug either way — worst
  case is a slightly busier-looking refresh.

Also: the clock reads the device's RTC, which UIFlow2 normally syncs via NTP at
boot. If the clock shows a wrong/zero time, that's a device time-sync issue,
not something this app handles.

## Deliberate scope decisions

- **Single file**, organized in commented sections (config → hardware → Flask
  API client → app state/change detection → screen geometry/hit-testing →
  drawing → main loop) rather than a multi-file package.
- **No per-tile partial redraw / dirty-rects.** A poll either changed
  *something* (repaint everything — cheap, it's just software drawing) or
  changed nothing (skip the panel refresh entirely, which is the actually
  expensive/flickery part on e-paper).
- **Blocking HTTP calls, no `uasyncio`.** AC commands take a real 7-10s BLE
  round trip; the tile shows "..." *before* the call so you get instant
  feedback, and touch is naturally ignored while blocked.
- **Preset buttons instead of sliders** for position/brightness/setpoint/mode/
  fan — continuous drag doesn't work well against e-paper's slow refresh.
