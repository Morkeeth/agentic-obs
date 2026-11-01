#!/usr/bin/env python3
"""Local display connector. No broadcast/profile mutation or external model calls."""
import copy, json, re, socket, threading, time, uuid, os
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
ROOT=Path(__file__).resolve().parent
LOCK=threading.RLock(); PORT=8878
STATE={'revision':0,'armed':True,'display':{'title':'Talk. We’ll handle the screen.','subtitle':'Your live browser display','layout':'speaker','accent':'lime','cue':'','until':None},'events':[],'transcript':'','obs':{'connected':False,'detail':'Not checked'},'undo':None}
SEEN={}
def status():
    with LOCK:return copy.deepcopy({'connector_port':PORT,'build_tag':'native-program-27oct', **{k:v for k,v in STATE.items() if k!='undo'}})
def obs_probe():
    # Read-only OBS v5 handshake. Password is provided explicitly through env only.
    import os, hashlib, base64
    try:
        import websocket
        ws=websocket.create_connection('ws://127.0.0.1:4455',timeout=1)
        try:
            hello=json.loads(ws.recv()); auth=hello.get('d',{}).get('authentication'); identify={'rpcVersion':1,'eventSubscriptions':0}
            if auth:
                password=os.environ.get('OBS_WEBSOCKET_PASSWORD')
                if not password:return {'connected':False,'detail':'OBS requires a password; set OBS_WEBSOCKET_PASSWORD explicitly'}
                enc=lambda s:base64.b64encode(hashlib.sha256(s.encode()).digest()).decode()
                identify['authentication']=enc(enc(password+auth['salt'])+auth['challenge'])
            ws.send(json.dumps({'op':1,'d':identify})); identified=json.loads(ws.recv())
            if identified.get('op')!=2:raise ValueError('OBS identification failed')
            ws.send(json.dumps({'op':6,'d':{'requestType':'GetVersion','requestId':'connector-status'}})); version=json.loads(ws.recv())
            if not version.get('d',{}).get('requestStatus',{}).get('result'):raise ValueError('OBS version request failed')
            return {'connected':True,'detail':'Read-only OBS WebSocket connected','version':version['d']['responseData'].get('obsVersion'),'mutations':False}
        finally:ws.close()
    except Exception as e:return {'connected':False,'detail':f'OBS disconnected ({type(e).__name__}); browser output still works'}
def validate(fields):
    if not isinstance(fields,dict) or not fields:raise ValueError('Provide display fields')
    if set(fields)-{'title','subtitle','layout','accent','cue','seconds'}:raise ValueError('Unsupported display field')
    for k in ['title','subtitle','cue']:
        if k in fields and (not isinstance(fields[k],str) or len(fields[k])>160):raise ValueError(k+' must be text up to160characters')
    if 'layout' in fields and fields['layout'] not in ['speaker','focus','break']:raise ValueError('Unknown layout')
    if 'accent' in fields and fields['accent'] not in ['lime','pink','white']:raise ValueError('Unknown accent')
    if 'seconds' in fields and (type(fields['seconds']) is not int or not 0<=fields['seconds']<=600):raise ValueError('seconds must be0–600')
def parse(text):
    text=text.strip().rstrip('.!?').strip(); low=text.lower()
    if low in ['clear','clear the screen']:return {'title':'','subtitle':'','cue':'','seconds':0}
    if low in ['speaker','back to me','camera']:return {'layout':'speaker','cue':'','seconds':0}
    if low in ['focus','focus mode']:return {'layout':'focus'}
    if low in ['break','take a break']:return {'layout':'break','title':'Back in a moment','subtitle':'Stay close'}
    m=re.fullmatch(r'(?:show|title)\s+(.+)',text,re.I)
    if m:return {'title':m[1],'layout':'speaker'}
    m=re.fullmatch(r'(?:caption|subtitle)\s+(.+)',text,re.I)
    if m:return {'subtitle':m[1]}
    m=re.fullmatch(r'countdown\s*(\d+)\s*(?:seconds?)?',text,re.I)
    if m:return {'seconds':int(m[1]),'cue':'Up next'}
    m=re.fullmatch(r'(?:cue|reveal)\s+(.+)',text,re.I)
    if m:return {'cue':m[1],'seconds':0}
    raise ValueError('Cue not understood. Try: show…, caption…, countdown20, reveal…, focus, back to me, break, clear')
def action(kind,data):
    with LOCK:
        if kind=='native':
            from native_control import execute
            return execute(data.get('text',''))
        if kind=='obs':STATE['obs']=obs_probe();return status()
        if kind=='arm':
            if type(data.get('armed')) is not bool:raise ValueError('armed must be boolean')
            STATE['armed']=data['armed'];return status()
        if kind=='undo':
            if STATE['undo'] is None:raise ValueError('No display change to undo')
            STATE['display'],STATE['undo']=STATE['undo'],STATE['display'];fields=None
        else:
            source=data.get('source','prompt')
            if source not in ['prompt','transcript','mcp']:raise ValueError('Unknown source')
            if kind=='transcript':
                text=data.get('text');eid=data.get('event_id');final=data.get('final')
                if not isinstance(text,str) or len(text)>2000 or not isinstance(eid,str) or not 1<=len(eid)<=120 or type(final) is not bool:raise ValueError('Need text, event_id and final boolean')
                STATE['transcript']=text
                if not final:return {'outcome':'interim; display unchanged','state':status()}
                if eid in SEEN:return {'outcome':'duplicate; display unchanged','state':status()}
                if not STATE['armed']:return {'outcome':'paused; display unchanged','state':status()}
                SEEN[eid]=time.time()
                while len(SEEN)>1000:SEEN.pop(next(iter(SEEN)))
                m=re.search(r'(?:^|[.!?]\s+)\s*director\s*[, :]\s*(.+)',text,re.I)
                if not m:return {'outcome':'speech without director cue; display unchanged','state':status()}
                cue=m[1].strip()
                # Unquoted speech ends at its first sentence boundary. Quote titles
                # explicitly when punctuation is part of the intended displayed text.
                quoted=re.fullmatch(r'(show|title|caption|subtitle|cue|reveal)\s+["“](.+?)["”](?:[.!?](?:\s.*)?|\s*)',cue,re.I)
                if quoted: cue=quoted[1]+' '+quoted[2]
                else: cue=re.split(r'[.!?](?:\s|$)',cue,maxsplit=1)[0]
                if re.match(r'^(preview |program |play (?:program )?preset |undo (?:preview|program)|pause native|resume native)',cue,re.I):
                    from native_control import execute,parse as parse_native
                    try:parse_native(cue)
                    except ValueError:return {'outcome':'unsupported native cue; OBS unchanged','state':status()}
                    return execute(cue)
                try:fields=parse(cue)
                except ValueError:return {'outcome':'unsupported director cue; display unchanged','state':status()}
                source='transcript'
            elif kind=='prompt':fields=parse(data.get('text',''))
            elif kind=='display':fields=data.get('fields')
            else:raise ValueError('Unknown action')
            validate(fields)
            if not STATE['armed']:raise ValueError('Display paused; resume before changing it')
            new=copy.deepcopy(STATE['display']);values=fields.copy()
            if 'seconds' in values:
                sec=values.pop('seconds');new['until']=time.time()+sec if sec else None
            new.update(values);STATE['undo']=STATE['display'];STATE['display']=new
        STATE['revision']+=1
        STATE['events'].append({'at':time.time(),'revision':STATE['revision'],'kind':kind,'source':data.get('source',kind),'fields':fields});STATE['events']=STATE['events'][-40:]
        return {'outcome':'applied','state':status()}
class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*a,**kw):super().__init__(*a,directory=str(ROOT/'live_web'),**kw)
    def log_message(self,*a):pass
    def local(self):
        return self.headers.get('Host') in [f'127.0.0.1:{PORT}',f'localhost:{PORT}'] and self.headers.get('Origin') in [None,f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}']
    def reply(self,value,code=200):
        b=json.dumps(value).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
    def do_GET(self):
        if not self.local():return self.reply({'error':'Local origin required'},403)
        if urlparse(self.path).path=='/api/state':return self.reply(status())
        if urlparse(self.path).path=='/api/program-status':
            from native_control import program_status
            return self.reply(program_status())
        if urlparse(self.path).path=='/api/audio-status':
            from voice_pipeline import readiness
            return self.reply(readiness())
        super().do_GET()
    def do_POST(self):
        if not self.local():return self.reply({'error':'Local origin required'},403)
        try:
            if urlparse(self.path).path=='/api/audio':
                from voice_pipeline import process_audio
                size=int(self.headers.get('Content-Length',0))
                if not 0<size<=2_000_000:raise ValueError('Audio clip must be under2MB')
                eid=self.headers.get('X-Event-Id','')
                if not 1<=len(eid)<=120:raise ValueError('Audio needs an event ID')
                return self.reply(process_audio(self.rfile.read(size),eid))
            size=int(self.headers.get('Content-Length',0))
            if not 0<size<=8192:raise ValueError('Invalid request size')
            data=json.loads(self.rfile.read(size))
            if not isinstance(data,dict):raise ValueError('Expected object')
            if urlparse(self.path).path=='/api/program-enable':
                if self.headers.get('Origin') not in [f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}']:
                    return self.reply({'error':'Enable program control from the local controller UI'},403)
                from native_control import set_program_control
                return self.reply(set_program_control(data.get('enabled')))
            self.reply(action(urlparse(self.path).path.removeprefix('/api/'),data))
        except (ValueError,TypeError,AttributeError) as e:self.reply({'error':str(e)},400)
        except Exception:
            # Infrastructure failures (including MCP ExceptionGroup) are distinct
            # from unsupported/no-cue speech. Never return tracebacks or credentials.
            self.reply({'error':'Local connector transport failed; no completed action confirmed','code':'transport_failure'},502)
if __name__=='__main__':
    if os.environ.get('AGENTIC_OBS_PORT')!='8878':raise ValueError('Set explicit isolated target8878')
    STATE['obs']=obs_probe()
    print(f'Live connector http://127.0.0.1:{PORT}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',PORT),Handler).serve_forever()
