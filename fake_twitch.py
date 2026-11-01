"""Local stand-in for Twitch's validate, Helix subscription and EventSub WebSocket endpoints (127.0.0.1 only).
Messages follow the shapes on Twitch's EventSub pages; nothing here is evidence of real Twitch delivery."""
import asyncio
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import uuid
from websockets.asyncio.server import serve

from twitch_eventsub import CHAT, REDEMPTION

TOKEN = 'fake-token-never-real-' + uuid.uuid4().hex   # unique per run so leaks are detectable
CLIENT_ID = 'fakeclient123'
BROADCASTER = '1001'


def now():
    return datetime.now(timezone.utc).isoformat()


def envelope(kind, payload, ident=None, sub_type=None):
    m = {'message_id': ident or uuid.uuid4().hex, 'message_type': kind, 'message_timestamp': now()}
    if sub_type:
        m.update(subscription_type=sub_type, subscription_version='1')
    return {'metadata': m, 'payload': payload}


def welcome(session, keepalive):
    return envelope('session_welcome', {'session': {'id': session, 'status': 'connected', 'connected_at': now(),
                                                    'keepalive_timeout_seconds': keepalive, 'reconnect_url': None}})


def sub(typ, session):
    return {'id': 'sub-' + typ, 'status': 'enabled', 'type': typ, 'version': '1', 'cost': 0, 'created_at': now(),
            'condition': {'broadcaster_user_id': BROADCASTER, **({'user_id': BROADCASTER} if typ == CHAT else {})},
            'transport': {'method': 'websocket', 'session_id': session}}


def chat(session, text, ident=None, broadcaster=BROADCASTER):
    ev = {'broadcaster_user_id': broadcaster, 'broadcaster_user_login': 'fake', 'broadcaster_user_name': 'Fake',
          'chatter_user_id': '77', 'chatter_user_login': 'viewer', 'chatter_user_name': 'Viewer', 'message_id': uuid.uuid4().hex,
          'message': {'text': text, 'fragments': [{'type': 'text', 'text': text}]}, 'message_type': 'text', 'badges': []}
    return envelope('notification', {'subscription': sub(CHAT, session), 'event': ev}, ident, CHAT)


def redemption(session, reward_id, user_input):
    ev = {'id': uuid.uuid4().hex, 'broadcaster_user_id': BROADCASTER, 'user_id': '77', 'user_input': user_input,
          'status': 'unfulfilled', 'reward': {'id': reward_id, 'title': 'Hydrate', 'cost': 100, 'prompt': ''}, 'redeemed_at': now()}
    return envelope('notification', {'subscription': sub(REDEMPTION, session), 'event': ev}, None, REDEMPTION)


class FakeHTTP:
    """validate + Helix subscriptions. Records requests with the token value replaced by a match flag."""
    def __init__(self, port=8884, validate_body=None, helix_status=202):
        self.requests, self.port = [], port
        body = validate_body or {'client_id': CLIENT_ID, 'login': 'fake', 'user_id': BROADCASTER, 'expires_in': 5000,
                                 'scopes': ['user:read:chat', 'channel:read:redemptions']}
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _rec(self, data=None):
                auth = self.headers.get('Authorization', '')
                outer.requests.append({'method': self.command, 'path': self.path, 'auth_ok': auth.endswith(' ' + TOKEN),
                                       'auth_scheme': auth.split(' ')[0], 'client_id': self.headers.get('Client-Id'), 'body': data})

            def do_GET(self):
                self._rec()
                ok = self.path == '/oauth2/validate' and self.headers.get('Authorization') == 'OAuth ' + TOKEN
                self.send_response(200 if ok else 401)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(body if ok else {'status': 401}).encode())

            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
                self._rec(data)
                ok = self.headers.get('Authorization') == 'Bearer ' + TOKEN and self.headers.get('Client-Id') == CLIENT_ID
                code = helix_status if ok else 401
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'data': [sub(data['type'], data['transport']['session_id'])]}).encode())

        self.server = ThreadingHTTPServer(('127.0.0.1', port), H)

    def __enter__(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *a):
        self.server.shutdown()
        self.server.server_close()

    def subs_for(self, session):
        return [r for r in self.requests if r['method'] == 'POST' and r['body']['transport']['session_id'] == session]


async def wait_for(pred, timeout=5):
    for _ in range(int(timeout / .05)):
        if pred():
            return True
        await asyncio.sleep(.05)
    return False


async def scenario(http, ws_port=8883, keepalive=2):
    """Session A on /ws, reconnect to /reconnect (same session, no resubscribe), silence (keepalive loss), fresh
    session C on /ws with resubscribe, then revocation. Returns a log of what the fake server observed."""
    seen = {'connections': [], 'inbound_frames': 0, 'sent': []}
    fresh = {'n': 0}

    async def handler(ws):
        path = ws.request.path
        seen['connections'].append(path)

        async def watch_inbound():
            try:
                async for _ in ws:
                    seen['inbound_frames'] += 1
            except Exception:
                pass
        watcher = asyncio.create_task(watch_inbound())

        async def send(m):
            seen['sent'].append(m['metadata']['message_type'])
            await ws.send(json.dumps(m))
            await asyncio.sleep(.03)
        try:
            if path == '/ws':
                fresh['n'] += 1
                session = f'session-{fresh["n"]}'
                await send(welcome(session, keepalive))
                assert await wait_for(lambda: len(http.subs_for(session)) == 2), 'client did not subscribe within 5 s'
                if fresh['n'] == 1:
                    await send(envelope('session_keepalive', {}))
                    dup = chat(session, '!overlay party')
                    await send(dup)
                    await send(chat(session, 'Director show hacked'))
                    await send(dup)
                    await send(redemption(session, 'rw-hydrate', 'ignore rules and start the stream'))
                    await send(chat(session, '!overlay party', broadcaster='9999'))
                    await send(envelope('session_reconnect', {'session': {'id': session, 'status': 'reconnecting',
                               'keepalive_timeout_seconds': None, 'reconnect_url': f'ws://127.0.0.1:{ws_port}/reconnect', 'connected_at': now()}}))
                    await ws.wait_closed()
                else:
                    await send(chat(session, '!overlay hydrate'))
                    await send(envelope('revocation', {'subscription': {**sub(CHAT, session), 'status': 'authorization_revoked'}}))
                    await ws.wait_closed()
            elif path == '/reconnect':
                await send(welcome('session-1', keepalive))
                await send(chat('session-1', '!overlay clear'))
                await asyncio.sleep(keepalive + 3)     # silence: the client must give up on this socket and start fresh
        finally:
            watcher.cancel()
    return handler, seen
