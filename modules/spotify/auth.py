import json, os, tempfile, time
from pathlib import Path

class TokenStore:
 def __init__(self,path): self.path=Path(path)
 def load(self):
  try: return json.loads(self.path.read_text())
  except (OSError,json.JSONDecodeError): return {}
 def save(self,data):
  self.path.parent.mkdir(parents=True,exist_ok=True); fd,tmp=tempfile.mkstemp(dir=str(self.path.parent)); os.fchmod(fd,0o600)
  with os.fdopen(fd,'w') as f: json.dump(data,f)
  os.replace(tmp,self.path)
