#!/usr/bin/env python3
"""Debug helper: measure Daikin (Madoka) BLE latency directly, bypassing Flask.

Every /api/daikin/* request runs one full
force_disconnect -> discover -> connect -> query/update -> disconnect
cycle (see DaikinController._run in controller.py). Multi-second latency is
expected, but this script breaks that cycle down phase-by-phase so you can
see *which* phase is slow, and optionally compares the raw BLE time against
the same call made through a running Flask server.

Usage (run from the repo root, or anywhere - it fixes sys.path itself):
    python modules/daikin/debug_timing.py <device_id>
    python modules/daikin/debug_timing.py <device_id> --action power_on
    python modules/daikin/debug_timing.py <device_id> --http http://localhost:5000

If no device_id is given, or it doesn't match devices.json, configured
device ids are printed.

Reading the output:
  - If the direct BLE call is already slow (several seconds per phase),
    the bottleneck is Bluetooth/pymadoka, not the webpage/API.
  - If --http is passed and the HTTP total is much larger than the direct
    BLE total, the extra time is Flask/network overhead, not Bluetooth.
"""
import argparse
import asyncio
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from modules.daikin.controller import DaikinController, _load_pymadoka  # noqa: E402


async def _timed(label, coro):
    start = time.perf_counter()
    result = await coro
    elapsed = time.perf_counter() - start
    print(f"  [{elapsed:6.2f}s] {label}")
    return result


async def _run_status_queries(madoka):
    power = await _timed("power_state.query()", madoka.power_state.query())
    mode = await _timed("operation_mode.query()", madoka.operation_mode.query())
    set_point = await _timed("set_point.query()", madoka.set_point.query())
    fan = await _timed("fan_speed.query()", madoka.fan_speed.query())
    return {
        "power": bool(power.turn_on),
        "mode": str(mode.operation_mode).lower(),
        "setpoint": set_point.cooling_set_point,
        "fan_speed": str(fan.cooling_fan_speed).lower(),
    }


def run_direct(device, action_name, discover_timeout, quick_scan_timeout, force_full_scan):
    """Mirrors DaikinController._run phase-by-phase, with no Flask/HTTP involved."""
    lib = _load_pymadoka()

    async def runner():
        total_start = time.perf_counter()

        await _timed(
            "force_device_disconnect", lib["force_device_disconnect"](device.address)
        )

        matched = None
        if not force_full_scan:
            matched = await _timed(
                f"find_device_by_address (quick scan, timeout={quick_scan_timeout}s)",
                lib["BleakScanner"].find_device_by_address(
                    device.address, timeout=quick_scan_timeout, adapter=device.adapter
                ),
            )
        if matched is not None:
            lib["connection_module"].DISCOVERED_DEVICES_CACHE = [matched]
        else:
            cache = await _timed(
                f"discover_devices (full adapter scan, timeout={discover_timeout}s)",
                lib["discover_devices"](timeout=discover_timeout, adapter=device.adapter),
            )
            matched = next(
                (d for d in cache if d.address.upper() == device.address.upper()), None
            )

        madoka = lib["Controller"](device.address, adapter=device.adapter)
        if matched is not None:
            # No-op callback: pymadoka's real on_disconnect schedules an
            # unconditional reconnect on every disconnect, including our own
            # deliberate one - see controller.py for the full explanation.
            madoka.connection.client = lib["BleakClient"](
                matched,
                adapter=device.adapter,
                disconnected_callback=lambda _client: None,
            )
        await _timed("controller.start (BLE connect)", madoka.start())

        try:
            if action_name == "status":
                payload = await _run_status_queries(madoka)
            elif action_name in ("power_on", "power_off"):
                on = action_name == "power_on"
                await _timed(
                    "power_state.update()",
                    madoka.power_state.update(lib["PowerStateStatus"](on)),
                )
                payload = await _run_status_queries(madoka)
            else:
                raise ValueError(f"Unknown action {action_name!r}")
        finally:
            await _timed("controller.stop (BLE disconnect)", madoka.stop())

        total = time.perf_counter() - total_start
        print("  --------")
        print(f"  [{total:6.2f}s] TOTAL (direct BLE call, no Flask/HTTP involved)")
        return payload

    return asyncio.run(runner())


def run_via_http(base_url, device_id, action_name):
    if action_name == "status":
        url = f"{base_url}/api/daikin/{device_id}/status"
        method = "GET"
        body = None
    else:
        url = f"{base_url}/api/daikin/{device_id}/power"
        method = "POST"
        body = json.dumps(
            {"state": "on" if action_name == "power_on" else "off"}
        ).encode()

    req = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")

    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read())
    except urllib.error.URLError as exc:
        elapsed = time.perf_counter() - start
        print(f"  [{elapsed:6.2f}s] HTTP request FAILED: {exc}")
        return None
    elapsed = time.perf_counter() - start
    print(f"  [{elapsed:6.2f}s] TOTAL (via Flask HTTP {method} {url})")
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("device_id", nargs="?", help="Device id from devices.json")
    parser.add_argument(
        "--action",
        choices=["status", "power_on", "power_off"],
        default="status",
        help="Command to run (default: status)",
    )
    parser.add_argument(
        "--discover-timeout",
        type=float,
        default=4.0,
        help="Fallback full-scan discover_devices timeout in seconds, used only if the "
        "quick address lookup fails (default: 4.0, same as the controller default)",
    )
    parser.add_argument(
        "--quick-scan-timeout",
        type=float,
        default=2.0,
        help="find_device_by_address timeout in seconds - it returns as soon as the "
        "device is seen, this is just the give-up threshold (default: 2.0)",
    )
    parser.add_argument(
        "--force-full-scan",
        action="store_true",
        help="Skip the quick address lookup and always use the slow full adapter scan "
        "(useful to reproduce/compare against the old behaviour).",
    )
    parser.add_argument(
        "--http",
        metavar="BASE_URL",
        help="Also run the same action through a running Flask server "
        "(e.g. http://localhost:5000) and print both timings for comparison.",
    )
    parser.add_argument(
        "--http-only",
        action="store_true",
        help="Skip the direct BLE call and only time the HTTP path (requires --http).",
    )
    args = parser.parse_args()

    controller = DaikinController.from_sources()
    device = controller._device_map.get(args.device_id) if args.device_id else None
    if device is None:
        print(f"Unknown device id {args.device_id!r}. Configured devices:")
        for d in controller.devices:
            print(f"  - {d.id}  ({d.display_name}, {d.address}, adapter={d.adapter})")
        sys.exit(1)

    if not args.http_only:
        print(f"=== Direct BLE call (bypasses Flask entirely) - {device.display_name} ===")
        try:
            run_direct(
                device,
                args.action,
                args.discover_timeout,
                args.quick_scan_timeout,
                args.force_full_scan,
            )
        except Exception as exc:
            print(f"  Direct call FAILED: {exc!r}")
        print()

    if args.http:
        print(f"=== Same action via Flask HTTP API ({args.http}) ===")
        run_via_http(args.http, args.device_id, args.action)
        print()

    if not args.http_only and args.http:
        print(
            "If the two totals are close, the slowdown is in Bluetooth/pymadoka, not the webpage/API.\n"
            "If the HTTP call takes noticeably longer than the direct call, look at Flask/network overhead instead."
        )


if __name__ == "__main__":
    main()
