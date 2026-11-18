import asyncio
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

MODES = ("auto", "cool", "heat", "dry", "fan")
FAN_SPEEDS = ("auto", "low", "mid", "high")
logger = logging.getLogger(__name__)


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
        from bleak import BleakClient, BleakScanner
        from pymadoka import connection as pymadoka_connection
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
        "connection_module": pymadoka_connection,
        "discover_devices": discover_devices,
        "force_device_disconnect": force_device_disconnect,
        "BleakScanner": BleakScanner,
        "BleakClient": BleakClient,
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
        quick_scan_timeout: float = 2.0,
        ble_lock_timeout: float = 60.0,
        connect_timeout: float = 20.0,
        poll_interval: float = 120.0,
    ):
        self.devices = devices
        self._device_map: Dict[str, DaikinDevice] = {d.id: d for d in devices}
        self._config_path = config_path
        self._discover_timeout = discover_timeout
        self._quick_scan_timeout = quick_scan_timeout
        self._ble_lock_timeout = ble_lock_timeout
        # pymadoka's own connect retry loop has no timeout or max attempts -
        # if the underlying D-Bus connection to BlueZ dies mid-operation (see
        # dbus_fast EOFError/"could not shut down socket" failures), it will
        # retry forever against that same dead connection. Without a bound
        # here, that hangs madoka.start()/stop() permanently, which - since
        # this all runs under _ble_lock - would permanently lock out every
        # Daikin device until the process is restarted.
        self._connect_timeout = connect_timeout
        self._command_timeout = 12.0
        self._ble_fault = False
        # Only one BLE conversation can happen at a time - the adapter can only
        # hold one connection per peripheral and pymadoka's discovery cache is
        # a shared module-level global - so concurrent requests (e.g. from two
        # browser tabs under the threaded Flask server) must be serialized
        # here instead of racing each other.
        self._ble_lock = threading.Lock()
        self._queue_lock = threading.Lock()
        self._waiting_requests = 0
        # Bleak's BlueZ backend keeps a process-global D-Bus manager tied to
        # the asyncio loop that first used it. Creating a fresh loop with
        # asyncio.run() for every request eventually leaves that manager bound
        # to a closed loop/D-Bus connection. All BLE work is therefore sent to
        # one long-lived loop running in its own daemon thread. It is started
        # lazily so loading configuration alone (pair/debug scripts) does not
        # create an otherwise unused thread.
        self._ble_loop = None
        self._ble_loop_thread = None
        # Shared last-known-status cache, kept fresh by a single background
        # poller plus every action's own result, so browser tabs read cheap
        # in-memory state instead of each tab triggering its own BLE cycle.
        self._status_cache: Dict[str, dict] = {}
        self._status_cache_lock = threading.Lock()
        self._poll_interval = poll_interval

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
            return await self._query_status_payload(madoka)

        return self._run(device, action, "status")

    def get_cached_status(self, device_id: str):
        device = self._require_device(device_id)
        if isinstance(device, dict):
            return device

        with self._status_cache_lock:
            cached = self._status_cache.get(device_id)
        if cached is not None:
            return cached

        # Nothing polled yet (e.g. right after startup) - fall back to one
        # live read, which also populates the cache via _run() below.
        return self.get_status(device_id)

    def start_background_polling(self):
        if not self.devices:
            return

        def loop():
            while True:
                for device in self.devices:
                    try:
                        result = self.get_status(device.id)
                        if not result.get("ok") and not result.get("skipped"):
                            logger.warning(
                                "daikin_background_poll_failed device_id=%s device_name=%r error=%s",
                                device.id,
                                device.name,
                                result.get("error", "unknown error"),
                            )
                    except Exception:
                        # _run() already turns BLE failures into a normal
                        # {"ok": False, ...} result, but this thread has no
                        # supervisor to restart it - an unexpected exception
                        # here must not silently end background polling for
                        # every device forever.
                        logger.exception(
                            "daikin_background_poll_crashed device_id=%s device_name=%r",
                            device.id,
                            device.name,
                        )
                    # Let waiting user requests acquire the radio between polls.
                    time.sleep(0.1)
                time.sleep(self._poll_interval)

        thread = threading.Thread(target=loop, name="daikin-poller", daemon=True)
        thread.start()

    def set_power(self, device_id: str, on: bool):
        device = self._require_device(device_id)
        if isinstance(device, dict):
            return device

        async def action(madoka, lib):
            await madoka.power_state.update(lib["PowerStateStatus"](on))
            return await self._query_status_payload(madoka)

        return self._run(device, action, "power")

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
            return await self._query_status_payload(madoka)

        return self._run(device, action, "mode")

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
            return await self._query_status_payload(madoka)

        return self._run(device, action, "setpoint")

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
            return await self._query_status_payload(madoka)

        return self._run(device, action, "fan_speed")

    # -- internals -----------------------------------------------------

    def _require_device(self, device_id: str):
        device = self._device_map.get(device_id)
        if device is None:
            return {"ok": False, "error": "Unknown device"}
        return device

    async def _query_status_payload(self, madoka):
        power = await madoka.power_state.query()
        mode = await madoka.operation_mode.query()
        set_point = await madoka.set_point.query()
        fan = await madoka.fan_speed.query()
        temps = await madoka.temperatures.query()
        return self._status_payload(power, mode, set_point, fan, temps)

    def _status_payload(self, power, mode, set_point, fan, temps):
        active_mode = str(mode.operation_mode).lower()
        return {
            "ok": True,
            "power": bool(power.turn_on),
            "mode": active_mode,
            "setpoint": (set_point.heating_set_point if active_mode == "heat"
                         else set_point.cooling_set_point),
            "cooling_setpoint": set_point.cooling_set_point,
            "heating_setpoint": set_point.heating_set_point,
            "current_temp": temps.indoor,
            "fan_speed": str(fan.cooling_fan_speed).lower(),
        }

    def _ensure_ble_loop(self):
        if self._ble_loop_thread is not None and self._ble_loop_thread.is_alive():
            return

        loop_ready = threading.Event()

        def run_loop():
            self._ble_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._ble_loop)
            loop_ready.set()
            self._ble_loop.run_forever()

        self._ble_loop_thread = threading.Thread(target=run_loop, daemon=True)
        self._ble_loop_thread.start()
        if not loop_ready.wait(timeout=5.0):
            raise DaikinControllerError("Could not start the Daikin BLE event loop")

    def _acquire_ble_lock(self):
        # Background refreshes must not jump ahead of queued HTTP commands.
        if threading.current_thread().name == "daikin-poller":
            with self._queue_lock:
                if self._waiting_requests:
                    return False
                return self._ble_lock.acquire(blocking=False)
        with self._queue_lock:
            self._waiting_requests += 1
        try:
            return self._ble_lock.acquire(timeout=self._ble_lock_timeout)
        finally:
            with self._queue_lock:
                self._waiting_requests -= 1

    def _run(self, device: DaikinDevice, action, operation: str):
        try:
            lib = _load_pymadoka()
        except DaikinControllerError as exc:
            logger.warning(
                "daikin_operation_failed operation=%s device_id=%s device_name=%r error=%s",
                operation, device.id, device.name, exc,
            )
            return {"ok": False, "id": device.id, "name": device.name, "error": str(exc)}

        if not self._acquire_ble_lock():
            if threading.current_thread().name == "daikin-poller":
                return {"ok": False, "skipped": True, "id": device.id}
            logger.warning(
                "daikin_operation_busy operation=%s device_id=%s device_name=%r lock_timeout_seconds=%s",
                operation, device.id, device.name, self._ble_lock_timeout,
            )
            return {
                "ok": False,
                "id": device.id,
                "name": device.name,
                "error": "Daikin control is busy with another request, try again shortly",
            }

        phase = "initialization"

        async def runner():
            nonlocal phase
            phase = "disconnect before scan"
            process = await asyncio.create_subprocess_exec(
                "bluetoothctl", "--timeout", "5", "disconnect", device.address,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                await asyncio.wait_for(process.wait(), timeout=6)
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
            phase = "scan"

            # We already know the address from devices.json, so look for that
            # one device only instead of pymadoka's discover_devices(), which
            # always sleeps the full timeout scanning for everything nearby.
            # find_device_by_address() returns as soon as it sees a match.
            matched = await asyncio.wait_for(
                lib["BleakScanner"].find_device_by_address(
                    device.address, timeout=self._quick_scan_timeout, adapter=device.adapter,
                ), timeout=self._quick_scan_timeout + 3,
            )
            if matched is not None:
                lib["connection_module"].DISCOVERED_DEVICES_CACHE = [matched]
            else:
                cache = await asyncio.wait_for(
                    lib["discover_devices"](timeout=self._discover_timeout, adapter=device.adapter),
                    timeout=self._discover_timeout + 3,
                )
                matched = next(
                    (d for d in cache if d.address.upper() == device.address.upper()),
                    None,
                )

            if matched is None:
                raise DaikinControllerError("AC not found during Bluetooth scan")

            # A request owns exactly one connect/disconnect cycle. In
            # particular, disable pymadoka's retry loop: it catches a task
            # cancellation while Bleak is connecting and can otherwise keep
            # opening system-bus connections after our timeout has expired.
            madoka = lib["Controller"](
                device.address, adapter=device.adapter, reconnect=False
            )
            try:
                if matched is not None:
                    # pymadoka's own connect loop always burns a wasted first
                    # iteration (just wraps the device we already found) plus a
                    # flat 2s sleep after it. Handing it a pre-built BleakClient
                    # skips straight to the real connect attempt.
                    #
                    # Also skip pymadoka's own on_disconnect callback: it
                    # unconditionally schedules a reconnect (asyncio.create_task)
                    # on every disconnect, including our own deliberate one at
                    # the end of this request - that reconnect attempt races
                    # against our shutdown and is what produces BlueZ's
                    # "Operation already in progress" / "br-connection-canceled"
                    # errors. We manage the connect/disconnect lifecycle
                    # ourselves once per request, so auto-reconnect is unwanted.
                    madoka.connection.client = lib["BleakClient"](
                        matched,
                        adapter=device.adapter,
                        disconnected_callback=lambda _client: None,
                    )
                phase = "connect"
                # start() swallows cancellation in pymadoka's retry loop.
                # _connect() performs one attempt and honors cancellation.
                await asyncio.wait_for(
                    madoka.connection._connect(), timeout=self._connect_timeout
                )
                phase = operation + " command/readback"
                task = asyncio.create_task(action(madoka, lib))
                done, _pending = await asyncio.wait({task}, timeout=self._command_timeout)
                if not done:
                    task.cancel()
                    try:
                        await task
                    except (Exception, asyncio.CancelledError):
                        pass
                    raise DaikinControllerError("Bluetooth timed out during " + phase)
                return task.result()
            finally:
                client = madoka.connection.client
                try:
                    await asyncio.wait_for(madoka.stop(), timeout=3.0)
                except Exception:
                    # cleanup() calls stop_notify() before disconnect(). If
                    # stop_notify() fails, pymadoka never reaches disconnect
                    # and every poll leaks a Bleak system-D-Bus connection.
                    # Always make a direct disconnect attempt as a fallback.
                    if client is not None:
                        try:
                            await asyncio.wait_for(
                                client.disconnect(), timeout=3.0
                            )
                        except Exception:
                            # Bleak 0.20 has no public finalizer for a failed
                            # disconnect. Its internal cleanup is the last-resort
                            # path that closes its private D-Bus connection and
                            # removes its BlueZ watcher.
                            cleanup = getattr(client, "_cleanup_all", None)
                            if cleanup is not None:
                                try:
                                    cleanup()
                                except Exception:
                                    pass

        try:
            if self._ble_fault:
                raise DaikinControllerError("Bluetooth worker is unresponsive; restart the dashboard")
            self._ensure_ble_loop()
            future = asyncio.run_coroutine_threadsafe(runner(), self._ble_loop)
            # Last-resort watchdog: never allow a broken library to hold the
            # shared lock forever. Quarantine the radio if cancellation hangs.
            total_timeout = (20 + self._quick_scan_timeout + self._discover_timeout
                             + self._connect_timeout + 6 + self._command_timeout)
            try:
                result = future.result(timeout=total_timeout)
            except TimeoutError:
                if not future.done():
                    self._ble_fault = True
                    future.cancel()
                raise DaikinControllerError("Bluetooth timed out during " + phase)
            result["id"] = device.id
            result["name"] = device.name
            if result.get("ok"):
                # Every call funnels through here (status reads and actions
                # alike), so this single hook keeps the shared cache fresh
                # without each method having to update it separately. Only
                # successful results overwrite the cache, so one transient
                # failure doesn't blank out the last known-good state for
                # every browser tab.
                with self._status_cache_lock:
                    self._status_cache[device.id] = result
            else:
                logger.warning(
                    "daikin_operation_failed operation=%s device_id=%s device_name=%r error=%s",
                    operation, device.id, device.name, result.get("error", "unknown error"),
                )
            return result
        except Exception as exc:
            logger.exception(
                "daikin_operation_failed operation=%s device_id=%s device_name=%r error=%s",
                operation, device.id, device.name, exc,
            )
            return {
                "ok": False,
                "id": device.id,
                "name": device.name,
                "error": str(exc),
            }
        finally:
            self._ble_lock.release()
