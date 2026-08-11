"""Strict localhost-only client for the existing dashboard APIs."""

import json
from typing import Dict, List, Optional
from urllib import error, parse, request


class DashboardError(RuntimeError):
    pass


class DashboardClient:
    def __init__(self, base_url: str = "http://127.0.0.1:5000"):
        parsed = parse.urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Dashboard URL must use HTTP on the local host")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Invalid dashboard URL")
        self.base_url = base_url.rstrip("/")

    def catalog(self) -> List[Dict[str, object]]:
        shelly = self._get("/api/shelly/configured")
        daikin = self._get("/api/daikin/devices")
        if not isinstance(shelly, list) or not isinstance(daikin, list):
            raise DashboardError("Dashboard returned an invalid device catalog")

        result: List[Dict[str, object]] = []
        for index, device in enumerate(sorted(shelly, key=lambda item: str(item.get("id"))), 1):
            component = str(device.get("component") or "relay").lower()
            capabilities = {
                "relay": ["status", "power", "toggle"],
                "switch": ["status", "power", "toggle"],
                "light": ["status", "power", "toggle", "brightness"],
                "cover": ["status", "cover", "position"],
                "rgbcct": ["status", "power", "toggle", "rgbcct"],
            }.get(component, ["status"])
            result.append(
                {
                    "token": f"S{index}",
                    "id": str(device["id"]),
                    "kind": "shelly",
                    "component": component,
                    "display_name": str(device.get("display_name") or device.get("name") or device["id"]),
                    "other_names": list(device.get("other_names") or []),
                    "room": str(device.get("room") or "Casa"),
                    "capabilities": capabilities,
                }
            )
        for index, device in enumerate(sorted(daikin, key=lambda item: str(item.get("id"))), 1):
            result.append(
                {
                    "token": f"A{index}",
                    "id": str(device["id"]),
                    "kind": "daikin",
                    "component": "ac",
                    "display_name": str(device.get("display_name") or device.get("name") or device["id"]),
                    "other_names": list(device.get("other_names") or []),
                    "room": str(device.get("room") or "Casa"),
                    "capabilities": ["status", "power", "ac_mode", "ac_setpoint", "ac_fan"],
                }
            )
        return result

    def snapshot(self, include_weather: bool = True) -> Dict[str, object]:
        devices: Dict[str, Dict[str, object]] = {}
        shelly = self._get("/api/shelly/devices")
        if isinstance(shelly, list):
            for item in shelly:
                if isinstance(item, dict) and item.get("id"):
                    devices[str(item["id"])] = dict(item)

        daikin = self._get("/api/daikin/devices")
        if isinstance(daikin, list):
            for item in daikin:
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                device_id = str(item["id"])
                try:
                    status = self._get(f"/api/daikin/{parse.quote(device_id)}/status")
                except DashboardError as exc:
                    status = {"ok": False, "error": str(exc), "id": device_id}
                if isinstance(status, dict):
                    devices[device_id] = status

        weather: Optional[Dict[str, object]] = None
        if include_weather:
            try:
                payload = self._get("/api/weather")
                weather = payload if isinstance(payload, dict) else None
            except DashboardError:
                weather = None
        return {"devices": devices, "weather": weather}

    def weather(self) -> Optional[Dict[str, object]]:
        try:
            payload = self._get("/api/weather")
        except DashboardError:
            return None
        return payload if isinstance(payload, dict) and payload.get("ok") else None

    def execute(self, action: Dict[str, object]) -> Dict[str, object]:
        device_id = parse.quote(str(action["device_id"]), safe="")
        kind = action["device_kind"]
        operation = action["operation"]
        params = dict(action.get("parameters") or {})

        if operation == "status":
            snapshot = self.snapshot(include_weather=False)
            status = snapshot["devices"].get(str(action["device_id"]))
            if not isinstance(status, dict):
                raise DashboardError("Device status is unavailable")
            return status

        if kind == "shelly":
            if operation in {"power", "toggle"}:
                command = params.get("state") if operation == "power" else "toggle"
                return self._post(f"/api/shelly/{device_id}/action", {"action": command}, timeout=15)
            if operation == "brightness":
                return self._post(
                    f"/api/shelly/{device_id}/light_level",
                    {"brightness": params["level"]},
                    timeout=15,
                )
            if operation == "cover":
                return self._post(
                    f"/api/shelly/{device_id}/cover_action",
                    {"command": params["command"]},
                    timeout=15,
                )
            if operation == "position":
                return self._post(
                    f"/api/shelly/{device_id}/position",
                    {"position": params["position"]},
                    timeout=15,
                )
            if operation == "rgbcct":
                payload: Dict[str, object] = {}
                if "state" in params:
                    payload["on"] = params["state"] == "on"
                if "level" in params:
                    payload["brightness"] = params["level"]
                if "mode" in params:
                    payload["mode"] = params["mode"]
                if "rgb" in params:
                    payload["rgb"] = params["rgb"]
                if "color_temp" in params:
                    payload["color_temp"] = params["color_temp"]
                return self._post(f"/api/shelly/{device_id}/rgbcct", payload, timeout=15)

        if kind == "daikin":
            if operation == "power":
                return self._post(
                    f"/api/daikin/{device_id}/power",
                    {"state": params["state"]},
                    timeout=45,
                )
            if operation == "ac_mode":
                return self._post(
                    f"/api/daikin/{device_id}/mode",
                    {"mode": params["mode"]},
                    timeout=45,
                )
            if operation == "ac_setpoint":
                return self._post(
                    f"/api/daikin/{device_id}/setpoint",
                    {"temperature": params["temperature"]},
                    timeout=45,
                )
            if operation == "ac_fan":
                return self._post(
                    f"/api/daikin/{device_id}/fan",
                    {"speed": params["speed"]},
                    timeout=45,
                )
        raise DashboardError("Action is not supported by the dashboard client")

    def _get(self, path: str, timeout: int = 35):
        req = request.Request(self.base_url + path, method="GET")
        return self._open_json(req, timeout)

    def _post(self, path: str, payload: Dict[str, object], timeout: int):
        req = request.Request(
            self.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        result = self._open_json(req, timeout)
        if not isinstance(result, dict) or not result.get("ok"):
            message = result.get("error") if isinstance(result, dict) else None
            raise DashboardError(str(message or "Dashboard action failed"))
        return result

    @staticmethod
    def _open_json(req: request.Request, timeout: int):
        try:
            with request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
                message = payload.get("error") if isinstance(payload, dict) else None
            except Exception:
                message = None
            raise DashboardError(str(message or f"Dashboard HTTP {exc.code}")) from exc
        except (error.URLError, json.JSONDecodeError, TimeoutError) as exc:
            raise DashboardError(f"Dashboard unavailable: {exc}") from exc
