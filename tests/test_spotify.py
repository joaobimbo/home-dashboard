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
 def test_player_404_explains_that_an_output_is_needed(self):
  with mock.patch('modules.spotify.controller.requests.request',return_value=Response(404,{'error':{'message':'Player command failed: No active device found'}})): result=self.c.command('play')
  self.assertEqual(result['error'],'No active Spotify speaker. Choose an output, then try again.')
 def test_search_normalizes_track(self):
  data={'tracks':{'items':[{'name':'So What','uri':'spotify:track:1','artists':[{'name':'Miles Davis'}],'album':{'name':'Kind of Blue','images':[{'url':'cover'}]}}]},'albums':{'items':[]},'playlists':{'items':[]}}
  with mock.patch('modules.spotify.controller.requests.request',return_value=Response(200,data)): result=self.c.search('so what')
  self.assertEqual(result['results'][0]['uri'],'spotify:track:1')
 def test_playlist_query_ignores_null_search_items(self):
  data={'playlists':{'items':[None]}}
  with mock.patch('modules.spotify.controller.requests.request',return_value=Response(200,data)): result=self.c.play_playlist_query('upbeat','device')
  self.assertFalse(result['ok'])
