"""OFFLINE EventSub-shaped experiment. No Twitch connection, OAuth, subscriptions or OBS calls."""
import asyncio
import collections
from datetime import datetime, timezone
import json
import urllib.request
from urllib.parse import urlsplit
from websockets.asyncio.client import connect

CHAT='channel.chat.message'
REDEMPTION='channel.channel_points_custom_reward_redemption.add'
# Viewer strings select a fixed action; they never become prompt or overlay text.
COMMANDS={'!overlay party':'Director party', '!overlay hydrate':'Director show Hydrate!', '!overlay clear':'Director clear'}
REWARDS={'mock-hydrate':'Director show Hydrate!'}

def local_url(url, scheme):
    u=urlsplit(url)
    if u.scheme!=scheme or u.hostname!='127.0.0.1' or u.username or u.password or not u.port or u.fragment or u.query or u.path not in ('','/ws','/reconnect'):
        raise ValueError('only literal 127.0.0.1 experiment endpoints allowed')
    if u.port not in (8881,8882): raise ValueError('endpoint not owned by this experiment')
    return url

class LocalConnect(connect):
    def process_redirect(self, exc):
        return exc  # refuse every HTTP redirect before another socket can be opened

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('HTTP redirects are forbidden in the offline experiment')

class Adapter:
    def __init__(self, send):
        self.send=send; self.enabled=False; self.session=None; self.timeout=10; self.seen=collections.OrderedDict();self.trace=[]
    def feed(self, message):
        result={'result':'ignored'}
        try:
            if not isinstance(message,dict): raise ValueError('object required')
            m=message['metadata']; p=message['payload']; ident=m['message_id']; kind=m['message_type']
            if not isinstance(ident,str) or not 0<len(ident)<=128: raise ValueError('bad id')
            ts=datetime.fromisoformat(m['message_timestamp'].replace('Z','+00:00'))
            age=(datetime.now(timezone.utc)-ts).total_seconds()
            if not -5<=age<=60: raise ValueError('stale/future event')
            if ident in self.seen: return self.note(ident,'duplicate')
            self.seen[ident]=True
            if len(self.seen)>4096:self.seen.popitem(last=False)
            if kind=='session_welcome':
                s=p['session']; sid=s['id']; timeout=s['keepalive_timeout_seconds']
                if not isinstance(sid,str) or not sid or type(timeout) is not int or not 1<=timeout<=600:raise ValueError('bad session')
                self.session=sid;self.timeout=timeout;return self.note(ident,'welcome',session=sid)
            if not self.session:raise ValueError('welcome required')
            if kind=='session_keepalive':return self.note(ident,'keepalive')
            if kind=='session_reconnect':
                url=local_url(p['session']['reconnect_url'],'ws');return self.note(ident,'reconnect',url=url)
            if kind=='revocation':
                self.enabled=False;return self.note(ident,'revoked; adapter off')
            if kind!='notification':return self.note(ident,'unsupported')
            sub=p['subscription'];e=p['event'];typ=m['subscription_type']
            if sub['type']!=typ or sub['version']!='1' or m['subscription_version']!='1':raise ValueError('subscription mismatch')
            if sub['condition']['broadcaster_user_id']!='42' or e['broadcaster_user_id']!='42':raise ValueError('wrong channel')
            cue=None
            if typ==CHAT:
                if not isinstance(e['message_id'],str) or not isinstance(e['chatter_user_id'],str):raise ValueError('bad chat identity')
                cue=COMMANDS.get(e['message']['text'])
            elif typ==REDEMPTION:cue=REWARDS.get(e['reward']['id'])
            if not cue:return self.note(ident,'no cue')
            if not self.enabled:return self.note(ident,'input off')
            response=self.send(cue)
            return self.note(ident,'submitted',cue=cue,response=response)
        except (KeyError,TypeError,ValueError,AttributeError) as exc:
            return self.note(None,'rejected',reason=str(exc))
    def note(self,ident,result,**extra):
        row={'id':ident,'result':result,**extra};self.trace.append(row);return row

class Controller:
    def __init__(self,url='http://127.0.0.1:8881'):
        local_url(url,'http');self.url=url
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    def request(self,path,payload=None):
        req=urllib.request.Request(self.url+path,data=json.dumps(payload).encode() if payload is not None else None,headers={'Origin':self.url,'Content-Type':'application/json'})
        with self.opener.open(req,timeout=3) as r:return json.load(r)
    def send(self,cue):
        state=self.request('/status')
        if state['build_tag']!='OFFLINE-eventsub-experiment-28oct' or state['connector_port']!=8881 or state['planner']!='rules' or state['models']['codex']['enabled'] or state['models']['codex']['calls']:
            raise ValueError('controller guard failed')
        return self.request('/chat-sim',{'text':cue})

async def consume(url, adapter, max_connections=2):
    """Mock reconnect preserves old socket until replacement welcome; never sends application data."""
    local_url(url,'ws'); socket=None; previous=None
    try:
        for _ in range(max_connections):
            socket=await LocalConnect(url,proxy=None,max_size=20000,open_timeout=3)
            adapter.session=None; reconnect=None
            while True:
                try:raw=await asyncio.wait_for(socket.recv(),timeout=adapter.timeout)
                except TimeoutError:
                    adapter.note(None,'keepalive timeout');return
                except Exception as exc:
                    from websockets.exceptions import ConnectionClosedOK
                    if isinstance(exc,ConnectionClosedOK):return
                    raise
                try:msg=json.loads(raw)
                except (ValueError,TypeError):adapter.note(None,'rejected',reason='bad JSON');continue
                row=adapter.feed(msg)
                if row['result']=='welcome' and previous is not None:
                    await previous.close();previous=None
                if row['result']=='reconnect':reconnect=row['url'];break
            if reconnect:
                previous=socket;socket=None;url=reconnect
            else:return
    finally:
        adapter.enabled=False
        if socket is not None:await socket.close()
        if previous is not None:await previous.close()
