# AGENTS.md — Home Dashboard

## Scope and constraints

- Current milestone is only the dashboard frame + Shelly controls; do not implement Spotify/calendar/photos/voice yet.
- Keep stack minimal: Python + Flask + Jinja templates + plain HTML/CSS + small vanilla JS.
- Do not introduce Node/npm/frontend frameworks, Docker, or a database unless explicitly requested.

## Entrypoints and runtime

- Start server with `python app.py`.
- Flask binds `0.0.0.0:5000` in `app.py`, so it should work on LAN at `http://<host-ip>:5000`.
- Main wiring is in `app.py`: page route `/`, health `/api/status`, Shelly APIs under `/api/shelly/*`.

## Shelly architecture (important)

- Shelly code is centralized in `modules/shelly/`.
- Browser never calls Shelly devices directly; all control/status goes through Flask endpoints.
- Device list source order in `ShellyController.from_sources()`:
  1) `modules/shelly/devices.json`
  2) `SHELLY_DEVICES_JSON` env var
  3) hardcoded fallback sample devices

## Discovery workflow

- Discovery is manual/on-demand via `python modules/shelly/discover.py`; it is not part of server startup.
- Default discovery scan is CIDR `192.168.1.0/24`; override with `--network`.
- Discovery writes editable JSON to `modules/shelly/devices.json` (default) and merges manual fields unless `--no-merge`.
- Supported naming fields in registry: `device_name` (discovered), `display_name` (UI/manual), `other_names` (aliases).

## File-level map

- `app.py`: Flask app + API routes.
- `modules/shelly/controller.py`: config loading, device status reads, on/off/toggle actions.
- `modules/shelly/discover.py`: LAN scan + config generation/merge.
- `templates/index.html`, `static/app.js`, `static/style.css`: dashboard UI.

## Verified dev checks

- No repo test/lint/typecheck config is present right now; use focused smoke checks.
- Useful quick check: `python -m py_compile app.py modules/shelly/controller.py modules/shelly/discover.py`.
