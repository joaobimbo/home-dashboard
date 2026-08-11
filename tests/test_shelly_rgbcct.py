import unittest
from unittest import mock

from modules.shelly.controller import ShellyController, ShellyDevice
from modules.shelly import discover


class RGBControllerTests(unittest.TestCase):
    def setUp(self):
        self.device = ShellyDevice(
            id="rgb",
            display_name="RGB",
            host="192.168.1.214",
            component="rgbcct",
            relay=0,
        )
        self.controller = ShellyController([self.device])

    def test_reads_rgbcct_status(self):
        with mock.patch.object(
            self.controller,
            "_request_json",
            return_value={
                "output": True,
                "brightness": 55,
                "mode": "rgb",
                "rgb": [255, 10, 0],
                "ct": 4000,
            },
        ) as request_json:
            result = self.controller.read_device("rgb")
        request_json.assert_called_once_with(
            self.device, "/rpc/RGBCCT.GetStatus?id=0"
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "on")
        self.assertEqual(result["rgb"], [255, 10, 0])
        self.assertEqual(result["color_temp"], 4000)

    def test_validates_and_sets_rgbcct(self):
        with mock.patch.object(
            self.controller,
            "_request_json",
            side_effect=[{}, {"output": True, "brightness": 60, "mode": "rgb", "rgb": [255, 0, 0]}],
        ) as request_json:
            result = self.controller.set_rgbcct(
                "rgb", {"on": True, "brightness": 60, "mode": "rgb", "rgb": [255, 0, 0]}
            )
        self.assertTrue(result["ok"])
        self.assertIn("/rpc/RGBCCT.Set?id=0&on=true&brightness=60&mode=rgb&rgb=[255,0,0]", request_json.call_args_list[0].args[1])
        self.assertFalse(self.controller.set_rgbcct("rgb", {"rgb": [300, 0, 0]})["ok"])


class RGBDiscoveryTests(unittest.TestCase):
    def test_discovers_rgbcct_component(self):
        def fake_http(url, _timeout):
            if url.endswith("/shelly"):
                raise RuntimeError("not gen1")
            if url.endswith("Shelly.GetDeviceInfo"):
                return {"model": "S3BL-C010007AEU"}
            if url.endswith("Shelly.GetConfig"):
                return {"device": {"name": "RGB"}, "rgbcct:0": {"name": "Bulb"}}
            raise AssertionError(url)

        connection = mock.MagicMock()
        connection.__enter__.return_value = connection
        with mock.patch("modules.shelly.discover.socket.create_connection", return_value=connection), mock.patch(
            "modules.shelly.discover.http_json", side_effect=fake_http
        ):
            result = discover.probe_host("192.168.1.214", 1.0)
        self.assertEqual(result["entries"][0]["component"], "rgbcct")
        self.assertEqual(result["entries"][0]["relay"], 0)


if __name__ == "__main__":
    unittest.main()
