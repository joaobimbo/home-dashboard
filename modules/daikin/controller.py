import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

MODES = ("auto", "cool", "heat", "dry", "fan")
FAN_SPEEDS = ("auto", "low", "mid", "high")


@dataclass(frozen=True)
class DaikinDevice:
    id: str
    display_name: str
    address: str
    adapter: str = "hci0"
    room: str = "Casa"
    image: str = ""
    other_names: List[str] = field(default_factory=list)

    @property
    def name(self):
        return self.display_name


class DaikinControllerError(Exception):
    pass


def _load_pymadoka():
    try:
        from pymadoka.controller import Controller
        from pymadoka.connection import discover_devices, force_device_disconnect
        from pymadoka.features.setpoint import SetPointStatus
        from pymadoka.features.fanspeed import FanSpeedStatus, FanSpeedEnum
        from pymadoka.features.operationmode import (
            OperationModeStatus,
            OperationModeEnum,
        )
        from pymadoka.features.power import PowerStateStatus
    except ImportError as exc:
        raise DaikinControllerError(
            "pymadoka nao esta instalado. Corre `pip install pymadoka` "
            "numa maquina Linux com Bluetooth (ver AGENTS.md)."
        ) from exc

    return {
        "Controller": Controller,
        "discover_devices": discover_devices,
        "force_device_disconnect": force_device_disconnect,
        "SetPointStatus": SetPointStatus,
        "FanSpeedStatus": FanSpeedStatus,
        "FanSpeedEnum": FanSpeedEnum,
        "OperationModeStatus": OperationModeStatus,
        "OperationModeEnum": OperationModeEnum,
        "PowerStateStatus": PowerStateStatus,
    }


_MODE_TO_ENUM_NAME = {
    "auto": "AUTO",
    "cool": "COOL",
    "heat": "HEAT",
    "dry": "DRY",
    "fan": "FAN",
}

_FAN_TO_ENUM_NAME = {
    "auto": "AUTO",
    "low": "LOW",
    "mid": "MID",
    "high": "HIGH",
}


class DaikinController:
    def __init__(
        self,
        devices: List[DaikinDevice],
        config_path: Optional[str] = None,
        discover_timeout: float = 4.0,
    ):
        self.devices = devices
        self._device_map: Dict[str, DaikinDevice] = {d.id: d for d in devices}
        self._config_path = config_path
        self._discover_timeout = discover_timeout

    @classmethod
    def from_sources(cls, config_path: Optional[str] = None):
        if config_path is None:
            config_path = str(Path(__file__).resolve().parent / "devices.json")
        file_devices = cls._load_from_file(config_path)
        if file_devices:
            return cls(file_devices, config_path=config_path)

        env_devices = cls._load_from_environment()
        if env_devices:
            return cls(env_devices)

        return cls([], config_path=config_path)

    @staticmethod
    def _parse_devices(parsed):
        return [
            DaikinDevice(
                id=item["id"],
                display_name=item.get("display_name")
                or item.get("name")
                or item["id"],
                address=item["address"],
                adapter=str(item.get("adapter", "hci0")),
                room=str(item.get("room", "Casa")),
                image=str(item.get("image", "")),
                other_names=list(item.get("other_names", [])),
            )
            for item in parsed
        ]

    @classmethod
    def _load_from_file(cls, config_path: str):
        path = Path(config_path)
        if not path.exists():
            return []
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
            return cls._parse_devices(parsed)
        except (json.JSONDecodeError, KeyError, ValueError, TypeError, OSError):
            return []

    @classmethod
    def _load_from_environment(cls):
        raw_config = os.environ.get("DAIKIN_DEVICES_JSON", "").strip()
        if not raw_config:
            return []
        try:
            parsed = json.loads(raw_config)
            return cls._parse_devices(parsed)
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            return []

    def list_configured_devices(self):
        return [
            {
                "id": device.id,
                "name": device.name,
                "display_name": device.display_name,
                "address": device.address,
                "adapter": device.adapter,
                "room": device.room,
                "image": device.image,
                "other_names": device.other_names,
            }
            for device in self.devices
        ]

    # -- command entry points (sync, called from Flask) --------------------

    def get_status(self, device_id: str):
        device = self._require_device(device_id)
        if isinstance(device, dict):
            return device

        async def action(madoka, lib):
            power = await madoka.power_state.query()
            mode = await madoka.operation_mode.query()
            set_point = await madoka.set_point.query()
            fan = await madoka.fan_speed.query()
            return self._status_payload(power, mode, set_point, fan)

        return self._run(device, action)

    def set_power(self, device_id: str, on: bool):
        device = self._require_device(device_id)
        if isinstance(device, dict):
            return device

        async def action(madoka, lib):
            await madoka.power_state.update(lib["PowerStateStatus"](on))
            power = await madoka.power_state.query()
            mode = await madoka.operation_mode.query()
            set_point = await madoka.set_point.query()
            fan = await madoka.fan_speed.query()
            return self._status_payload(power, mode, set_point, fan)

        return self._run(device, action)

    def set_mode(self, device_id: str, mode: str):
        device = self._require_device(device_id)
        if isinstance(device, dict):
            return device
        if mode not in MODES:
            return {"ok": False, "error": "Invalid mode"}

        async def action(madoka, lib):
            enum_value = getattr(lib["OperationModeEnum"], _MODE_TO_ENUM_NAME[mode])
            await madoka.operation_mode.update(
                lib["OperationModeStatus"](enum_value)
            )
            power = await madoka.power_state.query()
            mode_status = await madoka.operation_mode.query()
            set_point = await madoka.set_point.query()
            fan = await madoka.fan_speed.query()
            return self._status_payload(power, mode_status, set_point, fan)

        return self._run(device, action)

    def set_setpoint(self, device_id: str, temperature: float):
        device = self._require_device(device_id)
        if isinstance(device, dict):
            return device
        target = int(round(temperature))
        if target < 10 or target > 32:
            return {"ok": False, "error": "Temperature out of range"}

        async def action(madoka, lib):
            await madoka.set_point.update(
                lib["SetPointStatus"](target, target)
            )
            power = await madoka.power_state.query()
            mode = await madoka.operation_mode.query()
            set_point = await madoka.set_point.query()
            fan = await madoka.fan_speed.query()
            return self._status_payload(power, mode, set_point, fan)

        return self._run(device, action)

    def set_fan_speed(self, device_id: str, speed: str):
        device = self._require_device(device_id)
        if isinstance(device, dict):
            return device
        if speed not in FAN_SPEEDS:
            return {"ok": False, "error": "Invalid fan speed"}

        async def action(madoka, lib):
            enum_value = getattr(lib["FanSpeedEnum"], _FAN_TO_ENUM_NAME[speed])
            await madoka.fan_speed.update(
                lib["FanSpeedStatus"](enum_value, enum_value)
            )
            power = await madoka.power_state.query()
            mode = await madoka.operation_mode.query()
            set_point = await madoka.set_point.query()
            fan = await madoka.fan_speed.query()
            return self._status_payload(power, mode, set_point, fan)

        return self._run(device, action)

    # -- internals -----------------------------------------------------

    def _require_device(self, device_id: str):
        device = self._device_map.get(device_id)
        if device is None:
            return {"ok": False, "error": "Unknown device"}
        return device

    def _status_payload(self, power, mode, set_point, fan):
        return {
            "ok": True,
            "power": bool(power.turn_on),
            "mode": str(mode.operation_mode).lower(),
            "setpoint": set_point.cooling_set_point,
            "fan_speed": str(fan.cooling_fan_speed).lower(),
        }

    def _run(self, device: DaikinDevice, action):
        try:
            lib = _load_pymadoka()
        except DaikinControllerError as exc:
            return {"ok": False, "id": device.id, "name": device.name, "error": str(exc)}

        async def runner():
            await lib["force_device_disconnect"](device.address)
            await lib["discover_devices"](
                timeout=self._discover_timeout, adapter=device.adapter
            )
            madoka = lib["Controller"](device.address, adapter=device.adapter)
            await madoka.start()
            try:
                return await action(madoka, lib)
            finally:
                await madoka.stop()

        try:
            result = asyncio.run(runner())
            result["id"] = device.id
            result["name"] = device.name
            return result
        except Exception as exc:
            return {
                "ok": False,
                "id": device.id,
                "name": device.name,
                "error": str(exc),
            }
