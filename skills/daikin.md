# Daikin API — Madoka AC units (Bluetooth)

See `README.md` for base URL, response convention, and `find_id()`.

**Slow on purpose:** every action (and `?live=1` status read) does a real
BLE round trip, typically 7-10s. Use a 30s timeout. Requests are serialized
server-side (one radio), so firing several at once doesn't speed anything up.

| Method | Path | Body | Notes |
|---|---|---|---|
| GET | `/api/daikin/devices` | - | `id`, `display_name`, `room` |
| GET | `/api/daikin/<id>/status` | - | cached, fast. Add `?live=1` to force a real (slow) read |
| POST | `/api/daikin/<id>/power` | `{"state": "on\|off"}` | |
| POST | `/api/daikin/<id>/mode` | `{"mode": "auto\|cool\|heat\|dry\|fan"}` | |
| POST | `/api/daikin/<id>/setpoint` | `{"temperature": 10-32}` | whole °C |
| POST | `/api/daikin/<id>/fan` | `{"speed": "auto\|low\|mid\|high"}` | |

All return `{"ok", "id", "name", "power", "mode", "setpoint", "current_temp", "fan_speed"}` on success.

## Devices (may drift — prefer `find_id()`)

| display_name | room |
|---|---|
| AC Escritorio | Escritorio |
| AC Sala | Sala |
| AC Quarto | Quarto |
| AC Quarto 2 | Quarto 2 |

## Example

```python
device_id = find_id("/api/daikin/devices", "sala")
req = urllib.request.Request(
    BASE + "/api/daikin/" + device_id + "/power",
    data=json.dumps({"state": "off"}).encode(),
    headers={"Content-Type": "application/json"}, method="POST",
)
result = json.load(urllib.request.urlopen(req, timeout=30))  # generous timeout - BLE
if not result.get("ok"):
    raise RuntimeError(result.get("error"))
```
`mode`/`setpoint`/`fan` follow the same shape — different path and body.
For "in N hours", see `scheduling.md`.
