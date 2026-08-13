import os, tempfile, unittest
from unittest import mock
from modules.spotify.controller import SpotifyController

class Response:
 def __init__(self,status=204,data=None,headers=None): self.status_code=status;self._data=data or {};self.content=b'x' if data is not None else b'';self.headers=headers or {};self.ok=status<400
 def json(self): return self._data

class SpotifyTests(unittest.TestCase):
 def setUp(self):
  self.env=mock.patch.dict(os.environ,{'SPOTIFY_CLIENT_ID':'id','SPOTIFY_CLIENT_SECRET':'secret','SPOTIFY_REDIRECT_URI':'http://127.0.0.1/callback','SPOTIFY_TOKEN_FILE':tempfile.mktemp()},clear=False);self.env.start();self.c=SpotifyController();self.c.store.save({'access_token':'token','refresh_token':'refresh','expires_at':9999999999})
 def tearDown(self): self.env.stop()
 def test_transfer_has_one_device(self):
  with mock.patch('modules.spotify.controller.requests.request',return_value=Response()) as call:self.assertTrue(self.c.transfer('device')['ok']);self.assertEqual(call.call_args.kwargs['json'],{'device_ids':['device']})
 def test_volume_validation(self): self.assertFalse(self.c.volume(101)['ok'])
 def test_no_playback(self):
  with mock.patch('modules.spotify.controller.requests.request',return_value=Response(200,{})): self.assertIsNone(self.c.status()['track'])
 def test_rate_limit(self):
  with mock.patch('modules.spotify.controller.requests.request',return_value=Response(429,headers={'Retry-After':'12'})): self.assertIn('12',self.c.devices()['error'])
