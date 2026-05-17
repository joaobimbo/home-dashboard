#!/usr/bin/env python3
import argparse
import ipaddress
import json
import re
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional
from urllib import request


def parse_args():
    parser = argparse.ArgumentParser(
        description="Discover Shelly devices on LAN and write editable config"
    )
    parser.add_argument(
        "--network",
        default="192.168.1.0/24",
        help="CIDR network to scan (default: 192.168.1.0/24)",
    )
    parser.add_argument(
        "--output",
        default="modules/shelly/devices.json",
        help="Output JSON config path",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=0.5,
        help="Per-host timeout in seconds",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=64,
        help="Parallel workers for scan",
    )
    parser.add_argument(
        "--no-merge",
        action="store_true",
        help="Do not preserve name/image edits from existing file",
    )
    return parser.parse_args()


def slugify(value: str):
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "shelly-device"


def http_json(url: str, timeout: float):
    req = request.Request(url=url, method="GET")
    with request.urlopen(req, timeout=timeout) as response:
        body = response.read().decode("utf-8")
        return json.loads(body)


def probe_host(host: str, timeout: float) -> Optional[Dict[str, object]]:
    try:
        with socket.create_connection((host, 80), timeout=timeout):
            pass
    except OSError:
        return None

    model = "Shelly"
    device_name = ""

    try:
        data = http_json(f"http://{host}/shelly", timeout)
        model = data.get("type") or data.get("model") or model
        settings = http_json(f"http://{host}/settings", timeout)
        device_name = settings.get("name") or ""
    except Exception:
        try:
            data = http_json(f"http://{host}/rpc/Shelly.GetDeviceInfo", timeout)
            model = data.get("model") or model
            device_name = data.get("name") or ""
        except Exception:
            return None

    if not device_name:
        device_name = f"{model} {host.split('.')[-1]}"

    return {
        "id": slugify(device_name),
        "device_name": device_name,
        "display_name": device_name,
        "other_names": [],
        "host": host,
        "relay": 0,
        "image": "",
    }


def scan_network(cidr: str, timeout: float, workers: int):
    network = ipaddress.ip_network(cidr, strict=False)
    hosts = [str(ip) for ip in network.hosts()]
    devices: List[Dict[str, object]] = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(probe_host, host, timeout): host for host in hosts}
        for future in as_completed(futures):
            result = future.result()
            if result:
                devices.append(result)

    unique_by_host = {device["host"]: device for device in devices}
    deduped = list(unique_by_host.values())
    deduped.sort(key=lambda d: d["host"])
    return deduped


def load_existing(path: Path):
    if not path.exists():
        return []
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def merge_manual_fields(
    found: List[Dict[str, object]], existing: List[Dict[str, object]]
):
    existing_by_host = {item.get("host"): item for item in existing}
    for device in found:
        current = existing_by_host.get(device["host"])
        if not current:
            continue
        if current.get("display_name"):
            device["display_name"] = current["display_name"]
            device["id"] = slugify(current["display_name"])
        elif current.get("name"):
            device["display_name"] = current["name"]
            device["id"] = slugify(current["name"])
        if isinstance(current.get("other_names"), list):
            device["other_names"] = [str(name) for name in current["other_names"]]
        if current.get("image"):
            device["image"] = current["image"]
        if current.get("relay") is not None:
            try:
                device["relay"] = int(current["relay"])
            except (TypeError, ValueError):
                pass
    return found


def write_config(path: Path, devices: List[Dict[str, object]]):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(devices, indent=2, ensure_ascii=True)
    path.write_text(payload + "\n", encoding="utf-8")


def main():
    args = parse_args()
    output_path = Path(args.output)

    discovered = scan_network(args.network, args.timeout, args.workers)
    existing = load_existing(output_path)

    if not args.no_merge:
        discovered = merge_manual_fields(discovered, existing)

    write_config(output_path, discovered)
    print(f"Discovered {len(discovered)} device(s)")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
