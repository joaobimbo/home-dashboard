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
- `DaikinController.from_sources()` load order:
  1) `modules/daikin/devices.json`
  2) `DAIKIN_DEVICES_JSON`
  3) empty list (no hardcoded fallback — MAC addresses are household-specific)
- Pairing is manual/on-demand only: `python modules/daikin/pair.py` (run on the Linux host with Bluetooth hardware). It walks through `bluetoothctl` pairing interactively, then appends the device (id/display_name/room/address/adapter) to `devices.json`.
- The dashboard does not auto-poll AC status (unlike Shelly's 5s polling) to avoid hammering the BLE stack; each card fetches its status once on page load and after every action, plus a manual refresh button.
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
