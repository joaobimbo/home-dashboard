"""Server-side Spotify Connect and OAuth controller."""
import os
import secrets
import time
from pathlib import Path

import requests

from .auth import TokenStore


class SpotifyController:
    API = "https://api.spotify.com/v1"
    TOKEN_URL = "https://accounts.spotify.com/api/token"
    AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
    SCOPES = "user-read-playback-state user-modify-playback-state user-read-currently-playing"

    def __init__(self):
        self.client_id = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
        self.client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "").strip()
        self.redirect_uri = os.environ.get("SPOTIFY_REDIRECT_URI", "").strip()
        path = os.environ.get("SPOTIFY_TOKEN_FILE", str(Path.home() / ".config/home-dashboard/spotify-token.json"))
        self.store = TokenStore(path)
        self._state = None

    @property
    def configured(self):
        return bool(self.client_id and self.client_secret and self.redirect_uri)

    def auth_status(self):
        token = self.store.load()
        return {"ok": True, "configured": self.configured, "authenticated": bool(token.get("refresh_token"))}

    def login_url(self):
        self._state = secrets.token_urlsafe(24)
        return self.AUTHORIZE_URL + "?" + requests.compat.urlencode({
            "client_id": self.client_id, "response_type": "code", "redirect_uri": self.redirect_uri,
            "scope": self.SCOPES, "state": self._state,
        })

    def callback(self, code, state):
        if not self._state or not secrets.compare_digest(str(state or ""), self._state):
            return {"ok": False, "error": "Invalid Spotify authorization state"}
        return self._save_token({"grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri})

    def _save_token(self, form):
        try:
            response = requests.post(self.TOKEN_URL, data=form, auth=(self.client_id, self.client_secret), timeout=10)
            data = response.json() if response.content else {}
        except (requests.RequestException, ValueError):
            return {"ok": False, "error": "Spotify authorization is unavailable"}
        if not response.ok or not data.get("access_token"):
            return {"ok": False, "error": "Spotify authorization failed"}
        old = self.store.load()
        if not data.get("refresh_token"):
            data["refresh_token"] = old.get("refresh_token")
        data["expires_at"] = time.time() + int(data.get("expires_in", 3600))
        self.store.save(data)
        return {"ok": True}

    def _token(self):
        data = self.store.load()
        if not data.get("access_token"):
            raise RuntimeError("Spotify is not authenticated")
        if float(data.get("expires_at", 0)) < time.time() + 60:
            result = self._save_token({"grant_type": "refresh_token", "refresh_token": data.get("refresh_token", "")})
            if not result["ok"]:
                raise RuntimeError(result["error"])
            data = self.store.load()
        return data["access_token"]

    def _api(self, method, path, **kwargs):
        if not self.configured:
            return {"ok": False, "error": "Spotify is not configured"}
        try:
            response = requests.request(method, self.API + path, headers={"Authorization": "Bearer " + self._token()}, timeout=10, **kwargs)
        except (requests.RequestException, RuntimeError):
            return {"ok": False, "error": "Spotify is unavailable or not authenticated"}
        error_data = {}
        if response.status_code >= 400:
            try:
                error_data = response.json() if response.content else {}
            except ValueError:
                error_data = {}
        if response.status_code == 429:
            return {"ok": False, "error": "Spotify rate limit; try again in " + response.headers.get("Retry-After", "a moment") + " seconds"}
        if response.status_code == 401:
            return {"ok": False, "error": "Spotify authentication expired; sign in again"}
        if response.status_code == 403:
            return {"ok": False, "error": "Spotify denied this playback request"}
        if response.status_code == 404 and path.startswith("/me/player"):
            message = error_data.get("error", {}).get("message", "") if isinstance(error_data, dict) else ""
            if "device" in message.lower() or not message:
                return {"ok": False, "error": "No active Spotify speaker. Choose an output, then try again."}
        if response.status_code >= 400:
            return {"ok": False, "error": "Spotify request failed (" + str(response.status_code) + ")"}
        try:
            return {"ok": True, "data": response.json() if response.content else {}}
        except ValueError:
            return {"ok": False, "error": "Spotify returned an invalid response"}

    @staticmethod
    def _device(device):
        if not isinstance(device, dict): return None
        return {"id": device.get("id"), "name": device.get("name"), "type": device.get("type"), "is_active": bool(device.get("is_active")), "is_restricted": bool(device.get("is_restricted")), "volume_percent": device.get("volume_percent"), "supports_volume": not bool(device.get("is_restricted")) and device.get("volume_percent") is not None}

    def devices(self):
        result = self._api("GET", "/me/player/devices")
        return result if not result["ok"] else {"ok": True, "devices": [self._device(item) for item in result["data"].get("devices", []) if item.get("id")]}

    def status(self):
        result = self._api("GET", "/me/player")
        if not result["ok"]: return result
        data = result["data"]
        if not data: return {"ok": True, "authenticated": True, "is_playing": False, "device": None, "track": None}
        item = data.get("item") or {}; album = item.get("album") or {}
        return {"ok": True, "authenticated": True, "is_playing": bool(data.get("is_playing")), "progress_ms": data.get("progress_ms", 0), "device": self._device(data.get("device")), "track": None if not item else {"id": item.get("id"), "uri": item.get("uri"), "name": item.get("name"), "artists": [artist.get("name") for artist in item.get("artists", [])], "album": album.get("name"), "duration_ms": item.get("duration_ms"), "image": next((image.get("url") for image in album.get("images", []) if image.get("url")), None)}}

    def command(self, name, payload=None):
        payload = payload or {}; device_id = payload.get("device_id")
        paths = {"play": ("PUT", "/me/player/play"), "pause": ("PUT", "/me/player/pause"), "next": ("POST", "/me/player/next"), "previous": ("POST", "/me/player/previous")}
        method, path = paths[name]
        return self._api(method, path, params={"device_id": device_id} if device_id else None)

    def transfer(self, device_id, play=False):
        if not isinstance(device_id, str) or not device_id: return {"ok": False, "error": "A Spotify device is required"}
        body = {"device_ids": [device_id]}
        if play: body["play"] = True
        return self._api("PUT", "/me/player", json=body)

    def volume(self, volume, device_id=None):
        if type(volume) is not int or not 0 <= volume <= 100: return {"ok": False, "error": "Volume must be between 0 and 100"}
        params = {"volume_percent": volume}
        if device_id: params["device_id"] = device_id
        return self._api("PUT", "/me/player/volume", params=params)

    def play_uri(self, uri, device_id=None):
        if not isinstance(uri, str) or not uri.startswith("spotify:"): return {"ok": False, "error": "Invalid Spotify URI"}
        kind = uri.split(":", 2)[1] if uri.count(":") >= 2 else ""
        body = {"uris": [uri]} if kind == "track" else {"context_uri": uri} if kind in {"album", "playlist"} else None
        if body is None: return {"ok": False, "error": "Only Spotify tracks, albums, and playlists are supported"}
        return self._api("PUT", "/me/player/play", params={"device_id": device_id} if device_id else None, json=body)

    def play_playlist_query(self, query, device_id=None):
        if not isinstance(query, str) or not query.strip(): return {"ok": False, "error": "A playlist name is required"}
        result = self._api("GET", "/search", params={"q": query.strip(), "type": "playlist", "limit": 1})
        if not result["ok"]: return result
        items = result["data"].get("playlists", {}).get("items", [])
        playlist = next((item for item in items if isinstance(item, dict) and item.get("uri")), None)
        if not playlist: return {"ok": False, "error": "Spotify could not find an available playlist with that name"}
        return self.play_uri(playlist["uri"], device_id)

    def search(self, query):
        if not isinstance(query, str) or not query.strip(): return {"ok": False, "error": "Enter something to search for"}
        result = self._api("GET", "/search", params={"q": query.strip(), "type": "track,album,playlist", "limit": 5})
        if not result["ok"]: return result
        results = []
        for kind, key in (("track", "tracks"), ("album", "albums"), ("playlist", "playlists")):
            for item in result["data"].get(key, {}).get("items", []):
                if not item or not item.get("uri"): continue
                album = item.get("album") or {}; images = item.get("images") or album.get("images") or []
                artists = item.get("artists") or []
                subtitle = " · ".join(artist.get("name", "") for artist in artists) or (item.get("owner") or {}).get("display_name", "")
                if kind == "track" and album.get("name"): subtitle += " — " + album["name"]
                results.append({"type": kind, "name": item.get("name", "Spotify"), "subtitle": subtitle, "uri": item["uri"], "image": next((image.get("url") for image in images if image.get("url")), None)})
        return {"ok": True, "results": results}
