#!/usr/bin/env python3
import json
import urllib.error
import urllib.request

BASE = "http://localhost:5000"


def find_id(list_endpoint: str, name_substring: str) -> str:
    with urllib.request.urlopen(BASE + list_endpoint, timeout=10) as resp:
        devices = json.load(resp)

    for device in devices:
        if name_substring.lower() in device["display_name"].lower():
            return device["id"]

    raise ValueError("No device matching: " + name_substring)


def main() -> None:
    device_id = find_id("/api/daikin/devices", "AC Escritorio")

    request = urllib.request.Request(
        BASE + f"/api/daikin/{device_id}/power",
        data=json.dumps({"state": "on"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.load(response)

    if not result.get("ok"):
        raise RuntimeError(result.get("error", "Unknown API error"))

    print(f"AC Escritório ligado: power={result.get('power')}")


if __name__ == "__main__":
    try:
        main()
    except (urllib.error.URLError, ValueError, RuntimeError, TimeoutError) as exc:
        print(f"ERRO: {exc}")
        raise
