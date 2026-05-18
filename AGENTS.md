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
  - scenes APIs still exist in backend (`/api/scenes*`) even if UI is currently trimmed.
- Frontend entrypoints: `templates/index.html`, `static/app.js`, `static/style.css`.

## Shelly module conventions

- All Shelly logic is centralized in `modules/shelly/`.
- Browser must not call Shelly devices directly; always go through Flask endpoints.
- `ShellyController.from_sources()` load order:
  1) `modules/shelly/devices.json`
  2) `SHELLY_DEVICES_JSON`
  3) hardcoded fallback devices

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
