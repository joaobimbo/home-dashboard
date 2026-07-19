# Weather API

See `README.md` for base URL.

`GET /api/weather` -> `{"ok": true, "temp_c": 19, "condition": "Clear"}` (cached ~30 min, cheap to call).

```python
result = json.load(urllib.request.urlopen(BASE + "/api/weather", timeout=10))
print(str(result["temp_c"]) + "°C, " + result["condition"]) if result.get("ok") else print("unavailable")
```
