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

The app logs its progress with `print()` — connect over USB, open the UIFlow2
IDE's WebTerminal (or any serial monitor at the device's baud rate), and
re-run the app from the app list. You should see lines like:

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

If it crashes, the exception handler now prints a full traceback
(`sys.print_exception(e)`) before attempting the on-screen error display —
so even if on-screen error rendering isn't working, the real cause (file,
line, exception type) is visible over serial. Set `DEBUG = False` near the top
of the file once things are working, to quiet the log.

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

## One thing still worth watching for

Whether draws batch into one atomic screen update, or each shape/text call
visibly flashes the panel individually during a redraw. Not a bug either way —
worst case is a slightly busier-looking refresh than necessary.

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
