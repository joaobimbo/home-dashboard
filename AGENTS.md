# AGENTS.md — Home Dashboard

## Scope (current project)

- Keep this repo focused on local dashboard + Shelly controls.
- Do not add Spotify/calendar/photos/voice features unless explicitly requested.
- Keep stack minimal: Python + Flask + Jinja + plain HTML/CSS + small vanilla JS (no Node/npm/framework migration, no Docker, no DB by default).

## Runtime and verification

- Install deps with `pip install -r requirements.txt`.
- Run server with `python app.py` (binds `0.0.0.0:5000`).
- Fast sanity check before commit: `python -m py_compile app.py modules/shelly/controller.py modules/shelly/discover.py`.
- There is no configured test/lint pipeline in repo; prefer focused smoke checks over invented commands.

## Real entrypoints

- Backend wiring is in `app.py`.
  - UI route: `/`
  - health: `/api/status`
  - Shelly APIs: `/api/shelly/*`
  - Daikin/Madoka APIs: `/api/daikin/*`
  - scenes APIs still exist in backend (`/api/scenes*`) even if UI is currently trimmed.
- Frontend entrypoints: `templates/index.html`, `static/app.js`, `static/style.css`.

## Shelly module conventions

- All Shelly logic is centralized in `modules/shelly/`.
- Browser must not call Shelly devices directly; always go through Flask endpoints.
- `ShellyController.from_sources()` load order:
  1) `modules/shelly/devices.json`
  2) `SHELLY_DEVICES_JSON`
  3) hardcoded fallback devices

## Daikin (Madoka BRC1H) module conventions

- All Daikin logic is centralized in `modules/daikin/`, using the `pymadoka` library (BLE, Linux-only — relies on `bluetoothctl`).
- `bleak` is pinned to `<1` in `requirements.txt`: `pymadoka` calls the old top-level `bleak.discover()` shim, which was removed in `bleak` 1.0+. Do not let this pin drift without checking pymadoka still imports cleanly.
- Browser must not talk BLE directly; always go through Flask `/api/daikin/*` endpoints, which run one connect/command/disconnect cycle per request (several seconds of latency is expected and normal).
- `app.py` runs Flask with `threaded=True` so a slow Daikin request from one browser tab doesn't block Shelly polling, page loads, or other tabs. BLE access itself still can't run concurrently (single radio link per device, plus pymadoka's discovery cache is a shared module-level global), so `DaikinController` serializes it with `self._ble_lock` (a `threading.Lock`, one lock shared across all Daikin devices) inside `_run()`. A request that can't acquire the lock within `ble_lock_timeout` (default 25s) returns a "busy" error instead of hanging forever.
- pymadoka's `Connection.start()` retry loop has no timeout or max attempts. If the underlying D-Bus connection to BlueZ dies mid-operation (observed as `dbus_fast` `EOFError` / "could not shut down socket" — the D-Bus reader task noticing a broken socket and tearing down the whole bus connection on its own, independent of our code), pymadoka just keeps retrying `.connect()` against that same dead connection forever. Since this all runs under `self._ble_lock`, an unbounded hang there would permanently lock out every Daikin device (not just the one that failed) until the process is restarted — worse than before background polling existed, since one bad BLE hiccup during any poll cycle could wedge the whole subsystem with nobody touching anything. Fixed by wrapping `madoka.start()`/`madoka.stop()` in `asyncio.wait_for(..., timeout=self._connect_timeout)` (default 20s) inside `_run()`, so a dead connection surfaces as a normal timeout error (releasing the lock) instead of hanging forever. The background poller loop (`start_background_polling()`) also wraps each device's `get_status()` call in its own `try/except Exception: pass` as defense-in-depth, since an unsupervised daemon thread has nothing to restart it if an unexpected exception escapes.
- Before connecting, pymadoka needs the target device to be in its `DISCOVERED_DEVICES_CACHE` (populated by a BLE scan) — it won't connect by address alone. Since we already know the MAC from `devices.json`, `DaikinController._run()` uses `bleak.BleakScanner.find_device_by_address()` (returns as soon as the device is seen, timeout `quick_scan_timeout`, default 2s) instead of pymadoka's `discover_devices()` (which always sleeps the full timeout scanning everything nearby). Only falls back to the slow full scan (`discover_timeout`, default 4s) if the quick lookup finds nothing.
- `_run()` also pre-seeds `Controller.connection.client` with a `BleakClient` built from that already-found device before calling `madoka.start()`. This skips pymadoka's own connect loop's redundant first iteration (which just wraps the device with no radio I/O) and the flat 2s `asyncio.sleep()` that follows every iteration regardless of outcome — worth ~2s per request. This relies on a semi-internal pymadoka attribute (`Connection.client`); re-check `connection.py`'s connect loop if `pymadoka` is upgraded.
- That pre-seeded `BleakClient` is given a no-op `disconnected_callback`, not pymadoka's real `Connection.on_disconnect`. pymadoka's own callback unconditionally schedules a reconnect (`asyncio.create_task(self.start())`) on *every* disconnect, including our own deliberate one at the end of each request — that reconnect attempt races against our shutdown and shows up as BlueZ `Operation already in progress` / `br-connection-canceled` errors. We own the connect/disconnect lifecycle per request, so auto-reconnect is never wanted here.
- To debug whether AC slowness is BLE/pymadoka vs. the Flask/web layer, use `python modules/daikin/debug_timing.py <device_id> [--http http://localhost:5000]` — it times each phase of the connect cycle directly, and can compare against the same call made over HTTP.
- `DaikinController.from_sources()` load order:
  1) `modules/daikin/devices.json`
  2) `DAIKIN_DEVICES_JSON`
  3) empty list (no hardcoded fallback — MAC addresses are household-specific)
- Pairing is manual/on-demand only: `python modules/daikin/pair.py` (run on the Linux host with Bluetooth hardware). It walks through `bluetoothctl` pairing interactively, then appends the device (id/display_name/room/address/adapter) to `devices.json`.
- BLE polling and browser polling are decoupled through a shared server-side cache, so opening more tabs never adds BLE traffic. `DaikinController` (`modules/daikin/controller.py`) keeps a `_status_cache` dict (device_id -> last known status), updated by a single background thread (`start_background_polling()`, started once in `app.py` after constructing the controller) that queries each device every `poll_interval` (default 120s) regardless of how many tabs are open, plus every action's own result (all actions funnel through `_run()`, which writes to the cache on every successful call). `GET /api/daikin/<id>/status` serves that cache by default (near-instant, no BLE) and only does a live BLE read on cache-miss (e.g. right after startup) or when called with `?live=1`. The frontend polls this cheap endpoint every 30s per tab (`startAcStatusPolling()` in `static/app.js`, matching Shelly's cadence, skipped while the tab is hidden) — since it's just a cache read, all tabs converge within ~30s of any change instead of drifting for up to 120s. The manual refresh button (`data-ac-refresh`) explicitly passes `?live=1` to force a real BLE read, since a user pressing "refresh" wants ground truth, not a cached value.
- Exposed controls: power on/off, mode (`auto`/`cool`/`heat`/`dry`/`fan`), single setpoint temperature (applied to both cooling and heating set points), fan speed (`auto`/`low`/`mid`/`high`).

## Discovery workflow (important)

- Discovery is manual/on-demand only: `python modules/shelly/discover.py`.
- Default scan: `192.168.1.0/24`, timeout `1.5s`, workers `64`.
- Override network/timeout when needed, e.g. `python modules/shelly/discover.py --network 192.168.1.0/24 --timeout 2.0`.
- Output defaults to `modules/shelly/devices.json` and merges manual fields unless `--no-merge`.
- Discovery now emits per-channel entries with `component` + `relay` (e.g. covers, switches, dimmers); preserve these fields when editing JSON.
- Manual display names/images are expected to be edited in `devices.json` and should survive discovery merges.

## Old iPad compatibility

- Keep JS ES5-compatible in `static/app.js` (no `async/await`, no arrow functions, no modern-only APIs unless polyfilled).
- Prefer touch-safe interactions and simple controls; old iPad Safari has inconsistent behavior with some slider/click patterns.
- `classList.add()`/`.remove()` must be called with **one class name at a time** — multi-argument calls aren't guaranteed on old WebKit's `DOMTokenList`. Use the `removeClasses(el, names)` helper instead of `el.classList.remove(a, b, c)`. A multi-argument `classList.remove()` as the first line of `paintAcCard` previously broke AC card state rendering entirely on an old iPad (the call threw before any state update ran).
- `document.hidden`/`visibilitychange` aren't available (unprefixed) on pre-iOS-7 Safari. Use the `isPageHidden()` helper and the pre-computed `visibilityChangeEventName` instead of referencing `document.hidden`/`"visibilitychange"` directly.
