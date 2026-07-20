# In-memory application state + change detection.
#
# Change detection matters here specifically because e-paper redraws are slow and
# visibly flicker - refresh_shelly()/refresh_daikin() return True only when
# something in the fetched data actually differs from the last poll, so main.py can
# skip repainting (and skip the panel refresh entirely) on an unchanged poll tick.

import api_client

TAB_AC = "ac"
TAB_LIGHTS = "lights"
TAB_COVERS = "covers"


class AppState:
    def __init__(self):
        self.shelly_devices = []   # merged configured + live status, list of dicts
        self.daikin_devices = []   # merged configured + status, list of dicts
        self.weather = None
        self.online = True
        self.active_tab = None
        self.active_modal = None   # None or {"type": ..., "device_id": ...}
        self.busy_ids = set()
        self.page = 0
        self.hit_regions = []
        self._last_shelly_snapshot = {}
        self._last_daikin_snapshot = {}

    # --- tabs ---------------------------------------------------------------

    def available_tabs(self):
        tabs = []
        if self.daikin_devices:
            tabs.append(TAB_AC)
        if any(d.get("component") != "cover" for d in self.shelly_devices):
            tabs.append(TAB_LIGHTS)
        if any(d.get("component") == "cover" for d in self.shelly_devices):
            tabs.append(TAB_COVERS)
        return tabs

    def ensure_active_tab(self):
        tabs = self.available_tabs()
        if self.active_tab not in tabs:
            self.active_tab = tabs[0] if tabs else None

    def devices_for_tab(self, tab):
        if tab == TAB_AC:
            return self.daikin_devices
        if tab == TAB_COVERS:
            return [d for d in self.shelly_devices if d.get("component") == "cover"]
        if tab == TAB_LIGHTS:
            return [d for d in self.shelly_devices if d.get("component") != "cover"]
        return []

    # --- refresh + change detection -----------------------------------------

    def refresh_shelly(self):
        configured = api_client.get_shelly_configured()
        if isinstance(configured, dict) and configured.get("ok") is False:
            self.online = False
            return False
        live = api_client.get_shelly_devices()
        if isinstance(live, dict) and live.get("ok") is False:
            self.online = False
            return False

        live_by_id = dict((d["id"], d) for d in live)
        merged = []
        for cfg in configured:
            row = dict(cfg)
            row.update(live_by_id.get(cfg["id"], {}))
            merged.append(row)

        self.shelly_devices = merged
        self.online = True
        return self._diff_snapshot("_last_shelly_snapshot", merged)

    def refresh_daikin(self, live=False):
        configured = api_client.get_daikin_devices()
        if isinstance(configured, dict) and configured.get("ok") is False:
            self.online = False
            return False

        merged = []
        for cfg in configured:
            status = api_client.get_daikin_status(cfg["id"], live=live)
            row = dict(cfg)
            if status.get("ok"):
                row.update(status)
            merged.append(row)

        self.daikin_devices = merged
        self.online = True
        return self._diff_snapshot("_last_daikin_snapshot", merged)

    def refresh_weather(self):
        result = api_client.get_weather()
        if result.get("ok"):
            self.weather = result
            return True
        return False

    def _diff_snapshot(self, attr, rows):
        snapshot = dict((r["id"], _stable_repr(r)) for r in rows)
        changed = snapshot != getattr(self, attr)
        setattr(self, attr, snapshot)
        return changed

    # --- busy tracking (mirrors static/app.js's is-busy class) --------------

    def set_busy(self, device_id, busy):
        if busy:
            self.busy_ids.add(device_id)
        else:
            self.busy_ids.discard(device_id)

    def is_busy(self, device_id):
        return device_id in self.busy_ids


def _stable_repr(row):
    return tuple(sorted(row.items()))
