import json,unittest
from unittest.mock import patch
import native_control as n
class FakeWS:
 def __init__(self,active=True):self.active=active;self.program=n.SCENES['speaker'];self.preview=n.SCENES['speaker'];self.sent=[];self.bad_source=False;self.foreign=False
 def send(self,raw):
  q=json.loads(raw)['d'];k=q['requestType'];a=q.get('requestData',{});self.sent.append(k);v={}
  if k.endswith('Status'):v={'outputActive':self.active}
  elif k=='GetSceneCollectionList':v={'currentSceneCollectionName':'foreign' if self.foreign else n.COLLECTION}
  elif k=='GetProfileList':v={'currentProfileName':n.PROFILE}
  elif k=='GetStudioModeEnabled':v={'studioModeEnabled':True}
  elif k=='GetSceneList':v={'currentProgramSceneName':self.program,'currentPreviewSceneName':self.preview}
  elif k=='GetInputSettings':
   key=next(k for k,v in n.SOURCES.items() if v==a['inputName']);v={'inputKind':'browser_source','inputSettings':{'url':'http://foreign' if self.bad_source else n.URLS[key]}}
  elif k=='GetSceneItemId':v={'sceneItemId':1}
  elif k=='GetSceneItemTransform':v={'sceneItemTransform':{'positionX':0,'positionY':0,'scaleX':1,'scaleY':1}}
  elif k=='SetCurrentProgramScene':self.program=a['sceneName']
  elif k=='SetCurrentPreviewScene':self.preview=a['sceneName']
  self.response={'op':7,'d':{'requestId':q['requestId'],'requestStatus':{'result':True},'responseData':v}}
 def recv(self):return json.dumps(self.response)
 def close(self):pass
class ProgramControl(unittest.TestCase):
 def setUp(self):
  n.PROGRAM_ENABLED=False;n.PROGRAM_BINDING=None;n.PAUSED=False;n.UNDO=None
  self.obj=n.Native.__new__(n.Native);self.obj.ws=FakeWS();self.obj.setting_up=False
 def test_active_program_default_off(self):
  with patch.object(n,'Native',return_value=self.obj),self.assertRaises(ValueError):n.execute('program break')
  self.assertNotIn('SetCurrentProgramScene',self.obj.ws.sent)
 def test_active_program_explicit_enable_then_undo(self):
  with patch.object(n,'Native',return_value=self.obj):
   self.obj.ws.active=False;n.set_program_control(True);self.obj.ws.active=True;r=n.execute('program break');self.assertTrue(r['after']['streaming']);self.assertEqual(r['after']['program'],n.SCENES['break'])
   r=n.execute('undo program');self.assertEqual(r['after']['program'],n.SCENES['speaker']);n.set_program_control(False)
   with self.assertRaises(ValueError):n.execute('program focus')
  self.assertFalse(any(k.startswith(('Start','Stop')) for k in self.obj.ws.sent))
 def test_transform_visible_in_program_requires_enable_even_offline(self):
  self.obj.ws.active=False
  with self.assertRaises(ValueError):self.obj.set_transform('speaker',{'positionX':0,'positionY':0,'scaleX':1,'scaleY':1})
  self.assertNotIn('SetSceneItemTransform',self.obj.ws.sent)
 def test_setup_rejects_active(self):
  with self.assertRaises(ValueError):self.obj.setup()
  self.assertFalse(any(k.startswith('Create') for k in self.obj.ws.sent))
 def test_source_changed_after_enable(self):
  with patch.object(n,'Native',return_value=self.obj):
   self.obj.ws.active=False;n.set_program_control(True);self.obj.ws.bad_source=True
   with self.assertRaises(ValueError):n.execute('program break')
  self.assertNotIn('SetCurrentProgramScene',self.obj.ws.sent)
  self.assertFalse(n.PROGRAM_ENABLED)
 def test_workspace_changed_disarms(self):
  with patch.object(n,'Native',return_value=self.obj):
   self.obj.ws.active=False;n.set_program_control(True);self.obj.ws.foreign=True
   with self.assertRaises(ValueError):n.execute('program break')
  self.assertFalse(n.PROGRAM_ENABLED)
 def test_initial_enable_active_refuses_and_stays_off(self):
  with patch.object(n,'Native',return_value=self.obj),self.assertRaises(ValueError):n.set_program_control(True)
  self.assertFalse(n.PROGRAM_ENABLED);self.assertIsNone(n.PROGRAM_BINDING)
 def test_mcp_has_no_enable(self):
  import asyncio,live_mcp
  tools=asyncio.run(live_mcp.mcp.list_tools())
  self.assertNotIn('set_program_control',[t.name for t in tools])
  with self.assertRaises(ValueError):live_mcp.api('program-enable',{'enabled':True})
 def test_transcript_cannot_enable(self):
  import live_server
  with patch.object(n,'set_program_control') as enable,patch.object(n,'Native') as ws:
   for i,text in enumerate(['Director, enable program control.','Director, program enable.','Director, set program control true.']):
    live_server.action('transcript',{'text':text,'event_id':'no-enable-'+str(i),'final':True})
   enable.assert_not_called();ws.assert_not_called()
  self.assertFalse(n.PROGRAM_ENABLED)
 def test_fresh_process_defaults_off(self):
  import subprocess,sys
  data=json.loads(subprocess.check_output([sys.executable,'-c','import native_control,json;print(json.dumps(native_control.program_status()))']))
  self.assertFalse(data['enabled']);self.assertIsNone(data['bound_to'])
 def test_no_forbidden_method(self):
  for k in ['StartStream','StopStream','StartRecord','StopRecord','StartVirtualCam','StopVirtualCam','SetCurrentSceneCollection']:
   with self.subTest(k=k),self.assertRaises(ValueError):self.obj.req(k)
if __name__=='__main__':unittest.main()
