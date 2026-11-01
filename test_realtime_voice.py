import base64
import io
import json
import os
from pathlib import Path
import threading
import unittest
import urllib.error
import urllib.request
import wave

from director import Director
from director_server import make_server


def fixture():
    # Own synthetic PCM fixture; no microphone, voice, TTS service or media player.
    return Path(os.environ.get('REALTIME_TEST_WAV', str(Path(__file__).parent/'fixtures/realtime-tone.wav'))).read_bytes()


class VoiceRoute(unittest.TestCase):
    def test_voice_page_is_available_without_opening_any_device(self):
        server = make_server(0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/voice.html') as reply:
                self.assertIn(b'Hold to talk', reply.read())
        finally:
            server.shutdown(); server.director.close(); server.server_close(); thread.join()


class Protocol(unittest.TestCase):
    def setUp(self):
        from director_realtime import RealtimeDirector, wav_from_pcm
        self.director = Director(port=0)
        self.sent = []
        self.closed = False
        self.events = [
            {'type': 'session.created'}, {'type': 'session.updated'},
            {'type': 'response.output_audio_transcript.delta', 'delta': 'Preview the layout before you Take.'},
            {'type': 'response.output_audio.delta', 'delta': base64.b64encode(b'\x00\x01'*2400).decode()},
            {'type': 'response.done', 'response': {'status': 'completed'}},
        ]
        owner = self
        class Socket:
            def send(self, event): owner.sent.append(json.loads(event))
            def recv(self): return json.dumps(owner.events.pop(0))
            def close(self): owner.closed = True
        self.connect_calls = []
        def connect(url, **kwargs):
            self.connect_calls.append((url, kwargs)); return Socket()
        self.voice = RealtimeDirector(self.director, 'fixture-key-not-a-secret', connect)

    def tearDown(self):
        self.voice.close(); self.director.close()

    def test_fixture_audio_uses_real_protocol_and_receives_spoken_guidance(self):
        result = self.voice.turn(fixture())
        self.assertEqual(result['model'], 'gpt-realtime-2.1')
        self.assertIn('Preview', result['text'])
        with wave.open(io.BytesIO(base64.b64decode(result['audio_wav']))) as audio:
            self.assertEqual(audio.getframerate(), 24000)
            self.assertEqual(audio.getnframes(), 2400)
        session = self.sent[0]['session']
        self.assertIsNone(session['audio']['input']['turn_detection'])
        self.assertEqual(session['output_modalities'], ['audio'])
        types = [e['type'] for e in self.sent]
        self.assertLess(types.index('input_audio_buffer.append'), types.index('input_audio_buffer.commit'))
        self.assertLess(types.index('input_audio_buffer.commit'), types.index('response.create'))
        self.assertEqual(session['tools'][0]['name'], 'stage_visual')
        self.assertNotIn('viewer', self.sent[1]['item']['content'][0]['text'])

    def test_malformed_audio_never_opens_provider(self):
        with self.assertRaises(ValueError): self.voice.turn(b'not audio')
        self.assertFalse(self.connect_calls)

    def test_disabled_provider_has_no_key_discovery_or_fallback(self):
        from director_realtime import RealtimeDirector
        voice = RealtimeDirector(self.director)
        with self.assertRaises(ValueError): voice.turn(fixture())
        self.assertFalse(voice.status()['enabled'])

    def test_voice_cannot_take_arm_or_start_output(self):
        for name in ['take', 'arm', 'start_recording', 'connect', 'approve']:
            result = self.voice._stage({'name': name, 'arguments': '{}'})
            self.assertIn('error', result)
        self.assertFalse(self.director.armed)
        self.assertFalse(self.director.operator_approval)

    def test_stale_stage_does_not_fetch_and_replace_the_expected_version(self):
        result = self.voice._stage({'name': 'stage_visual', 'arguments': json.dumps({
            'expected_version': -1, 'fields': {'layout': 'pip'}})})
        self.assertIn('error', result)

    def test_valid_voice_stage_uses_existing_director_validation_and_stays_off_air(self):
        before = self.director.agent_state()
        result = self.voice._stage({'name': 'stage_visual', 'arguments': json.dumps({
            'expected_version': before['version'], 'fields': {'layout': 'pip'}})})
        self.assertTrue(result.get('staged'), result)
        self.assertFalse(result['on_air_changed'])
        self.assertFalse(self.director.armed)

    def test_provider_failure_closes_without_retry_or_secret_in_error(self):
        self.events = [{'type': 'error', 'error': {'message': 'DO NOT PRINT PROVIDER DETAIL'}}]
        with self.assertRaisesRegex(ValueError, 'provider refused') as caught:
            self.voice.turn(fixture())
        self.assertNotIn('PROVIDER DETAIL', str(caught.exception))
        self.assertTrue(self.closed)
        self.assertEqual(len(self.connect_calls), 1)

    def test_forged_take_through_whole_voice_turn_is_refused(self):
        self.events = [
            {'type': 'response.function_call_arguments.done', 'name': 'take', 'arguments': '{}', 'call_id': 'fixture-call'},
            {'type': 'response.done', 'response': {'status': 'completed'}},
        ] + self.events[2:]
        self.voice.turn(fixture())
        outputs = [e['item'] for e in self.sent if e['type'] == 'conversation.item.create' and e['item']['type'] == 'function_call_output']
        self.assertIn('error', json.loads(outputs[0]['output']))
        self.assertFalse(self.director.armed)
        self.assertFalse(self.director.operator_approval)

    def test_stop_closes_session(self):
        self.voice.turn(fixture()); self.voice.close()
        self.assertTrue(self.closed)
        self.assertIsNone(self.voice._socket)

    def test_stop_during_slow_connect_cannot_send_audio_afterwards(self):
        from director_realtime import RealtimeDirector
        owner = self
        class Socket:
            def close(self): owner.closed = True
            def send(self, _): owner.fail('Nothing may be sent after Stop during connect')
        def connect(*args, **kwargs):
            self.voice.close()
            return Socket()
        self.voice._connect = connect
        with self.assertRaisesRegex(ValueError, 'stopped while connecting'):
            self.voice.turn(fixture())
        self.assertTrue(self.closed)

    def test_fixture_audio_through_actual_http_route_and_origin_guard(self):
        server = make_server(0, director=self.director, realtime=self.voice)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        url = f'http://127.0.0.1:{server.server_port}'
        try:
            bad = urllib.request.Request(url+'/api/realtime-turn', data=fixture(),
                headers={'Content-Type': 'audio/wav', 'Origin': 'https://untrusted.example'})
            with self.assertRaises(urllib.error.HTTPError) as denied: urllib.request.urlopen(bad)
            self.assertEqual(denied.exception.code, 403)
            self.assertFalse(self.connect_calls)
            request = urllib.request.Request(url+'/api/realtime-turn', data=fixture(),
                headers={'Content-Type': 'audio/wav', 'Origin': url})
            with urllib.request.urlopen(request) as reply: result = json.load(reply)
            self.assertIn('Preview', result['text'])
            self.assertTrue(result['audio_wav'])
        finally:
            server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__': unittest.main()
