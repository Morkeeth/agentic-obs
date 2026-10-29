import asyncio, json, os
from pathlib import Path
import live_server as s
from voice_pipeline import _send
checks=[]
def cue(text,i):return s.action('transcript',{'text':text,'event_id':str(i),'final':True})
for i,text in enumerate(['focus.','clear.','back to me.','countdown20.','countdown20 seconds.','take a break.']):
 r=cue('Director, '+text,i);assert r['outcome']=='applied';checks.append(text)
r=cue('Director, show Toast. Anyway, so what I was saying',20);assert r['state']['display']['title']=='Toast';checks.append('first-sentence boundary')
for i,t in enumerate(['I asked the director to show me the cut','The director said hello','Director, unsupported operation.'],30):
 before=s.status()['revision'];r=cue(t,i);assert s.status()['revision']==before;checks.append(t)
os.environ.pop('AGENTIC_OBS_PORT',None)
try:asyncio.run(_send('Director, focus.','missing-port'));raise AssertionError('accepted missing port')
except ValueError as e:assert 'explicitly' in str(e);checks.append('missing port fails before MCP')
Path('obs-regression-proof/GREEN.json').write_text(json.dumps({'checks':checks},indent=2))
print('PASS',len(checks))
