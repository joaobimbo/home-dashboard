import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    component: str = "relay"
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
                    component=str(item.get("component", "relay")),
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
                        component=str(item.get("component", "relay")),
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
        if not self.devices:
            return []

        results: List[Dict[str, object]] = []
        workers = min(16, max(1, len(self.devices)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self.read_device, device.id): index
                for index, device in enumerate(self.devices)
            }
            ordered: Dict[int, Dict[str, object]] = {}
            for future in as_completed(futures):
                index = futures[future]
                ordered[index] = future.result()

        for index in sorted(ordered.keys()):
            results.append(ordered[index])
        return results

    def list_configured_devices(self):
        return [
            {
                "id": device.id,
                "name": device.name,
                "display_name": device.display_name,
                "host": device.host,
                "component": device.component,
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
            component=device.component,
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
            "component": device.component,
            "relay": device.relay,
            "image": device.image,
            "room": device.room,
            "other_names": device.other_names,
        }

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
                    "component": device.component,
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
            relay_status = self._read_status(device)
            state = self._extract_state(device, relay_status)
            result = {
                "ok": True,
                "id": device.id,
                "name": device.name,
                "component": device.component,
                "state": state,
                "reachable": True,
            }
            if (device.component or "relay").lower() == "cover":
                pos = relay_status.get("current_pos")
                if isinstance(pos, (int, float)):
                    result["position"] = int(max(0, min(100, round(pos))))
            component = (device.component or "relay").lower()
            if component in {"light", "rgbcct"}:
                brightness = relay_status.get("brightness")
                if isinstance(brightness, (int, float)):
                    result["brightness"] = int(max(0, min(100, round(brightness))))
            if component == "rgbcct":
                mode = str(relay_status.get("mode", "")).lower()
                if mode in {"rgb", "cct"}:
                    result["mode"] = mode
                rgb = relay_status.get("rgb")
                if (
                    isinstance(rgb, list)
                    and len(rgb) == 3
                    and all(isinstance(value, (int, float)) for value in rgb)
                ):
                    result["rgb"] = [
                        int(max(0, min(255, round(value)))) for value in rgb
                    ]
                color_temp = relay_status.get("ct")
                if isinstance(color_temp, (int, float)):
                    result["color_temp"] = int(round(color_temp))
            return result
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
            self._apply_output_action(device, state_value)
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

    def set_cover_position(self, device_id: str, position: int):
        device = self._device_map.get(device_id)
        if device is None:
            return {"ok": False, "error": "Unknown device"}

        if (device.component or "relay").lower() != "cover":
            return {"ok": False, "error": "Device is not a cover"}

        target = max(0, min(100, int(position)))
        try:
            self._request_json(
                device, f"/rpc/Cover.GoToPosition?id={int(device.relay)}&pos={target}"
            )
            updated = self.read_device(device_id)
            if updated.get("ok"):
                updated["position"] = target
                return {"ok": True, **updated}
            return updated
        except Exception as exc:
            return {
                "ok": False,
                "id": device.id,
                "name": device.name,
                "error": str(exc),
            }

    def apply_cover_command(self, device_id: str, command: str):
        device = self._device_map.get(device_id)
        if device is None:
            return {"ok": False, "error": "Unknown device"}

        if (device.component or "relay").lower() != "cover":
            return {"ok": False, "error": "Device is not a cover"}

        if command not in {"open", "close", "stop"}:
            return {"ok": False, "error": "Invalid cover command"}

        channel = int(device.relay)
        try:
            try:
                if command == "open":
                    self._request_json(device, f"/rpc/Cover.Open?id={channel}")
                elif command == "close":
                    self._request_json(device, f"/rpc/Cover.Close?id={channel}")
                else:
                    self._request_json(device, f"/rpc/Cover.Stop?id={channel}")
            except Exception:
                self._request_json(device, f"/roller/{channel}?go={command}")

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

    def apply_light_command(self, device_id: str, command: str):
        device = self._device_map.get(device_id)
        if device is None:
            return {"ok": False, "error": "Unknown device"}

        if (device.component or "relay").lower() != "light":
            return {"ok": False, "error": "Device is not a light dimmer"}

        if command not in {"on", "off", "up", "down"}:
            return {"ok": False, "error": "Invalid light command"}

        channel = int(device.relay)
        try:
            if command == "on":
                self._set_light_state(device, channel, True)
            elif command == "off":
                self._set_light_state(device, channel, False)
            else:
                status = self._read_status(device)
                current = status.get("brightness")
                if not isinstance(current, (int, float)):
                    current = 0
                step = 5 if command == "up" else -5
                target = int(max(0, min(100, round(current + step))))
                self._set_light_brightness(device, channel, target)

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

    def set_light_brightness(self, device_id: str, brightness: int):
        device = self._device_map.get(device_id)
        if device is None:
            return {"ok": False, "error": "Unknown device"}

        if (device.component or "relay").lower() != "light":
            return {"ok": False, "error": "Device is not a light dimmer"}

        level = int(max(0, min(100, brightness)))
        try:
            self._set_light_brightness(device, int(device.relay), level)
            updated = self.read_device(device_id)
            if updated.get("ok"):
                updated["brightness"] = level
                return {"ok": True, **updated}
            return updated
        except Exception as exc:
            return {
                "ok": False,
                "id": device.id,
                "name": device.name,
                "error": str(exc),
            }

    def set_rgbcct(self, device_id: str, updates: Dict[str, object]):
        device = self._device_map.get(device_id)
        if device is None:
            return {"ok": False, "error": "Unknown device"}
        if (device.component or "relay").lower() != "rgbcct":
            return {"ok": False, "error": "Device is not an RGBCCT light"}

        allowed = {"on", "brightness", "mode", "rgb", "color_temp"}
        if not updates or any(key not in allowed for key in updates):
            return {"ok": False, "error": "Invalid RGBCCT fields"}

        params = [f"id={int(device.relay)}"]
        try:
            if "on" in updates:
                if not isinstance(updates["on"], bool):
                    raise ValueError("on must be true or false")
                params.append("on=" + ("true" if updates["on"] else "false"))

            if "brightness" in updates:
                if type(updates["brightness"]) is not int:
                    raise ValueError("brightness must be an integer")
                brightness = int(updates["brightness"])
                if brightness < 1 or brightness > 100:
                    raise ValueError("brightness must be between 1 and 100")
                params.append(f"brightness={brightness}")

            if "mode" in updates:
                mode = str(updates["mode"]).lower()
                if mode not in {"rgb", "cct"}:
                    raise ValueError("mode must be rgb or cct")
                params.append(f"mode={mode}")

            if "rgb" in updates:
                rgb = updates["rgb"]
                if not isinstance(rgb, list) or len(rgb) != 3:
                    raise ValueError("rgb must contain three values")
                if any(type(value) is not int for value in rgb):
                    raise ValueError("rgb values must be integers")
                values = [int(value) for value in rgb]
                if any(value < 0 or value > 255 for value in values):
                    raise ValueError("rgb values must be between 0 and 255")
                params.append("rgb=" + json.dumps(values, separators=(",", ":")))

            if "color_temp" in updates:
                if type(updates["color_temp"]) is not int:
                    raise ValueError("color_temp must be an integer")
                color_temp = int(updates["color_temp"])
                if color_temp < 2700 or color_temp > 6500:
                    raise ValueError("color_temp must be between 2700 and 6500")
                params.append(f"ct={color_temp}")
        except (TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

        if "on" not in updates and "brightness" not in updates:
            return {"ok": False, "error": "RGBCCT requires on or brightness"}

        try:
            self._request_json(device, "/rpc/RGBCCT.Set?" + "&".join(params))
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

    def _read_status(self, device: ShellyDevice):
        component = (device.component or "relay").lower()
        channel = int(device.relay)

        if component == "switch":
            return self._request_json(device, f"/rpc/Switch.GetStatus?id={channel}")

        if component == "light":
            try:
                return self._request_json(device, f"/rpc/Light.GetStatus?id={channel}")
            except Exception:
                return self._request_json(device, f"/light/{channel}")

        if component == "rgbcct":
            return self._request_json(device, f"/rpc/RGBCCT.GetStatus?id={channel}")

        if component == "cover":
            return self._request_json(device, f"/rpc/Cover.GetStatus?id={channel}")

        try:
            return self._request_json(device, f"/relay/{channel}")
        except Exception:
            return self._request_json(device, f"/rpc/Switch.GetStatus?id={channel}")

    def _extract_state(self, device: ShellyDevice, payload: Dict[str, object]):
        component = (device.component or "relay").lower()

        if component == "cover":
            state = str(payload.get("state", "")).lower()
            if state in {"opening", "closing", "stopped", "open", "closed"}:
                return state
            position = payload.get("current_pos")
            if isinstance(position, (int, float)):
                if position <= 0:
                    return "closed"
                if position >= 100:
                    return "open"
                return "partially-open"
            return "unknown"

        is_on = bool(payload.get("ison", payload.get("output", False)))
        return "on" if is_on else "off"

    def _apply_output_action(self, device: ShellyDevice, state_value: str):
        component = (device.component or "relay").lower()
        channel = int(device.relay)

        if component == "switch":
            on_value = "true" if state_value == "on" else "false"
            self._request_json(device, f"/rpc/Switch.Set?id={channel}&on={on_value}")
            return

        if component == "light":
            try:
                on_value = "true" if state_value == "on" else "false"
                self._request_json(device, f"/rpc/Light.Set?id={channel}&on={on_value}")
            except Exception:
                self._request_json(device, f"/light/{channel}?turn={state_value}")
            return

        if component == "rgbcct":
            on_value = "true" if state_value == "on" else "false"
            self._request_json(device, f"/rpc/RGBCCT.Set?id={channel}&on={on_value}")
            return

        if component == "cover":
            pos = 100 if state_value == "on" else 0
            self._request_json(
                device, f"/rpc/Cover.GoToPosition?id={channel}&pos={pos}"
            )
            return

        self._request_json(device, f"/relay/{channel}?turn={state_value}")

    def _set_light_state(self, device: ShellyDevice, channel: int, on_value: bool):
        try:
            on_text = "true" if on_value else "false"
            self._request_json(device, f"/rpc/Light.Set?id={channel}&on={on_text}")
        except Exception:
            turn = "on" if on_value else "off"
            self._request_json(device, f"/light/{channel}?turn={turn}")

    def _set_light_brightness(
        self, device: ShellyDevice, channel: int, brightness: int
    ):
        level = int(max(0, min(100, brightness)))
        try:
            self._request_json(
                device, f"/rpc/Light.Set?id={channel}&on=true&brightness={level}"
            )
        except Exception:
            self._request_json(device, f"/light/{channel}?turn=on&brightness={level}")

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
