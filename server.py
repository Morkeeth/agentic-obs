#!/usr/bin/env python3
"""Local exploratory show director. No AI API, OBS control or Twitch credentials."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
import copy, datetime, json, re, threading, time, uuid

ROOT = Path(__file__).resolve().parent
LOCK = threading.RLock()
EXAMPLES = [
 {'label':'Toast, but make it science','prompt':'Late-night science show. Camera left. 12 second countdown. Reveal: TOAST ACHIEVED. Keep the movement quiet.'},
 {'label':'The skill issue forecast','prompt':'Weather report. Camera right. 9 second countdown. Reveal: 80% CHANCE OF SKILL ISSUE. Make it playful.'},
 {'label':'Coffee mission control','prompt':'Space mission control. Camera left. 15 second countdown. Reveal: COFFEE HAS LANDED. Less movement.'}
]

def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def compile_prompt(prompt, base=None):
    if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>1800: raise ValueError('Write a brief between1 and1800 characters.')
    low=prompt.lower(); p=copy.deepcopy(base) if base else {'title':'Tonight’s experiment','theme':'science','camera':'left','motion':'quiet','duration':12,'hold':4,'reveal':'TOAST ACHIEVED'}
    if any(w in low for w in ['space','mission','orbit']): p.update(theme='space',title='Mission control')
    elif any(w in low for w in ['weather','forecast','rain']): p.update(theme='weather',title='The forecast is personal')
    elif any(w in low for w in ['science','late-night','toast','experiment']): p.update(theme='science',title='Late-night science')
    if 'camera right' in low:p['camera']='right'
    elif 'camera left' in low:p['camera']='left'
    timing=re.sub(r'hold(?: the)? reveal(?: for)? \d{1,2}(?: seconds?)?','',low)
    match=re.search(r'(\d{1,2})[ -]*(?:second|sec|s\b)',timing)
    if match:p['duration']=max(3,min(45,int(match.group(1))))
    if any(w in low for w in ['less movement','quiet','calm']):p['motion']='quiet'
    elif any(w in low for w in ['playful','more movement','energetic']):p['motion']='playful'
    match=re.search(r'reveal\s*:\s*([^.!?\n]{1,80})',prompt,re.I)
    if match:p['reveal']=match.group(1).strip()
    match=re.search(r'hold(?: the)? reveal(?: for)? (\d{1,2})',low)
    if match:p['hold']=max(2,min(20,int(match.group(1))))
    p['brief']=prompt.strip();p['id']=uuid.uuid4().hex[:8];p['beats']=[{'label':'Set the scene','seconds':3},{'label':'Build anticipation','seconds':p['duration']},{'label':'The reveal','seconds':p.get('hold',4)},{'label':'Return to normal','seconds':2}]
    return p

NORMAL={'id':'normal','title':'Back to the stream','theme':'normal','camera':'left','motion':'quiet','duration':12,'reveal':'','brief':'Normal camera layout','beats':[]}
STATE={'draft':compile_prompt(EXAMPLES[0]['prompt']),'program':copy.deepcopy(NORMAL),'restore':None,'rehearsal':None,'program_started':None,'history':[],'saved':[],'mode':'LOCAL_PROTOTYPE_NO_OBS_OR_TWITCH'}
# Explicitly saved drafts persist; a server restart never takes a segment automatically.
try:
    previous=json.loads((ROOT/'session-state.json').read_text())
    STATE['saved']=previous.get('saved',[])[:12]
    STATE['history']=previous.get('history',[])[-25:]
except (OSError,ValueError,TypeError):
    pass

def event(name, detail):
    STATE['history'].append({'at':now(),'action':name,'detail':detail});STATE['history']=STATE['history'][-25:]
    (ROOT/'session-state.json').write_text(json.dumps(STATE,indent=2))

def action(path,data):
    with LOCK:
      if path=='/api/compile':
        STATE['draft']=compile_prompt(data.get('prompt'),STATE['draft'] if data.get('revise') else None);STATE['rehearsal']=None;event('revise' if data.get('revise') else 'compile',STATE['draft']['brief'])
      elif path=='/api/update':
        d=STATE['draft'];v=data.get('fields',{})
        if not isinstance(v,dict):raise ValueError('fields must be an object')
        for k in v:
          if k not in ['title','camera','duration','motion','reveal','hold']:raise ValueError('Unsupported show field')
        if 'camera' in v and v['camera'] not in ['left','right']:raise ValueError('Camera must be left or right')
        if 'motion' in v and v['motion'] not in ['quiet','playful']:raise ValueError('Motion must be quiet or playful')
        if 'duration' in v and (not isinstance(v['duration'],int) or isinstance(v['duration'],bool) or not 3<=v['duration']<=45):raise ValueError('Countdown must be3–45 seconds')
        if 'hold' in v and (not isinstance(v['hold'],int) or isinstance(v['hold'],bool) or not 2<=v['hold']<=20):raise ValueError('Reveal hold must be2–20 seconds')
        for k in ['title','reveal']:
          if k in v and (not isinstance(v[k],str) or not 1<=len(v[k])<=80):raise ValueError('Text must be1–80 characters')
        d.update(v);d['beats'][1]['seconds']=d['duration'];d['beats'][2]['seconds']=d.get('hold',4);STATE['rehearsal']=None;event('edit',v)
      elif path=='/api/rehearse':STATE['rehearsal']={'show':copy.deepcopy(STATE['draft']),'started':time.time()};event('rehearse',STATE['draft']['id'])
      elif path=='/api/stop-rehearsal':STATE['rehearsal']=None;event('stop rehearsal','')
      elif path=='/api/take':
        # Only the local program state changes. No websocket or stream is started.
        STATE['restore']={'show':copy.deepcopy(STATE['program']),'started':STATE['program_started']};STATE['program']=copy.deepcopy(STATE['draft']);STATE['program_started']=time.time();event('take local',STATE['program']['id'])
      elif path=='/api/restore':
        if STATE['restore'] is None:raise ValueError('There is no prior program to restore')
        previous=STATE['restore'];STATE['program']=previous['show'];STATE['program_started']=previous['started'];STATE['restore']=None;event('restore local',STATE['program']['id'])
      elif path=='/api/save':
        STATE['saved'].append(copy.deepcopy(STATE['draft']));STATE['saved']=STATE['saved'][-12:];event('save',STATE['draft']['id'])
      elif path=='/api/load':
        idx=data.get('index');
        if not isinstance(idx,int) or not 0<=idx<len(STATE['saved']):raise ValueError('Choose a saved show')
        STATE['draft']=copy.deepcopy(STATE['saved'][idx]);STATE['rehearsal']=None;event('load saved',idx)
      else:raise ValueError('Unknown action')
      return copy.deepcopy(STATE)

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*a,**kw):super().__init__(*a,directory=str(ROOT/'web'),**kw)
    def log_message(self,*a):pass
    def send_json(self,data,status=200):
        raw=json.dumps(data).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        p=urlparse(self.path).path
        if p=='/api/state':
          with LOCK:self.send_json(copy.deepcopy(STATE))
        elif p=='/api/examples':self.send_json(EXAMPLES)
        elif p=='/api/show.json':
          with LOCK:self.send_json(STATE['draft'])
        else:super().do_GET()
    def do_POST(self):
        # Same-origin local actions only; no secret or filesystem read endpoint.
        host=self.headers.get('Host','');origin=self.headers.get('Origin')
        if host not in ['127.0.0.1:8873','localhost:8873'] or (origin and origin not in ['http://127.0.0.1:8873','http://localhost:8873']):return self.send_json({'error':'Local same-origin requests only'},403)
        try:
          size=int(self.headers.get('Content-Length',0))
          if size>8192:raise ValueError('Request too large')
          data=json.loads(self.rfile.read(size));result=action(urlparse(self.path).path,data);self.send_json(result)
        except (ValueError,TypeError,KeyError) as e:self.send_json({'error':str(e)},400)

if __name__=='__main__':
    print('Agentic OBS local rehearsal: http://127.0.0.1:8873',flush=True)
    ThreadingHTTPServer(('127.0.0.1',8873),Handler).serve_forever()
