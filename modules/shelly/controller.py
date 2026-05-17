import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List
from urllib import error, parse, request


@dataclass(frozen=True)
class ShellyDevice:
    id: str
    display_name: str
    host: str
    relay: int = 0
    image: str = ""
    other_names: List[str] = field(default_factory=list)

    @property
    def name(self):
        return self.display_name


class ShellyController:
    def __init__(self, devices: List[ShellyDevice], timeout_seconds: int = 2):
        self.devices = devices
        self._timeout_seconds = timeout_seconds
        self._device_map: Dict[str, ShellyDevice] = {d.id: d for d in devices}

    @classmethod
    def from_sources(cls, config_path: str = "modules/shelly/devices.json"):
        file_devices = cls._load_from_file(config_path)
        if file_devices:
            return cls(file_devices)

        env_devices = cls._load_from_environment()
        if env_devices:
            return cls(env_devices)

        fallback_devices = [
            ShellyDevice("living-room", "Living Room", "192.168.1.50"),
            ShellyDevice("kitchen", "Kitchen", "192.168.1.51"),
            ShellyDevice("hallway", "Hallway", "192.168.1.52"),
        ]
        return cls(fallback_devices)

    @staticmethod
    def _load_from_file(config_path: str):
        path = Path(config_path)
        if not path.exists():
            return []

        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
            return [
                ShellyDevice(
                    id=item["id"],
                    display_name=item.get("display_name")
                    or item.get("name")
                    or item["id"],
                    host=item["host"],
                    relay=int(item.get("relay", 0)),
                    image=str(item.get("image", "")),
                    other_names=list(item.get("other_names", [])),
                )
                for item in parsed
            ]
        except (json.JSONDecodeError, KeyError, ValueError, TypeError, OSError):
            return []

    @staticmethod
    def _load_from_environment():
        raw_config = os.environ.get("SHELLY_DEVICES_JSON", "").strip()

        if raw_config:
            try:
                parsed = json.loads(raw_config)
                return [
                    ShellyDevice(
                        id=item["id"],
                        display_name=item.get("display_name")
                        or item.get("name")
                        or item["id"],
                        host=item["host"],
                        relay=int(item.get("relay", 0)),
                        image=str(item.get("image", "")),
                        other_names=list(item.get("other_names", [])),
                    )
                    for item in parsed
                ]
            except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                pass

        return []

    def read_all(self):
        return [self.read_device(device.id) for device in self.devices]

    def read_device(self, device_id: str):
        device = self._device_map.get(device_id)
        if device is None:
            return {"ok": False, "id": device_id, "error": "Unknown device"}

        try:
            relay_status = self._request_json(device, "/relay/0")
            is_on = bool(relay_status.get("ison", False))
            return {
                "ok": True,
                "id": device.id,
                "name": device.name,
                "state": "on" if is_on else "off",
                "reachable": True,
            }
        except Exception as exc:
            return {
                "ok": False,
                "id": device.id,
                "name": device.name,
                "state": "unknown",
                "reachable": False,
                "error": str(exc),
            }

    def apply_action(self, device_id: str, action: str):
        device = self._device_map.get(device_id)
        if device is None:
            return {"ok": False, "error": "Unknown device"}

        if action == "toggle":
            status = self.read_device(device_id)
            if not status.get("ok"):
                return status
            target_action = "off" if status.get("state") == "on" else "on"
        else:
            target_action = action

        try:
            state_value = "on" if target_action == "on" else "off"
            self._request_json(device, f"/relay/{device.relay}?turn={state_value}")
            updated = self.read_device(device_id)
            if updated.get("ok"):
                return {"ok": True, **updated}
            return updated
        except Exception as exc:
            return {
                "ok": False,
                "id": device.id,
                "name": device.name,
                "error": str(exc),
            }

    def _request_json(self, device: ShellyDevice, endpoint: str):
        encoded_endpoint = parse.quote(endpoint, safe="/?=&")
        url = f"http://{device.host}{encoded_endpoint}"
        req = request.Request(url=url, method="GET")
        try:
            with request.urlopen(req, timeout=self._timeout_seconds) as response:
                body = response.read().decode("utf-8")
                return json.loads(body)
        except error.URLError as exc:
            raise RuntimeError(f"Device {device.name} unreachable") from exc
