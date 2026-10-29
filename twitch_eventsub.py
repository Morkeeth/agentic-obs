"""Restricted EventSub transport, implemented from the rebuild contract."""
import argparse
import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import time
import urllib.request
import urllib.error
from urllib.parse import urlsplit
import websockets

CHAT = 'channel.chat.message'
REDEMPTION = 'channel.channel_points_custom_reward_redemption.add'
COMMANDS = {'!overlay party': 'Director party', '!overlay hydrate': 'Director show Hydrate!', '!overlay clear': 'Director clear'}
CUES = frozenset(COMMANDS.values())
class TwitchError(Exception):
    pass

@dataclass(frozen=True)
class Endpoints:
    ws: str
    validate: str
    helix: str
LIVE = Endpoints('wss://eventsub.wss.twitch.tv/ws', 'https://id.twitch.tv/oauth2/validate', 'https://api.twitch.tv/helix/eventsub/subscriptions')
def offline_endpoints(ws_port=8883, http_port=8884):
    return Endpoints(f'ws://127.0.0.1:{ws_port}/ws', f'http://127.0.0.1:{http_port}/oauth2/validate', f'http://127.0.0.1:{http_port}/helix/eventsub/subscriptions')

@dataclass
class Config:
    client_id: str
    broadcaster_user_id: str
    reader_user_id: str
    rewards: dict
    keepalive_seconds: float = 10
    def __post_init__(self):
        if any(not isinstance(x, str) or not x.strip() for x in (self.client_id, self.broadcaster_user_id, self.reader_user_id)):
            raise TwitchError('invalid identifiers')
        if not isinstance(self.rewards, dict) or any(not isinstance(k,str) or not k or not isinstance(v,str) or v not in CUES for k,v in self.rewards.items()):
            raise TwitchError('invalid rewards')
        if not isinstance(self.keepalive_seconds,(int,float)) or self.keepalive_seconds <= 0:
            raise TwitchError('invalid keepalive')
    def types(self):
        return [CHAT] + ([REDEMPTION] if self.rewards else [])

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

def request(url, headers=None, body=None):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    data = None if body is None else json.dumps(body).encode()
    hdr = dict(headers or {})
    if data is not None: hdr['Content-Type'] = 'application/json'
    try:
        with opener.open(urllib.request.Request(url, data=data, headers=hdr, method="GET" if data is None else "POST"), timeout=8) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise TwitchError(f'refused ({exc.code})') from None
    except Exception:
        raise TwitchError('request failed') from None

class Helix:
    def __init__(self,cfg,endpoints,token_provider):
        self.cfg,self.endpoints,self.token_provider = cfg,endpoints,token_provider
        self.next_validation = 0
    def validate(self):
        token = self.token_provider()
        if not isinstance(token,str) or not token: raise TwitchError('missing token')
        token = token.strip().removeprefix('oauth:')
        info = request(self.endpoints.validate,{'Authorization': 'OAuth '+token, 'Client-Id': self.cfg.client_id})
        scopes = info.get('scopes',[])
        if info.get('client_id') != self.cfg.client_id:
            raise TwitchError('token client mismatch')
        if info.get('user_id') != self.cfg.reader_user_id:
            raise TwitchError('token user is not the configured reader')
        if 'user:read:chat' not in scopes: raise TwitchError('missing chat scope')
        if self.cfg.rewards and (info.get('user_id') != self.cfg.broadcaster_user_id or not set(scopes).intersection({'channel:read:redemptions','channel:manage:redemptions'})):
            raise TwitchError('missing redemption scope or identity')
        expires = info.get('expires_in',0)
        if not isinstance(expires,(float,int)) or expires <= 0: raise TwitchError('token expired')
        self.token = token
        self.next_validation = time.monotonic()+min(3600,expires)
        return info
    async def subscribe(self,session):
        result = {}
        for kind in self.cfg.types():
            condition = {'broadcaster_user_id':self.cfg.broadcaster_user_id}
            if kind == CHAT: condition['user_id'] = self.cfg.reader_user_id
            body = {'type':kind,'version':'1','condition':condition,'transport':{'method':'websocket','session_id':session}}
            data = await asyncio.to_thread(request,self.endpoints.helix,{'Authorization':'Bearer '+self.token,'Client-Id':self.cfg.client_id},body)
            try: result[kind] = data['data'][0]['id']
            except (KeyError,IndexError,TypeError): raise TwitchError('invalid subscription response') from None
        return result

class Adapter:
    def __init__(self,cfg,endpoints,send):
        self.cfg,self.endpoints,self.send = cfg,endpoints,send
        self.subscriptions = {}
        self.enabled = False
        self.session = None
        self.trace = []
        self.seen = OrderedDict()
        self.stopped = False
    def record(self,result,reason=None):
        item = {'result':result}
        if reason: item['reason'] = reason
        self.trace.append(item)
        del self.trace[:-200]
        return item
    def stop(self,reason):
        self.enabled = False
        self.stopped = True
        return self.record('stopped',reason)
    def reconnect_url(self,url):
        try:
            base,u = urlsplit(self.endpoints.ws),urlsplit(url)
            if (u.scheme,u.hostname,u.port)!=(base.scheme,base.hostname,base.port) or u.username or u.password or u.fragment or u.path not in (('/ws','/reconnect') if base.hostname == '127.0.0.1' else ('/ws',)):
                raise ValueError()
        except Exception: raise ValueError('invalid reconnect URL') from None
        return url
    def feed(self,envelope):
        try:
            meta,payload = envelope['metadata'],envelope['payload']
            kind = meta['message_type']
            mid = meta['message_id']
            stamp = datetime.fromisoformat(meta['message_timestamp'].replace('Z','+00:00'))
            age = (datetime.now(timezone.utc)-stamp).total_seconds()
            if not isinstance(mid,str) or not mid or age > 600 or age < -60: return self.record('rejected','stale or invalid metadata')
            if mid in self.seen: return self.record('duplicate')
            self.seen[mid] = None
            if len(self.seen)>2048: self.seen.popitem(last=False)
            if self.stopped: return self.record('rejected','stopped')
            if kind == 'session_welcome':
                session = payload['session']['id']
                if not isinstance(session, str) or not session:
                    return self.record('rejected', 'invalid session')
                self.session = session
                return self.record('welcome')
            if kind == 'session_keepalive': return self.record('keepalive')
            if kind == 'session_reconnect':
                self.reconnect_url(payload['session']['reconnect_url'])
                return self.record('reconnect')
            if kind == 'revocation': return self.stop('subscription revoked')
            if kind != 'notification': return self.record('rejected','unknown message')
            sub,event = payload['subscription'],payload['event']
            typ = sub['type']
            if typ not in self.cfg.types() or meta.get('subscription_type') != typ or meta.get('subscription_version') != '1' or sub.get('version') != '1' or sub.get('status') != 'enabled' or sub.get('id') != self.subscriptions.get(typ):
                return self.record('rejected','invalid subscription')
            if sub.get('transport',{}).get('method') != 'websocket' or sub['transport'].get('session_id') != self.session or not self.session: return self.record('rejected','wrong session')
            cond = sub.get('condition',{})
            if cond.get('broadcaster_user_id') != self.cfg.broadcaster_user_id or event.get('broadcaster_user_id') != self.cfg.broadcaster_user_id: return self.record('rejected','wrong channel')
            if typ == CHAT and cond.get('user_id') != self.cfg.reader_user_id: return self.record('rejected','wrong reader')
            cue = COMMANDS.get(event.get('message',{}).get('text')) if typ == CHAT else self.cfg.rewards.get(event.get('reward',{}).get('id'))
            if cue is None: return self.record('ignored')
            if not self.enabled: return self.record('input off')
            self.send(cue)
            return self.record('forwarded')
        except (KeyError,TypeError,ValueError,AttributeError): return self.record('rejected','malformed envelope')

class StreamAgentSink:
    def __init__(self,url='http://127.0.0.1:8879'):
        if url not in ('http://127.0.0.1:8879','http://127.0.0.1:8881'): raise TwitchError('invalid controller URL')
        self.url = url
    def __call__(self,cue):
        if cue not in CUES: raise TwitchError('invalid cue')
        status = request(self.url+'/status', {'Origin': self.url})
        codex = status.get('models', {}).get('codex', {})
        if status.get('planner') != 'rules' or codex.get('enabled') is not False or codex.get('calls') != 0 or status.get('build_tag') != 'stream-agent-27oct':
            raise TwitchError('unsafe controller')
        return request(self.url+'/chat-sim',{'Origin':self.url},{'text':cue})

async def run(cfg,endpoints,token_provider,send,enabled=False,max_fresh_sessions=3,log=print):
    adapter = Adapter(cfg,endpoints,send)
    helix = Helix(cfg,endpoints,token_provider)
    sockets = set()
    try:
        await asyncio.to_thread(helix.validate)
        fresh = 0
        url = endpoints.ws
        transfer = False
        while fresh < max_fresh_sessions:
            try:
                if not transfer: fresh += 1
                connection = websockets.connect(url,proxy=None,ping_interval=None,open_timeout=8)
                connection.process_redirect = lambda exc: exc
                ws = await connection
                sockets.add(ws)
                deadline = time.monotonic() + 10
                while True:
                    raw = await asyncio.wait_for(ws.recv(), max(0, deadline-time.monotonic()))
                    envelope = json.loads(raw)
                    if envelope.get('metadata',{}).get('message_type') == 'session_welcome':
                        adapter.feed(envelope)
                        break
                    adapter.record('rejected', 'first message must be welcome')
                if not adapter.session: raise TwitchError('invalid welcome')
                if not transfer: adapter.subscriptions = await asyncio.wait_for(helix.subscribe(adapter.session),max(0,deadline-time.monotonic()))
                adapter.enabled = bool(enabled)
                for other in list(sockets):
                    if other is not ws:
                        await other.close()
                        sockets.discard(other)
                transfer = False
                timeout = envelope['payload']['session'].get('keepalive_timeout_seconds',cfg.keepalive_seconds)+1
                while True:
                    remaining = helix.next_validation-time.monotonic()
                    if remaining <= 0:
                        await asyncio.to_thread(helix.validate)
                        continue
                    try: raw = await asyncio.wait_for(ws.recv(),min(timeout,remaining))
                    except asyncio.TimeoutError:
                        if time.monotonic() >= helix.next_validation:
                            await asyncio.to_thread(helix.validate)
                            continue
                        raise
                    envelope = json.loads(raw)
                    result = adapter.feed(envelope)
                    log(json.dumps(result))
                    if adapter.stopped: return adapter
                    if result['result'] == 'reconnect':
                        url = adapter.reconnect_url(envelope['payload']['session']['reconnect_url'])
                        adapter.session = None
                        adapter.enabled = False
                        transfer = True
                        break
            except websockets.exceptions.ConnectionClosed as exc:
                transfer = False
                code = exc.rcvd.code if exc.rcvd else None
                if code in {4001,4002,4003,4004,4007}:
                    adapter.stop(f'closed {code}')
                    return adapter
            except websockets.exceptions.InvalidHandshake:
                adapter.stop('websocket handshake refused')
                return adapter
            except (OSError,asyncio.TimeoutError):
                transfer = False
            if not transfer:
                adapter.enabled = False
                adapter.session = None
                for socket in list(sockets):
                    await socket.close()
                    sockets.discard(socket)
                url = endpoints.ws
                if fresh < max_fresh_sessions: await asyncio.sleep(min(fresh,3)*0.1)
        adapter.stop('session limit')
    except (ValueError, TypeError, KeyError, AttributeError):
        adapter.stop('malformed socket message')
    except TwitchError as exc:
        adapter.stop(str(exc))
    finally:
        adapter.enabled = False
        for socket in sockets: await socket.close()
    return adapter

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config',required=True)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--enable-events',action='store_true')
    args = parser.parse_args()
    with open(args.config) as stream: cfg = Config(**json.load(stream))
    if not args.live:
        print(json.dumps({'types':cfg.types(),'enabled':False}))
        return
    adapter = asyncio.run(run(cfg,LIVE,lambda:os.environ.get('TWITCH_USER_TOKEN'),StreamAgentSink(),enabled=args.enable_events))
    print(json.dumps(adapter.trace))
if __name__ == '__main__': main()
