# Shelly API — lights, blinds, dimmers

See `README.md` for base URL, response convention, and `find_id()`.

| Method | Path | Body | Notes |
|---|---|---|---|
| GET | `/api/shelly/configured` | - | `id`, `display_name`, `component`, `room` |
| GET | `/api/shelly/devices` | - | same + live state |
| POST | `/api/shelly/<id>/action` | `{"action": "on\|off\|toggle"}` | switch/relay only |
| POST | `/api/shelly/<id>/cover_action` | `{"command": "open\|close\|stop"}` | cover only |
| POST | `/api/shelly/<id>/position` | `{"position": 0-100}` | cover only. 0=closed, 100=open |
| POST | `/api/shelly/<id>/light_action` | `{"command": "on\|off\|up\|down"}` | light/dimmer only |
| POST | `/api/shelly/<id>/light_level` | `{"brightness": 0-100}` | light/dimmer only |

Cover/light endpoints 400 if called on the wrong `component`. Action/status responses return `{"ok", "id", "name", "component", "state", "reachable"}` plus `"position"` (cover) or `"brightness"` (light) where applicable.

## Devices (may drift — prefer `find_id()`)

| display_name | component | room |
|---|---|---|
| Escritorio, Quarto 1, Quarto 2, Corredor, Cozinha, Cozinha Mesa, Luz Hall | switch | Casa |
| Luz Sala | light | Casa |
| Estore Sala, Estore Escritorio, Estore Quarto 1A, Estore Quarto 1 B, Estore Quarto 2 | cover | Casa |

## Example

```python
device_id = find_id("/api/shelly/configured", "escritorio")
req = urllib.request.Request(
    BASE + "/api/shelly/" + device_id + "/action",
    data=json.dumps({"action": "toggle"}).encode(),
    headers={"Content-Type": "application/json"}, method="POST",
)
result = json.load(urllib.request.urlopen(req, timeout=10))
if not result.get("ok"):
    raise RuntimeError(result.get("error"))
```
`position`/`cover_action`/`light_action`/`light_level` follow the same shape — just a different path and body.
