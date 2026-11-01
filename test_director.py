"""New practical boundaries and recovery checks; original suites are unchanged."""
import copy
import json
import io
import wave
from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch

from director import Conflict, Director, ROOT
import director_schema as s
from director_obs import ObsClient, ObsError, OwnedOBS, OVERLAY, SCENES, OWNED
from director_server import make_server
from director_simulator import SimulatedOBS
from director_voice import LocalVoice


class Engine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT, prefix='.director-test-')
        self.d = Director(data_dir=self.tmp.name, media_dir=Path(self.tmp.name)/'media')
    def tearDown(self): self.d.close(); self.tmp.cleanup()
    def do(self, action, **kwargs): return self.d.execute({'action': action, **kwargs}, self.d.version)
    def take(self):
        self.do('preview'); self.d.preview_ack(self.d.stage_id); self.do('take')

    def test_new_and_revised_creation_needs_preview_of_exact_revision(self):
        self.do('compose', title='<script>not code</script>', template='orbit')
        with self.assertRaises(ValueError): self.do('take')
        self.do('preview'); old = self.d.stage_id
        self.do('revise', color='#aabbcc', motion='slide', duration=5)
        with self.assertRaises(Conflict): self.d.preview_ack(old)
        with self.assertRaises(ValueError): self.do('take')
        self.take()
        self.assertEqual(self.d.program['composition']['elements'][-2]['text'], '<script>not code</script>')

    def test_schema_refuses_code_paths_nonfinite_unknown_fields_and_unbounded_cost(self):
        for value in ({'elements': [], 'html': '<div>'}, {'elements': [], 'duration': float('nan')},
                      {'elements': [], 'repeat': 10000}, {'elements': [{'id':'x','kind':'image','url':'https://bad'}]}):
            with self.subTest(value=value), self.assertRaises(ValueError): s.composition(value)
        for media in ('../private.wav', 'https://bad/video.mp4', '/tmp/a.wav'):
            with self.assertRaises(ValueError): self.do('stage_patch', fields={'media': media})
        before = self.d.staged
        with self.assertRaises(ValueError): self.do('stage_patch', fields={'layout':'arbitrary'})
        self.assertEqual(self.d.staged, before)

    def test_optimistic_revision_prevents_duplicate_take(self):
        old = self.d.version; self.do('compose', title='New')
        with self.assertRaises(Conflict): self.d.execute({'action':'clear'}, old)

    def test_pause_freezes_clock_timer_and_rejects_new_mutations(self):
        self.do('stage_patch', fields={'timer': {'kind':'countdown','seconds':90,'label':'Break'}}); self.take()
        self.do('pause', paused=True)
        clock = self.d.clock(); time.sleep(.02)
        self.assertEqual(clock, self.d.clock())
        with self.assertRaises(ValueError): self.do('compose', title='Cannot air')
        self.do('clear'); self.assertEqual(self.d.program['composition']['elements'], [])
        self.do('restore'); self.assertIsNotNone(self.d.timer_state)
        self.do('pause', paused=False); self.assertGreaterEqual(self.d.clock(), clock)

    def test_timer_controls_and_restore_preserve_previous_segment(self):
        self.do('stage_patch', fields={'timer':{'kind':'elapsed','seconds':0,'label':'Session'}, 'lower':{'title':'Guest','subtitle':'Maker'}}); self.take()
        self.do('timer_control', operation='pause'); self.assertFalse(self.d.timer_state['running'])
        self.do('timer_control', operation='reset'); self.assertEqual(self.d.timer_state['offset'],0)
        self.do('timer_control', operation='resume'); self.assertTrue(self.d.timer_state['running'])
        self.do('compose', title='Next'); self.take(); self.do('restore')
        self.assertEqual(self.d.program['lower']['title'],'Guest')

    def test_viewer_text_does_not_author_or_enter_overlay(self):
        self.do('stage_patch', fields={'vote':{'question':'Choose','options':['A','B']}}); self.take()
        self.assertEqual(self.d.audience('id','!vote 1')['result'],'input off')
        self.do('audience', enabled=True)
        for message in ('title HACKED','!vote 1 HACKED','Director show HACKED','!vote 9'):
            self.d.audience('id',message)
        self.assertNotIn('HACKED',json.dumps(self.d.render('program')))
        self.assertEqual(self.d.audience('id','!vote 1')['result'],'vote accepted')
        self.assertEqual(self.d.audience('id','!vote 2')['result'],'duplicate')
        self.assertEqual(self.d.vote_state['counts'],[1,0])
        self.do('vote_control',operation='close')
        self.assertEqual(self.d.audience('other','!vote 1')['result'],'vote closed')
        self.assertEqual(self.d.audience('id',cue='Director show HACKED')['result'],'rejected')
        self.assertEqual(self.d.audience('id',cue='Director party')['result'],'fixed cue accepted')
        self.assertEqual(self.d.alert['title'],'Celebration')

    def test_recipes_round_trip_revalidate_and_never_autotake(self):
        self.do('recipe_save',name='Friday'); self.do('compose',title='Next'); self.do('recipe_save',name='Friday',append=True)
        fresh = Director(data_dir=self.tmp.name)
        try:
            self.assertEqual(len(fresh.recipes['Friday']['steps']),2)
            fresh.execute({'action':'recipe_load','name':'Friday','index':1},fresh.version)
            self.assertEqual(fresh.staged['composition']['name'],'Next')
            self.assertEqual(fresh.program['composition']['elements'],[])
            with self.assertRaises(ValueError): fresh.execute({'action':'take'},fresh.version)
        finally: fresh.close()
        path=Path(self.tmp.name)/'recipes.json';path.write_text('[{"name":"evil","steps":[{"shell":"x"}]}]')
        fresh=Director(data_dir=self.tmp.name)
        self.assertFalse(fresh.recipes); self.assertIn('failed validation',fresh.error)

    def test_local_marker_export_is_csv_formula_safe(self):
        self.do('marker',label='=danger()')
        self.assertIn("'=danger()",self.d.markers_csv())
        self.assertNotIn('Twitch',self.d.markers_csv())

    def test_final_voice_requires_director_prefix_deduplicates_and_cannot_bypass_take(self):
        self.assertEqual(self.d.transcript('title ignored','1',True)['result'],'no director cue')
        self.assertEqual(self.d.transcript('Director, title Hello','2',False)['result'],'interim ignored')
        self.d.transcript('Director, title Hello','2',True)
        self.assertEqual(self.d.staged['composition']['name'],'Hello')
        self.assertEqual(self.d.transcript('Director, clear','2',True)['result'],'duplicate')
        with self.assertRaises(ValueError): self.d.transcript('Director, take','3',True)
        with self.assertRaises(ValueError): self.d.transcript('Director, enable program control','4',True)
        self.assertFalse(self.d.armed)

    def test_voice_never_discovers_home_model_and_rejects_playlists(self):
        voice = LocalVoice()
        self.assertFalse(voice.status()['ready'])
        with self.assertRaises(ValueError): LocalVoice('/outside-project/model.bin')
        with patch.object(voice, 'status', return_value={'ready': True}):
            with self.assertRaisesRegex(ValueError,'playlists'): voice.transcribe(b'#EXTM3U\n'+b'x'*60)

    def test_synthetic_silent_wav_is_not_sent_to_recognizer(self):
        buffer=io.BytesIO()
        with wave.open(buffer,'wb') as audio:
            audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000);audio.writeframes(b'\x00\x00'*16000)
        voice=LocalVoice()
        with patch.object(voice,'status',return_value={'ready':True}),patch('director_voice.subprocess.run') as process:
            result=voice.transcribe(buffer.getvalue())
            self.assertTrue(result['silence']);self.assertEqual(result['text'],'');process.assert_not_called()

    def test_repreview_restarts_preview_serial_and_invalidates_old_review(self):
        self.do('preview');self.d.preview_ack(self.d.stage_id)
        old=self.d.render('preview')['preview_serial']
        self.do('preview')
        self.assertGreater(self.d.render('preview')['preview_serial'],old)
        self.assertFalse(self.d.state()['previewed'])


class NativeIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT,prefix='.director-test-')
        self.sim = SimulatedOBS().__enter__()
        self.d = Director(data_dir=self.tmp.name,media_dir=Path(self.tmp.name)/'media')
        self.do('connect',password=self.sim.password,port=self.sim.port)
        self.do('setup',camera='Camera',content='Content')
        self.render_stop=threading.Event()
        def render_stub():
            while not self.render_stop.wait(.01):
                for bank in ('A','B'):
                    value=self.d.render('bank-'+bank)
                    try: self.d.bank_ack(bank,value['id'],value['serial'],'obs',**({'warm_epoch':value['warm_epoch']} if 'warm_epoch' in value else {}))
                    except Conflict: pass  # Publication can race fetch/ACK; real renderer polls again.
        self.render_worker=threading.Thread(target=render_stub);self.render_worker.start()
        self.do('arm',enabled=True)
    def tearDown(self):
        self.render_stop.set();self.render_worker.join(timeout=2)
        self.d.close(); self.sim.__exit__(); self.tmp.cleanup()
    def do(self, action, **kwargs): return self.d.execute({'action': action, **kwargs},self.d.version)
    def preview(self):
        self.do('preview',target='obs');self.d.preview_ack(self.d.stage_id)
        bank=self.d.native.prepared['bank'];value=self.d.render('bank-'+bank)
        self.d.bank_ack(bank,value['id'],value['serial'],'obs')

    def test_native_paired_layout_preview_take_and_full_restore_readback(self):
        before = self.d.native.snapshot()
        self.do('stage_patch',fields={'mode':'live','layout':'pip'});self.preview()
        self.assertEqual(self.sim.program,before['program'])
        self.assertIn(self.sim.preview,SCENES['live'])
        self.do('take');self.assertIn(self.sim.program,SCENES['live'])
        self.do('restore');self.assertEqual(self.d.native.snapshot(),before)
        self.assertFalse(set(self.sim.requests)&{'StartStream','StopStream','StartRecord','StopRecord','StartVirtualCam'})

    def test_external_scene_change_invalidates_take_and_disarms(self):
        self.preview();self.sim.preview='Scene'
        with self.assertRaises(ObsError): self.do('take')
        self.assertFalse(self.d.armed)
        self.assertNotEqual(self.sim.program,'Scene')

    def test_socket_disconnect_requires_explicit_reconnect_arm_and_restore(self):
        self.do('stage_patch',fields={'mode':'brb'});self.preview()
        self.sim.drop_on='SetCurrentProgramScene'
        with self.assertRaises(ObsError): self.do('take')
        self.assertFalse(self.d.armed); self.assertFalse(self.d.obs_state['connected'])
        self.assertTrue(self.d.state()['can_restore'])
        self.do('connect',password=self.sim.password,port=self.sim.port);self.do('arm',enabled=True)
        self.do('restore');self.assertIn(self.sim.program,OWNED)

    def test_source_collection_and_setup_output_guards(self):
        self.sim.active=True
        with self.assertRaises(ObsError): self.do('setup',camera='Camera',content='Content')
        self.sim.active=False;self.do('arm',enabled=True)
        self.sim.inputs[OVERLAY]['settings']['url']='http://foreign'
        with self.assertRaises(ObsError): self.preview()
        self.assertFalse(self.d.armed)

    def test_stale_wire_response_ignored_wrong_type_refused_and_auth_required(self):
        self.sim.stale_before_reply=True
        self.assertIn('scenes',self.d.native.req('GetSceneList'))
        self.sim.wrong_type=True
        with self.assertRaises(ObsError): self.do('refresh')
        with self.assertRaises(ObsError): ObsClient('wrong-synthetic-password',port=self.sim.port)
        with self.assertRaises(ObsError): self.d.native.req('StartStream')

    def test_owned_media_cap_stop_and_path_refusal(self):
        folder=Path(self.tmp.name)/'media';folder.mkdir();(folder/'owned.wav').write_bytes(b'synthetic-test-media')
        with self.assertRaises(ValueError): self.do('media_play',name='owned.wav',volume=.9)
        self.do('media_play',name='owned.wav',volume=.4)
        self.assertEqual(self.sim.volume,.4)
        self.do('media_stop');self.assertEqual(self.sim.volume,0)
        self.assertEqual(self.sim.media_state,'OBS_MEDIA_STATE_STOPPED')
        (folder/'escape.wav').symlink_to(ROOT/'README.md')
        with self.assertRaises(ValueError): self.do('media_play',name='escape.wav')

    def test_changed_geometry_after_preview_cannot_be_taken(self):
        self.do('stage_patch',fields={'mode':'live','layout':'pip'});self.preview()
        self.sim.scenes[self.sim.preview][0]['transform']['positionX']=123
        with self.assertRaisesRegex(ObsError,'layout changed'):self.do('take')
        self.assertFalse(self.d.armed)

    def test_partial_take_keeps_recovery_checkpoint(self):
        folder=Path(self.tmp.name)/'media';folder.mkdir();(folder/'owned.wav').write_bytes(b'synthetic-media')
        before=self.d.native.snapshot()
        self.do('stage_patch',fields={'mode':'brb','media':'owned.wav'});self.preview()
        self.sim.refuse_on='SetInputSettings'
        with self.assertRaises(ObsError):self.do('take')
        self.assertNotEqual(self.sim.program,before['program'])
        self.assertTrue(self.d.state()['can_restore']);self.assertFalse(self.d.armed)
        self.do('arm',enabled=True);self.do('restore')
        self.assertEqual(self.d.native.snapshot(),before)

    def test_restore_anchor_survives_complete_four_scene_cycle(self):
        before=self.d.native.snapshot();self.do('checkpoint')
        for mode in ('starting','live','brb','ending'):
            self.do('stage_patch',fields={'mode':mode,'layout':'pip'});self.preview();self.do('take')
        self.do('restore');self.assertEqual(self.d.native.snapshot(),before)

    def test_profile_change_disarms_without_scene_mutation(self):
        before=self.sim.program;self.sim.profile='Changed profile'
        with self.assertRaises(ObsError):self.do('refresh')
        self.assertFalse(self.d.armed);self.assertEqual(self.sim.program,before)

    def test_idle_probe_reports_loss_without_reconnect_or_replay(self):
        native=self.d.native
        self.sim.drop_on='GetProfileList'
        state=self.d.probe()
        self.assertFalse(state['obs']['connected']);self.assertFalse(state['armed'])
        self.assertIs(self.d.native,native)
        self.assertIn('uncertain',state['error'])


class HTTPIntegration(unittest.TestCase):
    def test_http_origin_revision_renderer_and_no_private_static_files(self):
        with tempfile.TemporaryDirectory(dir=ROOT,prefix='.director-test-') as tmp:
            d=Director(data_dir=tmp)
            server=make_server(0,d);worker=threading.Thread(target=server.serve_forever);worker.start()
            url=f'http://127.0.0.1:{server.server_port}'
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            def call(path,body=None,origin=None):
                headers={}
                if origin:headers['Origin']=origin
                if body is not None:headers['Content-Type']='application/json'
                req=urllib.request.Request(url+path,headers=headers,data=None if body is None else json.dumps(body).encode())
                with opener.open(req,timeout=3) as response:return response.read()
            try:
                health=json.loads(call('/api/health'));self.assertEqual(health['pid'],os.getpid())
                print(f'Verified temporary director HTTP PID {health["pid"]} port {health["port"]}; stopped by test teardown')
                for path in ('/../README.md','/.obs-private.json','/director.py'):
                    with self.assertRaises(urllib.error.HTTPError) as error:call(path)
                    self.assertEqual(error.exception.code,404)
                cmd={'expected':0,'command':{'action':'preview'}}
                with self.assertRaises(urllib.error.HTTPError) as error:call('/api/action',cmd)
                self.assertEqual(error.exception.code,403)
                call('/api/action',cmd,url)
                render=json.loads(call('/api/render?channel=preview'));self.assertTrue(render['review_requested'])
                call('/api/previewed',{'stage_id':render['id']},url)
                call('/api/action',{'expected':d.version,'command':{'action':'take'}},url)
                with self.assertRaises(urllib.error.HTTPError) as error:call('/api/action',cmd,url)
                self.assertEqual(error.exception.code,409)
                html=call('/').decode();self.assertIn('trusted Codex via bounded MCP',html)
                js=call('/render.js').decode();self.assertNotIn('.innerHTML',js);self.assertNotIn('eval(',js)
                self.assertNotIn('password',json.dumps(json.loads(call('/api/state'))))
            finally:
                d.close();server.shutdown();server.server_close();worker.join(timeout=3)
                self.assertFalse(worker.is_alive())

    def test_existing_twitch_adapter_feeds_only_fixed_cues_to_director(self):
        import twitch_eventsub as twitch
        from director_audience import DirectorSink
        with tempfile.TemporaryDirectory(dir=ROOT,prefix='.director-test-') as tmp:
            d=Director(data_dir=tmp);server=make_server(0,d)
            worker=threading.Thread(target=server.serve_forever);worker.start()
            try:
                # Independently constructed public EventSub envelopes; no fake/harness imports.
                cfg=twitch.Config('client','channel','reader',{})
                adapter=twitch.Adapter(cfg,twitch.offline_endpoints(),DirectorSink(server.server_port))
                def envelope(kind,payload,ident):
                    return {'metadata':{'message_type':kind,'message_id':ident,'message_timestamp':datetime.now(timezone.utc).isoformat(),
                            'subscription_type':twitch.CHAT,'subscription_version':'1'},'payload':payload}
                adapter.feed(envelope('session_welcome',{'session':{'id':'session'}},'welcome'))
                adapter.subscriptions={twitch.CHAT:'sub'};adapter.enabled=True
                d.execute({'action':'audience','enabled':True},d.version)
                sub={'id':'sub','type':twitch.CHAT,'version':'1','status':'enabled','condition':{'broadcaster_user_id':'channel','user_id':'reader'},
                     'transport':{'method':'websocket','session_id':'session'}}
                for i,message in enumerate(('!overlay party','title HACKED','!overlay party HACKED')):
                    adapter.feed(envelope('notification',{'subscription':sub,'event':{'broadcaster_user_id':'channel','message':{'text':message}}},str(i)))
                self.assertEqual(d.alert['title'],'Celebration')
                self.assertNotIn('HACKED',json.dumps(d.render('program')))
                with self.assertRaises(ValueError):DirectorSink(server.server_port)('arbitrary viewer text')
            finally:
                d.close();server.shutdown();server.server_close();worker.join(timeout=3)

if __name__ == '__main__': unittest.main()
