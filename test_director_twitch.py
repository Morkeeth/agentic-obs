"""Launcher wiring with simulated effects only; no Twitch or OBS connections."""
import contextlib
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import director_twitch as launcher
import twitch_eventsub as twitch
from director import Director
from director_audience import DirectorSink

SECRET = 'synthetic-secret-never-print'


class Launcher(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent, prefix='.director-test-')
        self.config = Path(self.tmp.name)/'public.json'
        self.config.write_text(json.dumps({'client_id': 'publicclient', 'broadcaster_user_id': '123', 'reader_user_id': '456', 'rewards': {}}))
        self.out = io.StringIO(); self.err = io.StringIO()
    def tearDown(self): self.tmp.cleanup()
    def invoke(self, *args):
        with contextlib.redirect_stdout(self.out), contextlib.redirect_stderr(self.err):
            return launcher.main(['--config', str(self.config), *args])
    def tty(self):
        return patch.object(launcher, '_interactive_terminal', return_value=True)

    def test_default_dry_run_cannot_call_transport_or_prompt_or_network(self):
        with patch.object(launcher, 'queue_run', side_effect=AssertionError('transport')), patch.object(launcher.getpass, 'getpass', side_effect=AssertionError('prompt')), patch('socket.socket', side_effect=AssertionError('network')):
            self.assertEqual(self.invoke('--enable-events'), 0)
        result = json.loads(self.out.getvalue())
        self.assertFalse(result['enabled']); self.assertTrue(result['dry_run'])

    def test_live_binds_unchanged_transport_and_existing_sink_with_explicit_flag(self):
        for enabled in (False, True):
            seen = []
            async def run(cfg, endpoints, provider, send, *, enabled, log):
                seen.append((cfg, endpoints, send, enabled, provider))
                self.assertEqual(provider(), SECRET)
                log(SECRET)  # Transport diagnostics must never reach public output.
                return type('Stopped', (), {'trace': [{'reason': SECRET}]})()
            with self.tty(), patch.object(launcher.getpass, 'getpass', return_value=SECRET), patch.object(launcher, 'queue_run', side_effect=run):
                self.assertEqual(self.invoke('--live', *(['--enable-events'] if enabled else [])), 0)
            cfg, endpoints, sink, flag, provider = seen[0]
            self.assertIsNone(provider(), "launcher must release its retained secret after run")
            self.assertIsInstance(cfg, twitch.Config); self.assertIs(endpoints, twitch.LIVE)
            self.assertIsInstance(sink, DirectorSink); self.assertEqual(sink.url, 'http://127.0.0.1:8880')
            self.assertEqual(flag, enabled)
        self.assertNotIn(SECRET, self.out.getvalue()+self.err.getvalue())

    def test_local_director_poll_receiver_flag_is_explicit_default_off_and_dry_run_safe(self):
        with patch.object(launcher,'queue_run',side_effect=AssertionError('transport')),patch('socket.socket',side_effect=AssertionError('network')):
            self.assertEqual(self.invoke(),0)
            self.assertFalse(json.loads(self.out.getvalue())['local_director_polls'])
            self.out.seek(0);self.out.truncate()
            self.assertEqual(self.invoke('--enable-local-director-polls'),0)
            self.assertTrue(json.loads(self.out.getvalue())['local_director_polls'])
        seen=[]
        async def run(cfg,endpoints,provider,send,**kwargs):seen.append(send.enable_local_director_polls)
        with self.tty(),patch.object(launcher.getpass,'getpass',return_value=SECRET),patch.object(launcher,'queue_run',side_effect=run):
            self.assertEqual(self.invoke('--live','--enable-events','--enable-local-director-polls'),0)
        self.assertEqual(seen,[True])
        self.assertNotIn(SECRET,self.out.getvalue()+self.err.getvalue())

    def test_rewards_rejected_before_prompt_or_transport(self):
        value = json.loads(self.config.read_text())
        value['rewards'] = {'existing-reward': 'Director party'}
        self.config.write_text(json.dumps(value))
        with self.tty(), patch.object(launcher.getpass, 'getpass') as prompt, patch.object(launcher, 'queue_run') as run:
            self.assertEqual(self.invoke(), 2)
            self.assertEqual(self.invoke('--live', '--enable-events'), 2)
            prompt.assert_not_called(); run.assert_not_called()

    def test_empty_and_missing_rewards_remain_chat_only(self):
        value = json.loads(self.config.read_text())
        for rewards in ({}, None):
            if rewards is None: value.pop('rewards', None)
            else: value['rewards'] = rewards
            self.config.write_text(json.dumps(value))
            self.assertEqual(launcher._config(self.config).types(), [twitch.CHAT])

    def test_non_tty_refused_without_prompt_or_transport(self):
        with patch.object(launcher, '_interactive_terminal', return_value=False), patch.object(launcher.getpass, 'getpass') as prompt, patch.object(launcher, 'queue_run') as run:
            self.assertEqual(self.invoke('--live'), 2)
            prompt.assert_not_called(); run.assert_not_called()

    def test_failure_and_getpass_fallback_are_sanitized(self):
        for failure in (RuntimeError(SECRET), KeyboardInterrupt(SECRET)):
            async def run(*args, **kwargs): raise failure
            with self.tty(), patch.object(launcher.getpass, 'getpass', return_value=SECRET), patch.object(launcher, 'queue_run', side_effect=run):
                self.assertNotEqual(self.invoke('--live'), 0)
        def fallback(*args, **kwargs):
            import warnings
            warnings.warn(SECRET, launcher.getpass.GetPassWarning)
            raise AssertionError('must not fall back to echo')
        with self.tty(), patch.object(launcher.getpass, 'getpass', side_effect=fallback), patch.object(launcher, 'queue_run') as run:
            self.assertEqual(self.invoke('--live'), 2); run.assert_not_called()
        self.assertNotIn(SECRET, self.out.getvalue()+self.err.getvalue())
        self.assertNotIn('Traceback', self.err.getvalue())

    def test_bad_config_and_secret_arguments_are_not_echoed(self):
        self.config.write_text(json.dumps({'token': SECRET}))
        self.assertEqual(self.invoke(), 2)
        self.assertEqual(self.invoke('--token', SECRET), 2)
        self.assertNotIn(SECRET, self.out.getvalue()+self.err.getvalue())

    def test_public_identity_and_port_validation_precede_secret_input(self):
        with self.tty(), patch.object(launcher.getpass, 'getpass') as prompt, patch.object(launcher, 'queue_run') as run:
            self.assertEqual(self.invoke('--live', '--port', '4455'), 2)
            value = json.loads(self.config.read_text())
            value['reader_user_id'] = 'not-numeric'
            self.config.write_text(json.dumps(value))
            self.assertEqual(self.invoke('--live'), 2)
            prompt.assert_not_called(); run.assert_not_called()

    def test_live_wiring_preserves_actual_adapter_matching_and_director_allowlist(self):
        director = Director(data_dir=Path(self.tmp.name)/'data', media_dir=Path(self.tmp.name)/'media')
        director.execute({'action': 'compose', 'title': 'Operator composition remains'}, director.version)
        director.execute({'action': 'preview', 'target': 'overlay'}, director.version)
        director.preview_ack(director.stage_id)
        director.execute({'action': 'take'}, director.version)
        before = director.program.copy()
        delivered = []; observed_effects = []
        class Reply:
            def __enter__(self): return io.BytesIO(b'{"result":"simulated"}')
            def __exit__(self, *args): pass
        class Opener:
            def open(self, request, timeout):
                self_outer.assertEqual(request.full_url, 'http://127.0.0.1:8880/api/chat-request')
                body = json.loads(request.data); delivered.append(body)
                director.enqueue_request(body)
                return Reply()
        self_outer = self
        async def run(cfg, endpoints, provider, send, *, enabled, log):
            from director_chat import QueueAdapter
            adapter = QueueAdapter(cfg, endpoints, send)
            def envelope(kind, payload, ident):
                return {'metadata': {'message_type': kind, 'message_id': ident, 'message_timestamp': datetime.now(timezone.utc).isoformat(), 'subscription_type': twitch.CHAT, 'subscription_version': '1'}, 'payload': payload}
            adapter.feed(envelope('session_welcome', {'session': {'id': 'session'}}, 'welcome'))
            adapter.subscriptions = {twitch.CHAT: 'sub'}; adapter.enabled = enabled
            sub = {'id': 'sub', 'type': twitch.CHAT, 'version': '1', 'status': 'enabled', 'condition': {'broadcaster_user_id': '123', 'user_id': '456'}, 'transport': {'method': 'websocket', 'session_id': 'session'}}
            counter=[1000]
            def chat(text, ident, subscription=sub):
                counter[0]+=1
                return adapter.feed(envelope('notification', {'subscription': subscription, 'event': {'broadcaster_user_id': '123', 'chatter_user_id':str(counter[0]), 'message': {'text': text}}}, ident))
            chat('!overlay party', 'disabled-controller')
            self.assertIsNone(director.alert)
            director.execute({'action': 'audience', 'enabled': True}, director.version)
            chat('!overlay party', 'party'); observed_effects.append(director.alert)
            chat('!overlay hydrate', 'hydrate'); self.assertIsNone(director.alert)
            for i, text in enumerate(('!overlay party arbitrary', '!overlay Hydrate', 'make a title', '!overlay clear extra')):
                chat(text, str(i))
            wrong = {**sub, 'condition': {'broadcaster_user_id': '123', 'user_id': '999'}}
            self.assertEqual(chat('!overlay clear', 'wrong-reader', wrong)['result'], 'rejected')
            chat('!overlay clear', 'clear'); self.assertIsNone(director.alert)
            self.assertEqual(director.program, before)
            self.assertFalse(director.armed)
            return adapter
        try:
            with self.tty(), patch.object(launcher.getpass, 'getpass', return_value=SECRET), patch.object(launcher, 'queue_run', side_effect=run), patch('director_audience.urllib.request.build_opener', return_value=Opener()):
                self.assertEqual(self.invoke('--live', '--enable-events'), 0)
            self.assertIsNone(observed_effects[0], 'viewer request must wait for operator acceptance')
            self.assertEqual(len(delivered),8)
            self.assertEqual(len(director.requests.view()),7)
        finally: director.close()


if __name__ == '__main__': unittest.main()
