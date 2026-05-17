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
    default_output = Path(__file__).resolve().parent / "devices.json"
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
        default=str(default_output),
        help="Output JSON config path",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=1.5,
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


def output_label(component: str, channel: int):
    if component == "cover":
        return f"Shutter {channel + 1}"
    if component == "light":
        return f"Dimmer {channel + 1}"
    return f"Switch {channel + 1}"


def build_entry(
    host: str,
    model: str,
    device_name: str,
    component: str,
    relay: int,
    channel_name: str,
):
    base_name = (
        channel_name.strip() or device_name.strip() or f"{model} {host.split('.')[-1]}"
    )
    if channel_name.strip() or not device_name.strip() or component == "relay":
        display_name = base_name
    else:
        display_name = f"{base_name} {output_label(component, relay)}"

    return {
        "id": slugify(f"{display_name}-{host}-{component}-{relay}"),
        "device_name": device_name.strip() or base_name,
        "display_name": display_name,
        "other_names": [],
        "room": "Casa",
        "host": host,
        "component": component,
        "relay": relay,
        "image": "",
    }


def probe_host(host: str, timeout: float) -> Optional[Dict[str, object]]:
    try:
        with socket.create_connection((host, 80), timeout=timeout):
            pass
    except OSError:
        return None

    model = "Shelly"
    device_name = ""
    entries: List[Dict[str, object]] = []

    try:
        legacy_info = http_json(f"http://{host}/shelly", timeout)
        model = legacy_info.get("type") or legacy_info.get("model") or model
        settings = http_json(f"http://{host}/settings", timeout)
        device_name = settings.get("name") or ""

        relays = settings.get("relays")
        if isinstance(relays, list) and relays:
            for idx, relay_conf in enumerate(relays):
                relay_name = ""
                if isinstance(relay_conf, dict):
                    relay_name = str(relay_conf.get("name", ""))
                entries.append(
                    build_entry(host, model, device_name, "relay", idx, relay_name)
                )

        lights = settings.get("lights")
        if isinstance(lights, list) and lights:
            for idx, light_conf in enumerate(lights):
                light_name = ""
                if isinstance(light_conf, dict):
                    light_name = str(light_conf.get("name", ""))
                entries.append(
                    build_entry(host, model, device_name, "light", idx, light_name)
                )

        rollers = settings.get("rollers")
        if isinstance(rollers, list) and rollers:
            for idx, roller_conf in enumerate(rollers):
                roller_name = ""
                if isinstance(roller_conf, dict):
                    roller_name = str(roller_conf.get("name", ""))
                entries.append(
                    build_entry(host, model, device_name, "cover", idx, roller_name)
                )
    except Exception:
        pass

    if entries:
        return {"host": host, "entries": entries}

    try:
        info = http_json(f"http://{host}/rpc/Shelly.GetDeviceInfo", timeout)
        model = info.get("model") or model

        config = http_json(f"http://{host}/rpc/Shelly.GetConfig", timeout)
        if not isinstance(config, dict):
            return None
        device_cfg = config.get("device", {}) if isinstance(config, dict) else {}
        if isinstance(device_cfg, dict):
            device_name = str(device_cfg.get("name") or "")

        for key, value in config.items():
            if not isinstance(value, dict):
                continue
            if ":" not in key:
                continue
            component, channel_text = key.split(":", 1)
            if component not in {"switch", "cover", "light"}:
                continue
            try:
                channel = int(channel_text)
            except ValueError:
                continue
            channel_name = str(value.get("name") or "")
            entries.append(
                build_entry(host, model, device_name, component, channel, channel_name)
            )
    except Exception:
        return None

    if not entries:
        entries.append(build_entry(host, model, device_name, "switch", 0, ""))

    return {"host": host, "entries": entries}


def scan_network(cidr: str, timeout: float, workers: int):
    network = ipaddress.ip_network(cidr, strict=False)
    hosts = [str(ip) for ip in network.hosts()]
    devices: List[Dict[str, object]] = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(probe_host, host, timeout): host for host in hosts}
        for future in as_completed(futures):
            result = future.result()
            if result and isinstance(result.get("entries"), list):
                devices.extend(result["entries"])

    devices.sort(key=lambda d: (d["host"], int(d.get("relay", 0))))
    return devices


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
    existing_by_key = {}
    for item in existing:
        key = (
            item.get("host"),
            str(item.get("component", "relay")),
            int(item.get("relay", 0)) if item.get("relay") is not None else 0,
        )
        existing_by_key[key] = item

    for device in found:
        key = (
            device.get("host"),
            str(device.get("component", "relay")),
            int(device.get("relay", 0)),
        )
        current = existing_by_key.get(key)
        if not current:
            continue

        current_display = str(current.get("display_name") or "").strip()
        current_device_name = str(
            current.get("device_name") or current.get("name") or ""
        ).strip()

        # Preserve display_name only when it looks like a manual override.
        # If it matches auto-generated fields, keep the newly discovered name.
        if current_display and current_display not in {
            current_device_name,
            str(current.get("id") or "").strip(),
        }:
            device["display_name"] = current_display
            device["id"] = slugify(current_display)

        if isinstance(current.get("other_names"), list):
            device["other_names"] = [str(name) for name in current["other_names"]]
        if current.get("room"):
            device["room"] = str(current["room"])
        if current.get("image"):
            device["image"] = current["image"]
        if current.get("component"):
            device["component"] = str(current["component"])
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
