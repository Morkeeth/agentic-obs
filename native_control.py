"""Owned OBS preview scenes and transform presets; no broadcast capability."""
import base64,hashlib,json,os,re,threading,time,uuid
from pathlib import Path
import websocket
ROOT=Path(__file__).resolve().parent
PORT=8878; TAG='native-program-27oct'
COLLECTION='Agentic OBS Program 27Oct'; PROFILE=COLLECTION
SCENES={k:'Agentic Live '+k.title() for k in ['speaker','focus','break']}
SOURCES={k:'Agentic Live Display '+k.title() for k in SCENES}
URLS={k:f'http://127.0.0.1:8878/scene-{k}.html' for k in SCENES}
STORE=ROOT/'.native-presets.json';LOCK=threading.RLock();PAUSED=False;UNDO=None
PROGRAM_ENABLED=False;SESSION_ID=str(uuid.uuid4());PROGRAM_BINDING=None

def parse(prompt):
 if not isinstance(prompt,str) or len(prompt)>240:raise ValueError('Use a short native preview command')
 t=prompt.strip().rstrip('.!?').strip()
 m=re.fullmatch(r'(preview|program) (speaker|focus|break)',t,re.I)
 if m:return {'action':'scene','target':m[1].lower(),'scene':m[2].lower()}
 m=re.fullmatch(r'save preset ([a-z][a-z0-9 _-]{0,39}) with (slide left|slide right|lift|pulse) (\d+)ms',t,re.I)
 if m:
  duration=int(m[3])
  if not 200<=duration<=2000:raise ValueError('Animation duration must be200–2000ms')
  return {'action':'save','name':m[1].lower().strip(),'motion':m[2].lower(),'duration_ms':duration}
 m=re.fullmatch(r'play (program )?preset ([a-z][a-z0-9 _-]{0,39})',t,re.I)
 if m:return {'action':'play','target':'program' if m[1] else 'preview','name':m[2].lower().strip()}
 if t.lower() in ['undo preview','undo program','pause native','resume native']:
  return {'action':{'undo preview':'undo','undo program':'undo_program','pause native':'pause','resume native':'resume'}[t.lower()]}
 raise ValueError('Use preview speaker/focus/break; save preset NAME with slide left/slide right/lift/pulse 500ms; play preset NAME; undo preview; pause native; resume native')

def presets():
 if not STORE.exists():return {}
 data=json.loads(STORE.read_text())
 if not isinstance(data,dict):raise ValueError('Invalid local preset file')
 return data

class Native:
 def __init__(self,setup=False):
  if os.environ.get('AGENTIC_OBS_PORT')!='8878':raise ValueError('Native connector requires explicit target8878')
  cfg=json.loads((ROOT/'.obs-private.json').read_text())
  if cfg.get('authrequired')!='true' or cfg.get('serverport')!='4455':raise ValueError('Expected authenticated OBS4455')
  self.ws=websocket.create_connection('ws://127.0.0.1:4455',timeout=10)
  auth=json.loads(self.ws.recv())['d']['authentication'];enc=lambda s:base64.b64encode(hashlib.sha256(s.encode()).digest()).decode()
  self.ws.send(json.dumps({'op':1,'d':{'rpcVersion':1,'eventSubscriptions':0,'authentication':enc(enc(cfg['serverpassword']+auth['salt'])+auth['challenge'])}}))
  if json.loads(self.ws.recv()).get('op')!=2:raise ValueError('OBS authentication failed')
  self.setting_up=False
  if not setup:
   try:self.guard()
   except Exception:self.close();raise
 def close(self):self.ws.close()
 def req(self,kind,data=None):
  readonly={'GetSceneCollectionList','GetProfileList','GetSceneList','GetStreamStatus','GetRecordStatus','GetVirtualCamStatus','GetStudioModeEnabled','GetInputSettings','GetSceneItemId','GetSceneItemTransform'}
  changes={'SetCurrentPreviewScene','SetCurrentProgramScene','SetSceneItemTransform'}
  creates={'CreateProfile','CreateSceneCollection','CreateScene','CreateInput'}
  data=data or {}
  if kind not in readonly|changes|creates:raise ValueError('Outside native preview capability')
  if kind in creates:
   expected={'CreateProfile':[{'profileName':PROFILE}], 'CreateSceneCollection':[{'sceneCollectionName':COLLECTION}], 'CreateScene':[{'sceneName':v} for v in SCENES.values()], 'CreateInput':[{'sceneName':SCENES[k],'inputName':SOURCES[k],'inputKind':'browser_source','inputSettings':{'url':URLS[k],'width':1920,'height':1080,'shutdown':False},'sceneItemEnabled':True} for k in SCENES]}
   if data not in expected[kind]:raise ValueError('Only exact owned setup objects may be created')
  if kind in changes|creates:
   if kind in creates:self.outputs_off()
   else:self.permission(program=kind=='SetCurrentProgramScene')
   if kind in changes or kind in ['CreateScene','CreateInput']:self.guard()
   if kind in ['SetCurrentPreviewScene','SetCurrentProgramScene']:
    if data.get('sceneName') not in SCENES.values():raise ValueError('Unowned target scene')
    key=next(k for k,v in SCENES.items() if v==data['sceneName']);self.source_guard(key)
   if kind=='SetSceneItemTransform':
    if data.get('sceneName') not in SCENES.values():raise ValueError('Unowned transform scene')
    key=next(k for k,v in SCENES.items() if v==data['sceneName'])
    if self.req('GetSceneList')['currentProgramSceneName']==SCENES[key]:self.permission(program=True)
    self.source_guard(key)
    if data.get('sceneItemId')!=self.item(key):raise ValueError('Unowned transform source')
    allowed={'positionX','positionY','scaleX','scaleY'};v=data.get('sceneItemTransform',{})
    if not v or set(v)-allowed:raise ValueError('Unsupported native transform')
    if any(type(x) not in [float,int] for x in v.values()):raise ValueError('Transform must be numeric')
    if any(not -400<=v.get(k,0)<=400 for k in ['positionX','positionY']) or any(not .5<=v.get(k,1)<=1.2 for k in ['scaleX','scaleY']):raise ValueError('Transform outside preview bounds')
  rid=str(uuid.uuid4());self.ws.send(json.dumps({'op':6,'d':{'requestType':kind,'requestId':rid,'requestData':data}}))
  while True:
   out=json.loads(self.ws.recv())
   if out.get('op')==7 and out['d']['requestId']==rid:
    if not out['d']['requestStatus']['result']:raise ValueError(kind+' failed: '+out['d']['requestStatus'].get('comment',''))
    return out['d'].get('responseData',{})
 def source_guard(self,key):
  global PROGRAM_ENABLED,PROGRAM_BINDING
  try:
   settings=self.req('GetInputSettings',{'inputName':SOURCES[key]})
   if settings.get('inputKind')!='browser_source' or settings.get('inputSettings',{}).get('url')!=URLS[key]:raise ValueError('Owned source identity changed')
   self.item(key)
  except ValueError:
   PROGRAM_ENABLED=False;PROGRAM_BINDING=None
   raise
 def permission(self,program=False):
  self.guard()
  active=any(self.req(k)['outputActive'] for k in ['GetStreamStatus','GetRecordStatus','GetVirtualCamStatus'])
  if self.setting_up:
   if active:raise ValueError('Setup requires outputs off')
   return
  if program or active:
   if not PROGRAM_ENABLED or PROGRAM_BINDING!=(PROFILE,COLLECTION,SESSION_ID):raise ValueError('Program control is off; explicitly enable this session')
   if self.req('GetSceneList')['currentProgramSceneName'] not in SCENES.values():raise ValueError('Current program scene is not owned')
 def outputs_off(self):
  if any(self.req(k)['outputActive'] for k in ['GetStreamStatus','GetRecordStatus','GetVirtualCamStatus']):raise ValueError('Output active; preview mutation refused')
 def guard(self):
  global PROGRAM_ENABLED,PROGRAM_BINDING
  if self.req('GetSceneCollectionList')['currentSceneCollectionName']!=COLLECTION or self.req('GetProfileList')['currentProfileName']!=PROFILE:
   PROGRAM_ENABLED=False;PROGRAM_BINDING=None
   raise ValueError('Owned program profile and collection must be selected')
  if not self.req('GetStudioModeEnabled')['studioModeEnabled']:raise ValueError('Studio Mode required; no program changes')
 def item(self,key):return self.req('GetSceneItemId',{'sceneName':SCENES[key],'sourceName':SOURCES[key]})['sceneItemId']
 def transform(self,key):return self.req('GetSceneItemTransform',{'sceneName':SCENES[key],'sceneItemId':self.item(key)})['sceneItemTransform']
 def set_transform(self,key,t):
  self.req('SetSceneItemTransform',{'sceneName':SCENES[key],'sceneItemId':self.item(key),'sceneItemTransform':{k:t[k] for k in ['positionX','positionY','scaleX','scaleY']}})
 def snapshot(self):
  scene=self.req('GetSceneList');return {'profile':self.req('GetProfileList')['currentProfileName'],'collection':self.req('GetSceneCollectionList')['currentSceneCollectionName'],'preview':scene['currentPreviewSceneName'],'program':scene['currentProgramSceneName'],'streaming':self.req('GetStreamStatus')['outputActive'],'recording':self.req('GetRecordStatus')['outputActive'],'virtual_camera':self.req('GetVirtualCamStatus')['outputActive'],'studio_mode':self.req('GetStudioModeEnabled')['studioModeEnabled']}
 def setup(self):
  self.setting_up=True
  self.outputs_off()
  self.req('CreateProfile',{'profileName':PROFILE});self.req('CreateSceneCollection',{'sceneCollectionName':COLLECTION})
  self.guard()
  for key,name in SCENES.items():
   self.req('CreateScene',{'sceneName':name})
   self.req('CreateInput',{'sceneName':name,'inputName':SOURCES[key],'inputKind':'browser_source','inputSettings':{'url':URLS[key],'width':1920,'height':1080,'shutdown':False},'sceneItemEnabled':True})
  self.req('SetCurrentPreviewScene',{'sceneName':SCENES['speaker']})
  self.req('SetCurrentProgramScene',{'sceneName':SCENES['speaker']})
  self.setting_up=False

def execute(prompt):
 global PAUSED,UNDO
 command=parse(prompt)
 with LOCK:
  kind=command['action']
  if kind in ['pause','resume']:PAUSED=kind=='pause';return {'outcome':'paused' if PAUSED else 'resumed','command':command}
  if kind=='save':
   data=presets();data[command['name']]={k:command[k] for k in ['motion','duration_ms']}
   temp=STORE.with_suffix('.tmp');temp.write_text(json.dumps(data,indent=2));temp.chmod(0o600);temp.replace(STORE)
   return {'outcome':'preset saved on disk','preset':command['name'],'definition':data[command['name']]}
  if PAUSED:return {'outcome':'native paused; OBS unchanged','command':command}
  n=Native();samples=[]
  try:
   n.permission(program=command.get('target')=='program' or kind=='undo_program');before=n.snapshot()
   if kind=='scene':
    key=command['scene'];target=command['target'];UNDO={'target':target,'scene':before[target],'transforms':{key:n.transform(key)}}
    # A real native scene uses its own source geometry; this is not just CSS layout.
    scale=1.0
    n.set_transform(key,{'positionX':0,'positionY':0,'scaleX':scale,'scaleY':scale})
    n.req('SetCurrentProgramScene' if target=='program' else 'SetCurrentPreviewScene',{'sceneName':SCENES[key]})
   elif kind=='play':
    saved=presets().get(command['name'])
    if not saved:raise ValueError('Save this preset before playing it')
    # Revalidate disk contents, never execute arbitrary JSON as OBS requests.
    parse(f"save preset {command['name']} with {saved.get('motion')} {saved.get('duration_ms')}ms")
    target=command['target'];current=before[target];key=next((k for k,v in SCENES.items() if v==current),None)
    if key is None:raise ValueError('Select an owned preview scene first')
    t=n.transform(key);UNDO={'target':target,'scene':current,'transforms':{key:t}}
    frames=max(4,round(saved['duration_ms']/50));started=time.monotonic()
    for i in range(frames+1):
     progress=i/frames;wave=1-(2*progress-1)**2;v=dict(t)
     motion=saved['motion']
     if motion=='slide left':v['positionX']-=180*wave
     elif motion=='slide right':v['positionX']+=180*wave
     elif motion=='lift':v['positionY']-=100*wave
     elif motion=='pulse':v['scaleX']*=1+.08*wave;v['scaleY']*=1+.08*wave
     v['positionX']=min(400,max(-400,v['positionX']));v['positionY']=min(400,max(-400,v['positionY']))
     n.set_transform(key,v)
     if i in [0,frames//2,frames]:samples.append({'frame':i,'actual_transform':n.transform(key)})
     time.sleep(max(0,started+(i+1)*saved['duration_ms']/1000/frames-time.monotonic()))
   elif kind in ['undo','undo_program']:
    target='program' if kind=='undo_program' else 'preview'
    if not UNDO or UNDO['target']!=target:raise ValueError('No matching native change to undo')
    for key,t in UNDO['transforms'].items():n.set_transform(key,t)
    if UNDO['scene'] in SCENES.values():n.req('SetCurrentProgramScene' if target=='program' else 'SetCurrentPreviewScene',{'sceneName':UNDO['scene']})
    UNDO=None
   return {'outcome':'native '+command.get('target','program' if kind=='undo_program' else 'preview')+' applied','command':command,'before':before,'after':n.snapshot(),'animation_samples':samples}
  finally:n.close()


def program_status():
 return {'enabled':PROGRAM_ENABLED,'session_id':SESSION_ID,'bound_to':PROGRAM_BINDING,'default':'off; never persisted'}
def set_program_control(enabled):
 global PROGRAM_ENABLED,PROGRAM_BINDING
 if type(enabled) is not bool:raise ValueError('enabled must be boolean')
 with LOCK:
  if not enabled:PROGRAM_ENABLED=False;PROGRAM_BINDING=None;return program_status()
  PROGRAM_ENABLED=False;PROGRAM_BINDING=None
  n=Native()
  try:
   n.outputs_off()
   if n.snapshot()['program'] not in SCENES.values():raise ValueError('Select owned program scene with outputs off before enabling')
   for key in SCENES:n.source_guard(key)
   PROGRAM_BINDING=(PROFILE,COLLECTION,SESSION_ID);PROGRAM_ENABLED=True
   return program_status()
  finally:n.close()
