import unittest

from modules.agent.client import DashboardClient, DashboardError


class FakeClient(DashboardClient):
    def __init__(self):
        super().__init__()
        self.posts = []

    def _get(self, path, timeout=35):
        if path == "/api/shelly/configured":
            return [
                {
                    "id": "rgb-id-without-network-address",
                    "display_name": "RGB",
                    "component": "rgbcct",
                    "room": "Office",
                }
            ]
        if path == "/api/daikin/devices":
            return []
        if path == "/api/spotify/devices":
            return {"ok": True, "devices": []}
        raise AssertionError(path)

    def _post(self, path, payload, timeout):
        self.posts.append((path, payload, timeout))
        return {"ok": True}


class DashboardClientTests(unittest.TestCase):
    def test_rejects_non_local_dashboard_url(self):
        with self.assertRaises(ValueError):
            DashboardClient("http://example.com:5000")

    def test_catalog_exposes_opaque_token_and_capabilities(self):
        item = FakeClient().catalog()[0]
        self.assertEqual(item["token"], "S1")
        self.assertIn("rgbcct", item["capabilities"])
        self.assertNotIn("host", item)

    def test_dispatches_only_known_rgb_endpoint(self):
        client = FakeClient()
        client.execute(
            {
                "device_id": "rgb",
                "device_kind": "shelly",
                "operation": "rgbcct",
                "parameters": {"state": "on", "level": 50, "rgb": [255, 0, 0]},
            }
        )
        self.assertEqual(client.posts[0][0], "/api/shelly/rgb/rgbcct")
        self.assertEqual(client.posts[0][1]["brightness"], 50)
        with self.assertRaises(DashboardError):
            client.execute(
                {
                    "device_id": "rgb",
                    "device_kind": "shelly",
                    "operation": "arbitrary_http",
                    "parameters": {},
                }
            )

    def test_spotify_pause_omits_output_device(self):
        client = FakeClient()
        client.execute(
            {
                "device_id": "current-playback",
                "device_kind": "spotify",
                "operation": "spotify_pause",
                "parameters": {},
            }
        )
        self.assertEqual(client.posts[0], ("/api/spotify/pause", {}, 15))


if __name__ == "__main__":
    unittest.main()
