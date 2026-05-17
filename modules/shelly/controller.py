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
    device_name: str = ""
    relay: int = 0
    image: str = ""
    room: str = "Casa"
    other_names: List[str] = field(default_factory=list)

    @property
    def name(self):
        return self.display_name


class ShellyController:
    def __init__(
        self,
        devices: List[ShellyDevice],
        timeout_seconds: int = 2,
        config_path: str | None = None,
    ):
        self.devices = devices
        self._timeout_seconds = timeout_seconds
        self._device_map: Dict[str, ShellyDevice] = {d.id: d for d in devices}
        self._config_path = config_path

    @classmethod
    def from_sources(cls, config_path: str | None = None):
        if config_path is None:
            config_path = str(Path(__file__).resolve().parent / "devices.json")
        file_devices = cls._load_from_file(config_path)
        if file_devices:
            return cls(file_devices, config_path=config_path)

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
                    device_name=str(
                        item.get("device_name")
                        or item.get("display_name")
                        or item.get("name")
                        or item["id"]
                    ),
                    relay=int(item.get("relay", 0)),
                    image=str(item.get("image", "")),
                    room=str(item.get("room", "Casa")),
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
                        device_name=str(
                            item.get("device_name")
                            or item.get("display_name")
                            or item.get("name")
                            or item["id"]
                        ),
                        relay=int(item.get("relay", 0)),
                        image=str(item.get("image", "")),
                        room=str(item.get("room", "Casa")),
                        other_names=list(item.get("other_names", [])),
                    )
                    for item in parsed
                ]
            except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                pass

        return []

    def read_all(self):
        return [self.read_device(device.id) for device in self.devices]

    def list_configured_devices(self):
        return [
            {
                "id": device.id,
                "name": device.name,
                "display_name": device.display_name,
                "host": device.host,
                "relay": device.relay,
                "image": device.image,
                "room": device.room,
                "other_names": device.other_names,
            }
            for device in self.devices
        ]

    def update_device_config(self, device_id: str, updates: Dict[str, object]):
        device = self._device_map.get(device_id)
        if device is None:
            return {"ok": False, "error": "Unknown device"}

        display_name = str(updates.get("display_name", device.display_name)).strip()
        room = str(updates.get("room", device.room)).strip() or "Casa"
        image = str(updates.get("image", device.image)).strip()
        other_names_raw = updates.get("other_names", device.other_names)
        if isinstance(other_names_raw, str):
            other_names = [
                item.strip() for item in other_names_raw.split(",") if item.strip()
            ]
        elif isinstance(other_names_raw, list):
            other_names = [
                str(item).strip() for item in other_names_raw if str(item).strip()
            ]
        else:
            other_names = list(device.other_names)

        updated_device = ShellyDevice(
            id=device.id,
            display_name=display_name or device.id,
            host=device.host,
            device_name=device.device_name,
            relay=device.relay,
            image=image,
            room=room,
            other_names=other_names,
        )

        self.devices = [
            updated_device if current.id == device_id else current
            for current in self.devices
        ]
        self._device_map[device_id] = updated_device
        self._write_config_file()

        return {"ok": True, "device": self._device_to_dict(updated_device)}

    def _device_to_dict(self, device: ShellyDevice):
        return {
            "id": device.id,
            "device_name": device.device_name,
            "display_name": device.display_name,
            "host": device.host,
            "relay": device.relay,
            "image": device.image,
            "room": device.room,
            "other_names": device.other_names,
        }

    def reorder_devices(self, ordered_ids: List[str]):
        if not ordered_ids:
            return {"ok": False, "error": "No device ids provided"}

        current_ids = [device.id for device in self.devices]
        if set(ordered_ids) != set(current_ids):
            return {"ok": False, "error": "Device id set mismatch"}

        by_id = {device.id: device for device in self.devices}
        self.devices = [by_id[device_id] for device_id in ordered_ids]
        self._device_map = {device.id: device for device in self.devices}
        self._write_config_file()
        return {"ok": True, "order": ordered_ids}

    def _write_config_file(self):
        if not self._config_path:
            return

        path = Path(self._config_path)
        payload = []
        for device in self.devices:
            payload.append(
                {
                    "id": device.id,
                    "device_name": device.device_name or device.display_name,
                    "display_name": device.display_name,
                    "other_names": device.other_names,
                    "room": device.room,
                    "host": device.host,
                    "relay": device.relay,
                    "image": device.image,
                }
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
        )

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

    def apply_action_to_devices(self, action: str, room: str | None = None):
        if action not in {"on", "off", "toggle"}:
            return {"ok": False, "error": "Invalid action"}

        if room and room != "all":
            targets = [device for device in self.devices if device.room == room]
        else:
            targets = list(self.devices)

        results = [self.apply_action(device.id, action) for device in targets]
        success = sum(1 for item in results if item.get("ok"))
        return {
            "ok": True,
            "action": action,
            "room": room or "all",
            "total": len(results),
            "success": success,
            "failed": len(results) - success,
            "results": results,
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
