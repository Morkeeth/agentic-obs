import base64
import json
import threading
import unittest
import urllib.request
import urllib.error
from server import make_server
from streamer import Show
from obs import RehearsalNative

class HttpTests(unittest.TestCase):
    def setUp(self):
        self.server = make_server(Show(RehearsalNative()), port=0, transcribe=lambda _: 'Demo the demo')
        self.worker = threading.Thread(target=self.server.serve_forever); self.worker.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)
    def tearDown(self):
        self.server.shutdown(); self.worker.join(); self.server.server_close()
    def request(self, path, body=None, origin=True):
        headers = {'Content-Type':'application/json'}
        if origin: headers['Origin'] = self.url
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
        with urllib.request.urlopen(req) as response: return json.load(response)
    def test_http_five_shots(self):
        state = self.request('/api/state'); self.assertFalse(state['enabled'])
        self.request('/api/enable', {})
        reply = self.request('/api/direct', {'text':'Help me demo the demo'})
        self.assertEqual(reply['native_writes'], 0)
        token = self.request('/api/voice/start', {})['token']
        voice = self.request('/api/voice/finish', {'token':token,'audio':base64.b64encode(b'synthetic audio').decode()})
        self.assertEqual(voice['transcript'], 'Demo the demo')
        self.assertGreaterEqual(voice['latency_ms'], 0)
        self.assertTrue(voice['state']['native']['graphics']['visible'])
        self.assertEqual(voice['state']['native']['program'], 'Camera')
        stage = self.request('/api/stage', {'title':reply['proposal']['title']})
        self.assertTrue(stage['native']['graphics']['visible'])
        self.assertFalse(self.request('/api/clear', {})['native']['graphics']['visible'])
        self.assertTrue(self.request('/api/restore', {})['native']['graphics']['visible'])
    def test_disabled_voice_can_answer_but_must_not_claim_staging(self):
        token = self.request('/api/voice/start', {})['token']
        reply = self.request('/api/voice/finish', {'token':token,'audio':base64.b64encode(b'audio').decode()})
        self.assertFalse(reply['staged'])
        self.assertFalse(reply['state']['native']['graphics']['visible'])

    def test_unknown_take_and_missing_origin_fail(self):
        for path,origin in (('/api/take',True),('/api/enable',False)):
            with self.assertRaises(urllib.error.HTTPError) as err: self.request(path, {}, origin)
            self.assertIn(err.exception.code, (403,404))
    def test_chat_cannot_impersonate_operator(self):
        with self.assertRaises(urllib.error.HTTPError): self.request('/api/direct', {'text':'anything','source':'chat'})
    def test_bad_body_is_json_error_not_disconnection(self):
        req = urllib.request.Request(self.url+'/api/direct', data=b'[]', headers={'Origin':self.url,'Content-Type':'application/json'})
        with self.assertRaises(urllib.error.HTTPError) as err: urllib.request.urlopen(req)
        self.assertEqual(err.exception.code,400)
        self.assertIn('error', json.load(err.exception))
    def test_static_does_not_serve_repository_or_secrets(self):
        for path in ('/.git/config','/streamer.py','/../.obs-private.json'):
            with self.assertRaises(urllib.error.HTTPError): self.request(path)

if __name__ == '__main__': unittest.main()

class LiveHttpTests(HttpTests):
    def test_typed_endpoint_cannot_impersonate_voice_take(self):
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/direct',{'text':'take it','source':'voice'})
    def test_title_clear_restore_use_live_preview_bank(self):
        from live import LiveStudio
        from test_live import Native
        self.server.show.live=LiveStudio(Native(),['s']);self.request('/api/enable',{})
        r=self.request('/api/stage',{'title':'TwitchCon live'});self.assertEqual(r['live']['composition']['lower_third'],'TwitchCon live')
        r=self.request('/api/clear',{});self.assertEqual(r['live']['composition']['lower_third'],'')
        r=self.request('/api/restore',{});self.assertEqual(r['live']['composition']['lower_third'],'TwitchCon live')

class TwitchCommandHttpTests(HttpTests):
    def test_operator_can_opt_in_but_cannot_inject_chat_via_http(self):
        r=self.request('/api/twitch/commands',{'enabled':True});self.assertTrue(r['enabled'])
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/twitch/inject',{'text':'!brb'})
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/twitch/commands',{'enabled':'true'})
