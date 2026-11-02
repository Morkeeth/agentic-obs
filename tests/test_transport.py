import json
import unittest
from unittest.mock import patch
from transport import CodexDirector, Whisper, VoiceSession
from streamer import Refused, Show
from test_director import Native

class TransportTests(unittest.TestCase):
    def test_codex_uses_schema_read_only_and_ephemeral(self):
        def run(command, **kw):
            self.assertIn('read-only', command)
            self.assertIn('--ephemeral', command)
            self.assertIn('--ignore-user-config', command)
            self.assertNotIn('--dangerously-bypass-approvals-and-sandbox', command)
            self.assertIn('operator', kw['input'])
            out = command[command.index('--output-last-message') + 1]
            with open(out, 'w') as f: json.dump({'answer':'Ready', 'proposal':{'title':'Demo the demo'}}, f)
            return type('Result', (), {'returncode':0})()
        with patch('transport.subprocess.run', side_effect=run):
            self.assertEqual(CodexDirector().ask('operator direction', {})['answer'], 'Ready')
    def test_codex_failure_is_not_replaced_by_fake_answer(self):
        with patch('transport.subprocess.run', side_effect=TimeoutError):
            with self.assertRaises(Refused): CodexDirector().ask('Hello', {})
    def test_voice_needs_explicit_start_and_final_capture(self):
        voice = VoiceSession(Show(Native()), lambda audio: 'Demo the demo')
        with self.assertRaises(Refused): voice.finish(b'audio', 'x')
        token = voice.start()
        reply = voice.finish(b'audio', token)
        self.assertEqual(reply['transcript'], 'Demo the demo')
        self.assertEqual(reply['source'], 'voice')
        with self.assertRaises(Refused): voice.finish(b'audio', token)
    def test_voice_cancel_discards_inflight_transcript(self):
        voice = None
        def transcribe(audio):
            voice.cancel()
            return 'Demo the demo'
        voice = VoiceSession(Show(Native()), transcribe)
        token = voice.start()
        with self.assertRaises(Refused): voice.finish(b'audio', token)
    def test_voice_cancel_during_director_discards_answer(self):
        show = Show(Native())
        voice = VoiceSession(show, lambda _: 'Demo')
        original = show.director.ask
        def ask(*args):
            voice.cancel()
            return original(*args)
        show.director.ask = ask
        token = voice.start()
        with self.assertRaises(Refused): voice.finish(b'audio', token)
    def test_voice_overlarge_clip_refused_before_transcription(self):
        voice = VoiceSession(Show(Native()), lambda _: self.fail('transcribed'))
        token = voice.start()
        with self.assertRaises(Refused): voice.finish(b'x' * (2_000_001), token)
    def test_whisper_missing_model_fails_without_shell(self):
        with self.assertRaises(Refused): Whisper('/does/not/exist')(b'audio')

if __name__ == '__main__': unittest.main()

class WarmWhisperTests(unittest.TestCase):
    def test_decoded_silence_is_refused_before_transcription(self):
        import io,wave
        from transport import voiced_pcm
        b=io.BytesIO()
        with wave.open(b,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0\0'*16000)
        self.assertFalse(voiced_pcm(b.getvalue()))
        b=io.BytesIO()
        with wave.open(b,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\x00\x20'*16000)
        self.assertTrue(voiced_pcm(b.getvalue()))
    def test_warm_whisper_posts_actual_wav_to_loopback_service(self):
        import http.server,threading
        from transport import infer_wav
        received=[]
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                received.append((self.path,self.rfile.read(int(self.headers['Content-Length']))));self.send_response(200);self.end_headers();self.wfile.write(b'{"text":"zoom in on me"}')
        s=http.server.HTTPServer(('127.0.0.1',0),Handler);t=threading.Thread(target=s.handle_request);t.start()
        try:self.assertEqual(infer_wav(b'RIFF real decoded waveform',s.server_port),'zoom in on me')
        finally:t.join();s.server_close()
        self.assertEqual(received[0][0],'/inference');self.assertIn(b'RIFF real decoded waveform',received[0][1])
