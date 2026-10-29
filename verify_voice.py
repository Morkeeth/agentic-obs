"""Exercise real local audio, MCP target identity and display boundaries. No browser automation."""
import asyncio,json,os,sys,urllib.request,urllib.error
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
ROOT=Path(__file__).resolve().parent
OUT=Path(os.environ['OBS_PROOF_DIR'])
BASE='http://127.0.0.1:'+os.environ['AGENTIC_OBS_PORT']
get=lambda:json.load(urllib.request.urlopen(BASE+'/api/state'))
proof={'checks':[],'port':int(os.environ['AGENTIC_OBS_PORT'])}
assert get()['connector_port']==proof['port']
proof['before']=get()
for name in ['director-cue.aiff','ordinary-oscar.wav','silence.wav']:
 req=urllib.request.Request(BASE+'/api/audio',data=(OUT/name).read_bytes(),headers={'Content-Type':'audio/wav','X-Event-Id':'proof-'+name})
 d=json.load(urllib.request.urlopen(req,timeout=150));(OUT/(name+'.verified.json')).write_text(json.dumps(d,indent=2))
 if name=='director-cue.aiff':assert d['state']['display']['title']=='Local Audio Connected.';rev=get()['revision']
 else:assert get()['revision']==rev
 proof['checks'].append({'audio':name,'outcome':d['outcome'],'transcript':d.get('transcript'),'local_only':d['local_only']})
async def run():
 async with stdio_client(StdioServerParameters(command=sys.executable,args=[str(ROOT/'live_mcp.py')],env=dict(os.environ))) as (r,w):
  async with ClientSession(r,w) as c:
   await c.initialize()
   s=await c.call_tool('display_status',{});target=json.loads(next(x.text for x in s.content if x.type=='text'));assert target['connector_port']==proof['port']
   for name,args in [('duplicate',{'text':'Director, show RETRY','event_id':'proof-director-cue.aiff','final':True}),('interim',{'text':'Director, reveal PREMATURE','event_id':'proof-interim','final':False}),('ordinary',{'text':'We are talking about a display','event_id':'proof-ordinary','final':True})]:
    x=await c.call_tool('ingest_transcript',args);assert not x.isError;assert get()['revision']==rev;proof['checks'].append({'boundary':name,'display_unchanged':True})
   await c.call_tool('pause_display',{'paused':True});await c.call_tool('ingest_transcript',{'text':'Director, show PAUSED','event_id':'proof-paused','final':True});assert get()['revision']==rev
   proof['checks'].append({'boundary':'pause','display_unchanged':True});await c.call_tool('pause_display',{'paused':False})
   await c.call_tool('undo_display',{});assert get()['display']==proof['before']['display'];proof['checks'].append({'boundary':'undo','previous_display_restored':True});await c.call_tool('undo_display',{})
asyncio.run(run())
q=urllib.request.Request(BASE+'/api/audio',data=b'x',headers={'Origin':'http://evil.test','X-Event-Id':'proof-crossorigin'})
try:urllib.request.urlopen(q);raise AssertionError('crossoriginaccepted')
except urllib.error.HTTPError as e:assert e.code==403
proof['checks'].append({'boundary':'cross-origin audio','rejected':403})
proof['final']=get();proof['microphone']='WAITING FOR BROWSER PERMISSION; no captured live mic audio'
proof['fixture']='macOS Samantha TTS test fixture; not Oscar voice, not live mic'
(OUT/'VOICE-PIPELINE-VERIFICATION.json').write_text(json.dumps(proof,indent=2));print(json.dumps(proof,indent=2))
