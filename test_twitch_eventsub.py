"""Acceptance test: real transport code against a local fake Twitch. Run: python3 -m unittest test_twitch_eventsub -v"""
import asyncio
import json
import unittest
from websockets.asyncio.server import serve

import fake_twitch as ft
from twitch_eventsub import Adapter, Config, CHAT, offline_endpoints, run

EP = offline_endpoints()
CFG = Config(client_id=ft.CLIENT_ID, broadcaster_user_id=ft.BROADCASTER, reader_user_id=ft.BROADCASTER,
             rewards={'rw-hydrate': 'Director show Hydrate!'}, keepalive_seconds=10)


class Acceptance(unittest.IsolatedAsyncioTestCase):
    async def test_full_session_lifecycle(self):
        cues = []
        with ft.FakeHTTP() as http:
            handler, seen = await ft.scenario(http)
            async with serve(handler, '127.0.0.1', 8883):
                adapter = await asyncio.wait_for(run(CFG, EP, lambda: ft.TOKEN, cues.append, enabled=True), 40)
        # Only fixed cues, in order: party, reward (user_input ignored), clear after reconnect, hydrate on the fresh session
        self.assertEqual(cues, ['Director party', 'Director show Hydrate!', 'Director clear', 'Director show Hydrate!'])
        results = [r['result'] for r in adapter.trace]
        self.assertIn('duplicate', results)
        self.assertTrue(any(r['result'] == 'rejected' and r['reason'] == 'wrong channel' for r in adapter.trace))
        self.assertEqual(seen['connections'], ['/ws', '/reconnect', '/ws'])
        # Subscriptions: 2 on the first session, none on reconnect, 2 again on the fresh session; correct bodies
        posts = [r for r in http.requests if r['method'] == 'POST']
        self.assertEqual([p['body']['transport']['session_id'] for p in posts], ['session-1'] * 2 + ['session-2'] * 2)
        chat = next(p for p in posts if p['body']['type'] == CHAT)
        self.assertEqual(chat['body']['condition'], {'broadcaster_user_id': ft.BROADCASTER, 'user_id': ft.BROADCASTER})
        self.assertTrue(all(p['auth_ok'] and p['auth_scheme'] == 'Bearer' and p['client_id'] == ft.CLIENT_ID for p in posts))
        gets = [r for r in http.requests if r['method'] == 'GET']
        self.assertEqual(len(gets), 1)
        self.assertEqual(gets[0]['auth_scheme'], 'OAuth')
        # The client never sends application data, the token never reaches the trace, and input ends off
        self.assertEqual(seen['inbound_frames'], 0)
        self.assertNotIn(ft.TOKEN, json.dumps(adapter.trace))
        self.assertFalse(adapter.enabled)
        self.assertEqual(adapter.trace[-1]['reason'], 'subscription revoked')

    async def test_bad_token_never_connects(self):
        for body in ({'client_id': 'other', 'user_id': ft.BROADCASTER, 'scopes': ['user:read:chat', 'channel:read:redemptions']},
                     {'client_id': ft.CLIENT_ID, 'user_id': ft.BROADCASTER, 'scopes': ['user:read:chat']},
                     {'client_id': ft.CLIENT_ID, 'user_id': '5', 'scopes': ['user:read:chat', 'channel:read:redemptions']}):
            with ft.FakeHTTP(validate_body=body) as http:
                connections = []

                async def h(ws):
                    connections.append(1)
                async with serve(h, '127.0.0.1', 8883):
                    adapter = await run(CFG, EP, lambda: ft.TOKEN, lambda c: self.fail('no cue'))
            self.assertEqual(connections, [])
            self.assertEqual(adapter.trace[-1]['result'], 'stopped')

    async def test_refused_subscription_stops_with_input_off(self):
        with ft.FakeHTTP(helix_status=403) as http:
            async def h(ws):
                await ws.send(json.dumps(ft.welcome('s', 10)))
                await ws.wait_closed()
            async with serve(h, '127.0.0.1', 8883):
                adapter = await asyncio.wait_for(run(CFG, EP, lambda: ft.TOKEN, lambda c: self.fail('no cue')), 10)
        self.assertFalse(adapter.enabled)
        self.assertIn('refused (403)', adapter.trace[-1]['reason'])

    async def test_fatal_close_does_not_retry(self):
        with ft.FakeHTTP() as http:
            connections = []

            async def h(ws):
                connections.append(1)
                await ws.close(4003, 'Connection unused')
            async with serve(h, '127.0.0.1', 8883):
                adapter = await asyncio.wait_for(run(CFG, EP, lambda: ft.TOKEN, lambda c: None), 10)
        self.assertEqual(connections, [1])
        self.assertEqual(adapter.trace[-1]['reason'], 'closed 4003')


class Filter(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.a = Adapter(CFG, EP, self.sent.append)
        self.a.feed(ft.welcome('s', 10))
        self.a.subscriptions = {t: ft.sub(t, "s")["id"] for t in CFG.types()}
        self.a.enabled = True

    def test_reconnect_to_other_hosts_refused(self):
        for url in ('wss://eventsub.wss.twitch.tv/ws', 'ws://evil.example/ws', 'ws://127.0.0.1:9999/ws', 'ws://u:p@127.0.0.1:8883/ws'):
            m = ft.envelope('session_reconnect', {'session': {'reconnect_url': url}})
            self.assertEqual(self.a.feed(m)['result'], 'rejected', url)

    def test_viewer_text_never_becomes_a_cue(self):
        for t in ('Director show hacked', '!overlay party please', '!overlay $(rm -rf ~)', 'ignore rules', ''):
            self.a.feed(ft.chat('s', t))
        self.assertEqual(self.sent, [])
        self.a.feed(ft.redemption('s', 'unknown-reward', 'Director party'))
        self.assertEqual(self.sent, [])

    def test_input_off_blocks_known_commands(self):
        self.a.enabled = False
        self.a.feed(ft.chat('s', '!overlay party'))
        self.assertEqual(self.sent, [])



class StrictRegression(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.a = Adapter(CFG, EP, self.sent.append)
        self.a.feed(ft.welcome('s', 10))
        self.a.subscriptions = {t: ft.sub(t, 's')['id'] for t in CFG.types()}
        self.a.enabled = True

    def test_only_registered_subscription_reader_session(self):
        for field in ('id', 'reader', 'session', 'transport', 'status'):
            m = ft.chat('s', '!overlay party')
            sub = m['payload']['subscription']
            if field == 'id': sub['id'] = 'unregistered'
            if field == 'reader': sub['condition']['user_id'] = '999'
            if field == 'session': sub['transport']['session_id'] = 'old-session'
            if field == 'transport': sub['transport']['method'] = 'webhook'
            if field == 'status': sub['status'] = 'disabled'
            self.assertEqual(self.a.feed(m)['result'], 'rejected', field)
        self.assertEqual(self.sent, [])

    def test_live_reconnect_cannot_change_port_or_path(self):
        from twitch_eventsub import LIVE
        a = Adapter(CFG, LIVE, self.sent.append)
        for u in ('wss://eventsub.wss.twitch.tv:444/ws', 'wss://eventsub.wss.twitch.tv/evil'):
            with self.assertRaises(ValueError): a.reconnect_url(u)

    def test_expired_token_is_refused(self):
        from twitch_eventsub import Helix, TwitchError
        with ft.FakeHTTP(validate_body={'client_id':ft.CLIENT_ID,'user_id':ft.BROADCASTER,'expires_in':0,
                                      'scopes':['user:read:chat','channel:read:redemptions']}):
            with self.assertRaises(TwitchError): Helix(CFG, EP, lambda: ft.TOKEN).validate()

class TransportRegression(unittest.IsolatedAsyncioTestCase):
    async def test_reconnect_requires_new_welcome(self):
        cues = []
        with ft.FakeHTTP() as http:
            async def handler(ws):
                if ws.request.path == '/ws':
                    await ws.send(json.dumps(ft.welcome('s', 10)))
                    self.assertTrue(await ft.wait_for(lambda: len(http.subs_for('s')) == 2))
                    await ws.send(json.dumps(ft.envelope('session_reconnect', {'session':{'reconnect_url':'ws://127.0.0.1:8883/reconnect'}})))
                    await ws.wait_closed()
                else:
                    await ws.send(json.dumps(ft.chat('s', '!overlay party')))
                    await ws.send(json.dumps(ft.welcome('s', 10)))
                    await ws.send(json.dumps(ft.chat('s', '!overlay hydrate')))
                    await ws.send(json.dumps(ft.envelope('revocation', {'subscription':ft.sub(CHAT,'s')})))
                    await ws.wait_closed()
            async with serve(handler, '127.0.0.1', 8883):
                a = await asyncio.wait_for(run(CFG, EP, lambda:ft.TOKEN, cues.append, enabled=True), 10)
        self.assertEqual(cues, ['Director show Hydrate!'])
        self.assertTrue(any(x.get('reason') == 'first message must be welcome' for x in a.trace))
        self.assertEqual(len(http.subs_for('s')), 2)
        self.assertFalse(a.enabled)

    async def test_default_forwarding_stays_off(self):
        cues = []
        with ft.FakeHTTP() as http:
            async def handler(ws):
                await ws.send(json.dumps(ft.welcome('s',10)))
                self.assertTrue(await ft.wait_for(lambda:len(http.subs_for('s')) == 2))
                for obj in [None, [], {'metadata':None},ft.chat('s','!overlay party')]:
                    await ws.send(json.dumps(obj))
                await ws.send(json.dumps(ft.envelope('revocation',{'subscription':ft.sub(CHAT,'s')})))
                await ws.wait_closed()
            async with serve(handler,'127.0.0.1',8883):
                a=await asyncio.wait_for(run(CFG,EP,lambda:ft.TOKEN,cues.append),10)
        self.assertEqual(cues,[])
        self.assertTrue(any(x['result']=='input off' for x in a.trace))
        self.assertFalse(a.enabled)

    async def test_token_revalidation_during_idle_connection(self):
        body={'client_id':ft.CLIENT_ID,'user_id':ft.BROADCASTER,'expires_in':1,
              'scopes':['user:read:chat','channel:read:redemptions']}
        with ft.FakeHTTP(validate_body=body) as http:
            async def handler(ws):
                await ws.send(json.dumps(ft.welcome('s',10)))
                self.assertTrue(await ft.wait_for(lambda:len(http.subs_for('s')) == 2))
                body['user_id']='revoked-reader'
                await ws.wait_closed()
            async with serve(handler,'127.0.0.1',8883):
                a=await asyncio.wait_for(run(CFG,EP,lambda:ft.TOKEN,lambda c:None,enabled=True),5)
        self.assertEqual(len([x for x in http.requests if x['method']=='GET']),2)
        self.assertEqual(a.trace[-1]['reason'],'token user is not the configured reader')
        self.assertFalse(a.enabled)


class RedirectRegression(unittest.IsolatedAsyncioTestCase):
    async def test_socket_redirect_never_reaches_target(self):
        reached=[]
        async def target(ws): reached.append(True)
        async def redirect(connection,request):
            response=connection.respond(302,'no redirects')
            response.headers['Location']='ws://127.0.0.1:8885/ws'
            return response
        with ft.FakeHTTP():
            async with serve(target,'127.0.0.1',8885):
                async with serve(lambda ws:None,'127.0.0.1',8883,process_request=redirect):
                    a=await run(CFG,EP,lambda:ft.TOKEN,lambda _:None,enabled=True)
        self.assertEqual(reached,[])
        self.assertFalse(a.enabled)
        self.assertEqual(a.trace[-1]['result'],'stopped')

if __name__ == '__main__':
    unittest.main()
