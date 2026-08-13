import json, threading, time, uuid
from datetime import datetime
from pathlib import Path

class SpotifyScheduleStore:
 def __init__(self,controller,path): self.controller=controller;self.path=Path(path);self.lock=threading.Lock();self.rules=self._load();self.last={}
 def _load(self):
  try:return json.loads(self.path.read_text())
  except (OSError,json.JSONDecodeError):return []
 def list(self):
  with self.lock:return list(self.rules)
 def add(self,rule):
  uri=str(rule.get('uri','')); at=str(rule.get('at','')); device=str(rule.get('device_id',''))
  try:datetime.strptime(at,'%H:%M')
  except ValueError:raise ValueError('Time must use HH:MM')
  if not uri.startswith('spotify:') or not device:raise ValueError('Playlist and output are required')
  saved={'id':uuid.uuid4().hex[:10],'name':str(rule.get('name') or uri)[:80],'uri':uri,'device_id':device,'at':at,'daily':bool(rule.get('daily',True)),'date':str(rule.get('date') or '')}
  if not saved['daily']:
   datetime.strptime(saved['date'],'%Y-%m-%d')
  with self.lock:
   self.rules.append(saved);self.path.parent.mkdir(parents=True,exist_ok=True);self.path.write_text(json.dumps(self.rules,indent=2))
  return saved
 def tick(self):
  now=datetime.now();slot=now.strftime('%Y-%m-%dT%H:%M')
  for rule in self.list():
   if rule['at']!=now.strftime('%H:%M') or (not rule['daily'] and rule['date']!=now.strftime('%Y-%m-%d')) or self.last.get(rule['id'])==slot:continue
   self.last[rule['id']]=slot;self.controller.transfer(rule['device_id']);self.controller.play_uri(rule['uri'],rule['device_id'])
 def run(self):
  while True:self.tick();time.sleep(15)
