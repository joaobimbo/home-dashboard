# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Scope

This is a local home dashboard: Flask backend + Jinja/vanilla-JS frontend for controlling Shelly devices (relays, covers, dimmers) and Daikin Madoka (BRC1H) AC units over Bluetooth. Keep the stack minimal:

- Python + Flask + Jinja + plain HTML/CSS + small vanilla JS.
- No Node/npm/frontend framework migration, no Docker, no DB by default.
- Spotify Connect playback is part of the dashboard. Do not add calendar, photos, or voice features unless explicitly requested.

## Commands

- Install deps: `pip install -r requirements.txt`
- Run server: `python app.py` (binds `0.0.0.0:5000`)
- Sanity check before commit (there is no configured test/lint pipeline — prefer this over inventing commands): `python -m py_compile app.py modules/shelly/controller.py modules/shelly/discover.py`
- Shelly discovery (manual/on-demand): `python modules/shelly/discover.py --network 192.168.1.0/24 --timeout 2.0`
- Daikin pairing (manual/on-demand, run on the Linux host with BT hardware): `python modules/daikin/pair.py`

## Architecture

`app.py` is the only Flask entrypoint and wires two independently-loaded controllers into routes:

- `ShellyController` (`modules/shelly/controller.py`) — HTTP/local-network calls to Shelly devices.
- `DaikinController` (`modules/daikin/controller.py`) — BLE calls to Madoka thermostats via `pymadoka`.
- `SpotifyController` (`modules/spotify/controller.py`) — server-side OAuth and Spotify Connect Web API calls; it remains optional when its environment variables are absent.

Both controllers follow the same `from_sources()` pattern, in priority order:
1. `modules/<name>/devices.json` (checked in, hand-edited/discovery-generated)
2. `<NAME>_DEVICES_JSON` env var (JSON string, same shape as the file)
3. hardcoded fallback — Shelly has one; Daikin does not (MAC addresses are household-specific, so an empty list is used instead)

The browser never talks to devices directly — it only calls Flask JSON endpoints (`/api/shelly/*`, `/api/daikin/*`, `/api/scenes*`), which the controllers then translate into device I/O. Keep new device features behind this same indirection.

Spotify playback uses `/api/spotify/*`; access/refresh tokens never reach the browser. The Música tab controls live playback and search only. Timed Spotify requests belong to the Telegram automation agent. Raspotify/librespot is an external system service for the server's analog output, not a Flask child process.

Scene endpoints (`/api/scenes*`) are backed by `modules/shelly/scenes.py::SceneStore` and remain live in the backend even though the current UI doesn't surface them.

`/api/weather` is unrelated to the device controllers: `modules/weather.py::get_weather()` does a server-side fetch of `wttr.in/?format=%t+%C`, parsed into `{ok, temp_c, condition}` and cached in-process for 30 minutes (falls back to the last good value on fetch failure). Kept server-side rather than a client-side fetch to avoid CORS and so multiple browser tabs share one cache instead of each hammering the external service.

### Shelly specifics

- Device records carry `component` (`relay`/`switch`/`cover`/`light`) + `relay` index — discovery emits one entry per channel; preserve these fields when hand-editing `devices.json`.
- Manual `display_name`/`image`/`other_names` edits in `devices.json` are expected to survive discovery re-runs (merge, not overwrite) unless `--no-merge` is passed.
- Status polling from the frontend is continuous (~30s) since it's plain HTTP.

### Daikin specifics

- Uses `pymadoka` over BLE (Linux-only, requires `bluetoothctl`). `bleak` is pinned `<1` in `requirements.txt` because `pymadoka` calls the old top-level `bleak.discover()` shim removed in `bleak` 1.0+ — don't let this pin drift without re-checking `pymadoka` still imports cleanly.
- Every `/api/daikin/*` request runs one full connect → command → disconnect BLE cycle — multi-second latency per request is expected, not a bug.
- Flask runs `threaded=True` (`app.py`) so a slow Daikin request doesn't block Shelly polling or other tabs' page loads. BLE access itself is still serialized behind `DaikinController._ble_lock` (one `threading.Lock` shared across all Daikin devices — the radio can only hold one connection at a time and pymadoka's discovery cache is a shared global), with a `ble_lock_timeout` (default 25s) that returns a "busy" error instead of blocking forever if something upstream hangs.
- pymadoka's own connect retry loop has no timeout/max-attempts, so a dead underlying D-Bus connection (BlueZ/`bluetoothd` hiccup, surfaces as `dbus_fast` `EOFError`/"could not shut down socket") makes it retry forever — which, held under `_ble_lock`, would permanently wedge every Daikin device. `_run()` wraps `madoka.start()`/`madoka.stop()` in `asyncio.wait_for(..., timeout=self._connect_timeout)` (default 20s) so this surfaces as a normal timeout instead. The background poller also wraps each device's poll in `try/except Exception: pass` since the daemon thread has no supervisor to restart it.
- pymadoka won't connect by MAC address alone — `Connection.start()` matches against its `DISCOVERED_DEVICES_CACHE`, populated by a scan. Since the MAC is already known from `devices.json`, `DaikinController._run()` does a targeted `bleak.BleakScanner.find_device_by_address()` lookup (returns as soon as seen, `quick_scan_timeout`, default 2s) instead of pymadoka's `discover_devices()` (always sleeps the full timeout scanning everything nearby), falling back to the full scan (`discover_timeout`, default 4s) only if the quick lookup finds nothing. It also pre-seeds `Controller.connection.client` with a `BleakClient` built from the found device, skipping a redundant first loop iteration + flat 2s sleep inside pymadoka's own connect loop (~2s saved per request; relies on a semi-internal pymadoka attribute, re-check on upgrade). That pre-seeded client uses a no-op `disconnected_callback` instead of pymadoka's real one, because the real one unconditionally reconnects on every disconnect (including our own deliberate one), racing against our own shutdown and surfacing as BlueZ `Operation already in progress`/`br-connection-canceled` errors.
- To isolate BLE/pymadoka slowness from Flask/web-layer slowness, use `python modules/daikin/debug_timing.py <device_id> [--http http://localhost:5000]` — it times each phase of the connect cycle directly and can diff it against the same call made over HTTP.
- BLE polling is decoupled from browser polling via a shared in-memory cache in `DaikinController` (`_status_cache`), kept fresh by one background thread (`start_background_polling()`, every `poll_interval`/120s regardless of tab count) plus every action's own result. `GET /api/daikin/<id>/status` reads that cache by default (fast, no BLE) and only does a live BLE round trip on cache-miss or `?live=1` (used by the manual refresh button). The frontend polls the cheap cached endpoint every 30s per tab (`startAcStatusPolling()` in `static/app.js`, matching Shelly's cadence) — since reads are cheap, more open tabs cost nothing extra, and all tabs converge within ~30s of any change instead of each tab drifting on its own independent clock.
- Exposed controls: power on/off, mode (`auto`/`cool`/`heat`/`dry`/`fan`), single setpoint temperature (applied to both cooling and heating setpoints), fan speed (`auto`/`low`/`mid`/`high`). Status payloads also include `current_temp` (actual indoor temperature, from pymadoka's `temperatures` feature) alongside `setpoint` — every status call funnels through `DaikinController._query_status_payload()`, so all 5 command methods stay in sync automatically.
- Pairing is interactive-only (`modules/daikin/pair.py`): walks `bluetoothctl` pairing, then appends `{id, display_name, room, address, adapter}` to `devices.json`.

## Frontend constraint: old iPad compatibility

`static/app.js` targets an old iPad used as a wall-mounted control panel. Keep it ES5-compatible: no `async/await`, no arrow functions, no modern-only APIs unless polyfilled. Prefer touch-safe interactions — old iPad Safari has inconsistent behavior with some slider/click patterns. Two specific traps already hit in practice: multi-argument `classList.add()`/`.remove()` isn't guaranteed on old WebKit (use the `removeClasses()` helper, one class per call — a multi-argument call as the first line of `paintAcCard` once silently broke all AC card state rendering there), and `document.hidden`/`visibilitychange` need the `isPageHidden()`/`visibilityChangeEventName` fallback for pre-iOS-7 Safari.
