import re
import time
import urllib.error
import urllib.request

_URL = "https://wttr.in/?format=%25t+%25C"
_CONDITION_RE = re.compile(r"^([+-]?\d+)\s*\S*?\s+(.+)$")

_cache = {"data": None, "fetched_at": 0.0}


def get_weather(ttl_seconds: float = 1800.0, timeout: float = 5.0):
    now = time.time()
    if _cache["data"] is not None and (now - _cache["fetched_at"]) < ttl_seconds:
        return _cache["data"]

    try:
        with urllib.request.urlopen(_URL, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "ignore").strip()
    except (urllib.error.URLError, OSError, TimeoutError):
        return _cache["data"] or {"ok": False, "error": "Weather unavailable"}

    match = _CONDITION_RE.match(raw)
    if not match:
        return _cache["data"] or {"ok": False, "error": "Could not parse weather"}

    result = {
        "ok": True,
        "temp_c": int(match.group(1)),
        "condition": match.group(2).strip(),
    }
    _cache["data"] = result
    _cache["fetched_at"] = now
    return result
