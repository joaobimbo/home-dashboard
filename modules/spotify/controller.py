import os,time,secrets
from pathlib import Path
import requests
from .auth import TokenStore
class SpotifyController:
 SCOPES='user-read-playback-state user-modify-playback-state user-read-currently-playing'
 def __init__(self):
  self.client_id=os.getenv('SPOTIFY_CLIENT_ID',''); self.secret=os.getenv('SPOTIFY_CLIENT_SECRET',''); self.redirect=os.getenv('SPOTIFY_REDIRECT_URI',''); self.store=TokenStore(os.getenv('SPOTIFY_TOKEN_FILE',str(Path.home()/'.config/home-dashboard/spotify-token.json'))); self.state=None
 @property
 def configured(self): return bool(self.client_id and self.secret and self.redirect)
 def auth_status(self): return {'ok':True,'configured':self.configured,'authenticated':bool(self.store.load().get('refresh_token'))}
 def login_url(self):
  self.state=secrets.token_urlsafe(24); return 'https://accounts.spotify.com/authorize?'+requests.compat.urlencode({'client_id':self.client_id,'response_type':'code','redirect_uri':self.redirect,'scope':self.SCOPES,'state':self.state})
 def callback(self,code,state):
  if not self.state or not secrets.compare_digest(state or '',self.state): return {'ok':False,'error':'Invalid Spotify authorization state'}
  r=requests.post('https://accounts.spotify.com/api/token',data={'grant_type':'authorization_code','code':code,'redirect_uri':self.redirect},auth=(self.client_id,self.secret),timeout=10)
  if not r.ok:return {'ok':False,'error':'Spotify authorization failed'}
  d=r.json(); d['expires_at']=time.time()+d.get('expires_in',3600); self.store.save(d); return {'ok':True}
 def _token(self):
  d=self.store.load()
  if not d.get('access_token'): raise RuntimeError('Spotify is not authenticated')
  if d.get('expires_at',0)<time.time()+60:
   r=requests.post('https://accounts.spotify.com/api/token',data={'grant_type':'refresh_token','refresh_token':d['refresh_token']},auth=(self.client_id,self.secret),timeout=10); d.update(r.json());d['expires_at']=time.time()+d.get('expires_in',3600);self.store.save(d)
  return d['access_token']
 def _api(self,method,path,**kw):
  try:r=requests.request(method,'https://api.spotify.com/v1'+path,headers={'Authorization':'Bearer '+self._token()},timeout=10,**kw)
  except (requests.RequestException,RuntimeError) as e:return {'ok':False,'error':str(e)}
  if r.status_code==429:return {'ok':False,'error':'Spotify rate limit; retry after '+r.headers.get('Retry-After','a moment')}
  if r.status_code>=400:return {'ok':False,'error':'Spotify request failed ('+str(r.status_code)+')'}
  return {'ok':True,'data':r.json() if r.content else {}}
 def devices(self):
  x=self._api('GET','/me/player/devices'); return x if not x['ok'] else {'ok':True,'devices':[{'id':d['id'],'name':d['name'],'type':d['type'],'is_active':d['is_active'],'is_restricted':d['is_restricted'],'volume_percent':d.get('volume_percent'),'supports_volume':not d['is_restricted']} for d in x['data'].get('devices',[])]}
 def status(self):
  x=self._api('GET','/me/player');
  if not x['ok']:return x
  d=x['data']; i=d.get('item') or {}; return {'ok':True,'authenticated':True,'is_playing':d.get('is_playing',False),'progress_ms':d.get('progress_ms',0),'device':d.get('device'),'track':None if not i else {'id':i.get('id'),'uri':i.get('uri'),'name':i.get('name'),'artists':[a['name'] for a in i.get('artists',[])],'album':i.get('album',{}).get('name'),'duration_ms':i.get('duration_ms'),'image':next((z['url'] for z in i.get('album',{}).get('images',[])),None)}}
 def command(self,name,payload={}):
  paths={'play':('PUT','/me/player/play'),'pause':('PUT','/me/player/pause'),'next':('POST','/me/player/next'),'previous':('POST','/me/player/previous')}; m,p=paths[name];return self._api(m,p,params={'device_id':payload.get('device_id')} if payload.get('device_id') else None)
