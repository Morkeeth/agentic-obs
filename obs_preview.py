"""Bounded local OBS preview setup. No broadcast/record methods are exposed."""
import base64,hashlib,json,uuid
from pathlib import Path
import websocket
ROOT=Path(__file__).resolve().parent
COLLECTION='Agentic OBS Preview 27Oct'
PROFILE=COLLECTION
SCENE='Agentic OBS Audio Preview'
SOURCE='Agentic OBS Loopback Display'
URL='http://127.0.0.1:8876/overlay.html'
class Preview:
 def __init__(self):
  cfg=json.loads((ROOT/'.obs-private.json').read_text())
  if cfg.get('authrequired')!='true' or cfg.get('serverport')!='4455':raise ValueError('Expected authenticated local OBS target')
  self.ws=websocket.create_connection('ws://127.0.0.1:4455',timeout=10)
  hello=json.loads(self.ws.recv());auth=hello['d']['authentication']
  enc=lambda s:base64.b64encode(hashlib.sha256(s.encode()).digest()).decode()
  self.ws.send(json.dumps({'op':1,'d':{'rpcVersion':1,'eventSubscriptions':0,'authentication':enc(enc(cfg['serverpassword']+auth['salt'])+auth['challenge'])}}))
  if json.loads(self.ws.recv()).get('op')!=2:raise ValueError('OBS authentication failed')
 def request(self,kind,data=None):
  allowed={'GetVersion','GetSceneCollectionList','GetProfileList','GetSceneList','GetStreamStatus','GetRecordStatus','GetStudioModeEnabled','GetVideoSettings','GetInputSettings','CreateSceneCollection','CreateProfile','CreateScene','CreateInput','SetCurrentPreviewScene','GetSceneItemList'}
  if kind not in allowed:raise ValueError('OBS method outside preview capability')
  if kind.startswith('Create') or kind=='SetCurrentPreviewScene':
   if self.request('GetStreamStatus')['outputActive'] or self.request('GetRecordStatus')['outputActive']:raise ValueError('OBS output active; refusing preview setup')
   want={'CreateSceneCollection':{'sceneCollectionName':COLLECTION},'CreateProfile':{'profileName':PROFILE},'CreateScene':{'sceneName':SCENE},'SetCurrentPreviewScene':{'sceneName':SCENE},'CreateInput':{'sceneName':SCENE,'inputName':SOURCE,'inputKind':'browser_source','inputSettings':{'url':URL,'width':1920,'height':1080,'shutdown':False},'sceneItemEnabled':True}}[kind]
   if data!=want:raise ValueError('Only fixed owned preview objects may be created')
  rid=str(uuid.uuid4());self.ws.send(json.dumps({'op':6,'d':{'requestType':kind,'requestId':rid,'requestData':data or {}}}))
  while True:
   r=json.loads(self.ws.recv())
   if r.get('op')==7 and r['d']['requestId']==rid:
    if not r['d']['requestStatus']['result']:raise ValueError(kind+': '+r['d']['requestStatus'].get('comment','failed'))
    return r['d'].get('responseData',{})
 def snapshot(self):
  return {k:self.request(k) for k in ['GetVersion','GetSceneCollectionList','GetProfileList','GetSceneList','GetStreamStatus','GetRecordStatus','GetStudioModeEnabled','GetVideoSettings']}
 def setup(self):
  self.request('CreateProfile',{'profileName':PROFILE})
  self.request('CreateSceneCollection',{'sceneCollectionName':COLLECTION})
  self.request('CreateScene',{'sceneName':SCENE})
  self.request('CreateInput',{'sceneName':SCENE,'inputName':SOURCE,'inputKind':'browser_source','inputSettings':{'url':URL,'width':1920,'height':1080,'shutdown':False},'sceneItemEnabled':True})
  self.request('SetCurrentPreviewScene',{'sceneName':SCENE})
if __name__=='__main__':
 import sys
 p=Preview();folder=Path(sys.argv[2]);folder.mkdir(exist_ok=True)
 if sys.argv[1]=='snapshot':(folder/'OBS-BEFORE-API.json').write_text(json.dumps(p.snapshot(),indent=2))
 elif sys.argv[1]=='setup':
  p.setup();(folder/'OBS-OWNED-PREVIEW.json').write_text(json.dumps(p.snapshot(),indent=2))
 else:raise ValueError('Expected snapshot or setup')
 print('OBS bounded preview command complete')

def preview_source_status():
 p=Preview()
 try:
  current=p.request('GetSceneCollectionList')['currentSceneCollectionName']
  if current!=COLLECTION:raise ValueError('Owned preview collection is not current; no OBS action taken')
  settings=p.request('GetInputSettings',{'inputName':SOURCE})
  if settings.get('inputSettings',{}).get('url')!=URL:raise ValueError('Owned browser source is not pinned to the loopback display')
  return {'connected':True,'collection':COLLECTION,'scene':SCENE,'source':SOURCE,'url':URL,'stream_active':p.request('GetStreamStatus')['outputActive'],'record_active':p.request('GetRecordStatus')['outputActive'],'mutations':False}
 finally:p.ws.close()
