"""Independent contract checks; no acceptance or fake-server dependencies."""
import asyncio
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
import unittest
from unittest.mock import patch
import twitch_eventsub as t

class Safety(unittest.TestCase):
    def setUp(self):
        self.cfg = t.Config('client', 'channel', 'reader', {})
        self.a = t.Adapter(self.cfg, t.offline_endpoints(), lambda cue: self.fail('unexpected cue'))

    def envelope(self, ident, kind, payload):
        return {'metadata': {'message_id': ident, 'message_type': kind,
                'message_timestamp': datetime.now(timezone.utc).isoformat()}, 'payload': payload}

    def test_receipt_and_dedup_storage_stay_bounded(self):
        for i in range(3000):
            self.a.feed(self.envelope(str(i), 'session_keepalive', {}))
        self.assertLessEqual(len(self.a.trace), 200)
        self.assertLessEqual(len(self.a.seen), 2048)
        self.assertEqual(self.a.feed(self.envelope('2999', 'session_keepalive', {}))['result'], 'duplicate')

    def test_reconnect_query_does_not_enter_trace(self):
        secret = 'opaque-private-query'
        receipt = self.a.feed(self.envelope('r', 'session_reconnect',
                    {'session': {'reconnect_url': self.a.endpoints.ws+'?key='+secret}}))
        self.assertEqual(receipt['result'], 'reconnect')
        self.assertNotIn(secret, repr(self.a.trace))

    def test_reward_values_must_be_fixed_strings(self):
        for bad in ([], {}, 'viewer provided text'):
            with self.assertRaises(t.TwitchError):
                t.Config('client', 'channel', 'reader', {'reward': bad})

    def test_sink_refuses_unsupported_build_before_post(self):
        status = {'planner': 'rules', 'build_tag': 'unknown',
                  'models': {'codex': {'enabled': False, 'calls': 0}}}
        with patch.object(t, 'request', return_value=status) as request:
            with self.assertRaises(t.TwitchError):
                t.StreamAgentSink()('Director party')
            self.assertEqual(request.call_count, 1)

    def test_http_redirect_is_not_followed(self):
        visits = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                visits.append(self.path)
                self.send_response(302)
                self.send_header('Location', '/must-not-visit')
                self.end_headers()
        server = HTTPServer(('127.0.0.1', 0), Handler)
        worker = Thread(target=server.serve_forever)
        worker.start()
        try:
            with self.assertRaisesRegex(t.TwitchError, 'refused \\(302\\)'):
                t.request(f'http://127.0.0.1:{server.server_port}/start')
            self.assertEqual(visits, ['/start'])
        finally:
            server.shutdown()
            worker.join()
            server.server_close()


class Cleanup(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_closes_idle_socket(self):
        connected = asyncio.Event()
        closed = asyncio.Event()
        async def handler(ws):
            connected.set()
            await ws.wait_closed()
            closed.set()
        async with t.websockets.serve(handler, '127.0.0.1', 0) as server:
            port = server.sockets[0].getsockname()[1]
            cfg = t.Config('client', 'channel', 'reader', {})
            def validate(helix):
                helix.next_validation = t.time.monotonic() + 3600
            with patch.object(t.Helix, 'validate', validate):
                task = asyncio.create_task(t.run(cfg, t.offline_endpoints(port),
                                                lambda: 'independent-placeholder', lambda _: None))
                await asyncio.wait_for(connected.wait(), 2)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                await asyncio.wait_for(closed.wait(), 2)

if __name__ == '__main__': unittest.main()
