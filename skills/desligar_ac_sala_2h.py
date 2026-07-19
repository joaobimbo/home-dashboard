#!/usr/bin/env python3
import json
import time
import urllib.error
import urllib.request

BASE = "http://localhost:5000"
DELAY_SECONDS = 2 * 60 * 60


def find_id(list_endpoint: str, name_substring: str) -> str:
    with urllib.request.urlopen(BASE + list_endpoint, timeout=10) as resp:
        devices = json.load(resp)

    for device in devices:
        if name_substring.lower() in device["display_name"].lower():
            return device["id"]

    raise ValueError("No device matching: " + name_substring)


def post_json(path: str, payload: dict, timeout: int) -> dict:
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.load(response)

    if not result.get("ok"):
        raise RuntimeError(result.get("error", "Unknown API error"))

    return result


def main() -> None:
    # Resolve the device before waiting, so configuration errors appear immediately.
    device_id = find_id("/api/daikin/devices", "AC Sala")
    print(f"Scheduled AC Sala ({device_id}) to turn off in 2 hours.", flush=True)

    time.sleep(DELAY_SECONDS)

    result = post_json(
        f"/api/daikin/{device_id}/power",
        {"state": "off"},
        timeout=30,
    )
    print(
        f"AC Sala turned off successfully: power={result.get('power')}",
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except (urllib.error.URLError, ValueError, RuntimeError, TimeoutError) as exc:
        print(f"ERROR: {exc}", flush=True)
        raise
