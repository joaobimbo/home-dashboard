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

## State icons

Lights, switches, blinds, and the AC power button all show a big square gauge
instead of small text — filled black = fully on/open, empty/outline = fully
off/closed, and for blinds specifically it fills proportionally to how open
they are (a 60%-open blind shows a square that's 60% filled from the bottom
up). The AC power icon in particular spans nearly the full height of its row —
a small text button was easy to miss and hard to hit; this one isn't.

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
