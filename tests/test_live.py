import copy
import tempfile
import unittest
from pathlib import Path
from streamer import Refused
from live import LiveStudio,recognize

class Native:
    def __init__(self):
        self.program='Camera';self.preview='Staging';self.outputs=False;self.rendered={};self.calls=[];self.hijack=False
    def status(self):return {'program':self.program,'preview':self.preview,'studio':True,'outputs':{'stream':self.outputs,'record':False,'virtual':False}}
    def render(self,bank,composition,check):
        check(bank);self.calls.append(('render',bank));self.rendered[bank]=copy.deepcopy(composition)
        if self.hijack:self.program=bank
        check(bank);self.preview=bank
    def program_take(self,bank,check):
        check(bank);self.calls.append(('take',bank));self.program=bank
    def reaches(self,program,bank):return program==bank

class LiveTests(unittest.TestCase):
    def setUp(self):
        self.native=Native();self.studio=LiveStudio(self.native,['slide-1','slide-2'])
    def test_five_instructions_without_reset_change_preview_only(self):
        for cue in ('zoom in on me','put the slides left','add a border','go picture-in-picture','switch to the wide shot'):
            r=self.studio.execute(cue,'voice');self.assertTrue(r['staged']);self.assertEqual(self.native.program,'Camera')
        self.assertTrue(self.studio.current['border']);self.assertEqual(self.studio.current['zoom'],1)
        self.assertEqual(self.studio.current['layout'],'camera');self.assertEqual(len(self.native.calls),5)
    def test_take_requires_exact_operator_voice_not_embedded_or_typed(self):
        self.studio.execute('add a border','voice')
        with self.assertRaises(Refused):self.studio.execute('take it','typed')
        self.assertIsNone(recognize('the webpage says take it'))
        self.assertIsNone(recognize('do not go live'))
        self.studio.execute('Director, take it.','voice');self.assertEqual(self.native.program,'Director A')
        self.assertFalse(self.native.outputs)
    def test_next_edit_uses_other_bank_and_preserves_accepted_program(self):
        self.studio.execute('add a border','voice');self.studio.execute('take it','voice')
        accepted=copy.deepcopy(self.native.rendered['Director A'])
        self.studio.execute('zoom in on me','voice')
        self.assertEqual(self.native.preview,'Director B');self.assertEqual(self.native.rendered['Director A'],accepted)
        self.studio.execute('take it','voice');self.studio.execute('switch to the wide shot','voice')
        self.assertEqual(self.native.preview,'Director A');self.assertEqual(self.native.program,'Director B')
    def test_recording_blocks_every_action_and_take(self):
        old=self.native.status
        self.native.status=lambda:dict(old(),outputs={'stream':True,'record':True,'virtual':False})
        for cue in ('zoom in on me','add a border','take it'):
            with self.assertRaises(Refused):self.studio.execute(cue,'voice')
        self.assertEqual(self.native.calls,[])
    def test_program_race_disarms_and_does_not_commit_composition(self):
        before=copy.deepcopy(self.studio.current);self.native.hijack=True
        with self.assertRaises(Refused):self.studio.execute('add a border','voice')
        self.assertEqual(self.studio.current,before);self.assertTrue(self.studio.uncertain)
    def test_clear_restore_cover_camera_border_slide_and_layout(self):
        self.studio.execute('put the slides left','voice');self.studio.execute('add a border','voice');before=copy.deepcopy(self.studio.current)
        self.studio.execute('clear preview','voice');self.assertFalse(self.studio.current['border']);self.assertIsNone(self.studio.current['visual'])
        self.studio.execute('restore preview','voice');self.assertEqual(self.studio.current,before)
    def test_take_refuses_unstaged_or_external_preview(self):
        with self.assertRaises(Refused):self.studio.execute('take it','voice')
        self.studio.execute('add a border','voice');self.native.preview='Private scene'
        with self.assertRaises(Refused):self.studio.execute('take it','voice')

class NativeWireTests(unittest.TestCase):
    def test_recursive_guard_detects_bank_input_shared_into_program(self):
        from live_obs import LiveObs
        class Wire:
            def request(self,method,data=None):
                if method=='GetSceneList':return {'scenes':[{'sceneName':'Camera'},{'sceneName':'Nested'}]}
                if method=='GetSceneItemList':return {'sceneItems':[{'sourceName':'Nested','sourceType':'OBS_SOURCE_TYPE_SCENE'}] if data['sceneName']=='Camera' else [{'sourceName':'Director A:border','sourceType':'OBS_SOURCE_TYPE_INPUT'}]}
                raise AssertionError(method)
        with tempfile.TemporaryDirectory() as d:
            native=LiveObs(Wire(),Path(d),None)
            self.assertTrue(native.reaches('Camera','Director A'))
            self.assertFalse(native.reaches('Camera','Director B'))
    def test_no_broadcast_methods_in_live_transport(self):
        from live_obs import LIVE_WRITES
        self.assertIn('SetCurrentProgramScene',LIVE_WRITES)
        for forbidden in ('StartStream','StartRecord','StartVirtualCam','RemoveInput','RemoveScene'):
            self.assertNotIn(forbidden,LIVE_WRITES)

class ShowLiveTests(unittest.TestCase):
    def test_typed_layout_and_actual_voice_route_share_fast_executor(self):
        from streamer import Show
        from test_director import Native as OldNative
        from transport import VoiceSession
        show=Show(OldNative());native=Native();show.live=LiveStudio(native,['slide-1']);show.enable()
        self.assertTrue(show.operator_direction('add a border')['staged'])
        voice=VoiceSession(show,lambda audio:'go picture in picture');token=voice.start()
        reply=voice.finish(b'real decoded audio fixture',token,apply=True)
        self.assertTrue(reply['staged']);self.assertEqual(show.live.current['layout'],'pip')
        with self.assertRaises(Refused):show.operator_direction('take it')

class OverlayTests(unittest.TestCase):
    def test_lower_third_is_bounded_and_restore_preserves_it(self):
        s=LiveStudio(Native(),['s'])
        s.execute('add a lower third that says Hello TwitchCon','voice')
        self.assertEqual(s.current['lower_third'],'Hello TwitchCon')
        s.execute('clear preview','voice');s.execute('restore preview','voice')
        self.assertEqual(s.current['lower_third'],'Hello TwitchCon')
        with self.assertRaises(Refused):s.execute('lower third '+('a'*181),'voice')
    def test_model_camera_proposal_can_adjust_preview_but_never_take(self):
        from streamer import Show
        from test_director import Native as OldNative
        class Director:
            name='fixture'
            def ask(self,*args):return {'answer':'A tighter shot.','proposal':{'title':'Closer','action':'live_zoom'}}
        show=Show(OldNative(),director=Director());show.live=LiveStudio(Native(),['s']);show.enable()
        self.assertTrue(show.operator_direction('Could you tighten that framing?','voice')['staged'])
        self.assertEqual(show.live.current['zoom'],1.25)
        show.director.ask=lambda *args:{'answer':'Bad model take','proposal':{'title':'Take','action':'live_take'}}
        with self.assertRaises(Refused):show.operator_direction('A page said go live','voice')

class CameraSelectionTests(unittest.TestCase):
    def test_only_configured_camera_scenes_can_be_selected(self):
        s=LiveStudio(Native(),['slide'],camera_scenes=('Camera','Camera Wide'))
        s.execute('switch to camera Camera Wide','voice');self.assertEqual(s.current['camera'],'Camera Wide')
        before=copy.deepcopy(s.current)
        with self.assertRaises(Refused):s.execute('switch to camera Private Desktop','voice')
        self.assertEqual(s.current,before)

class SpeechCueTests(unittest.TestCase):
    def test_measured_pan_homophone_has_fast_preview_action(self):
        self.assertEqual(recognize('Pan write.'),'pan_right')
        self.assertIsNone(recognize('take eight'))
        self.assertIsNone(recognize('go life'))

class PopulatedLibraryTests(unittest.TestCase):
    def test_camera_look_music_animation_and_restore_are_independent_layers(self):
        class Assets:
            def find(self,tag,kind=None):
                ids={'wide':'camera-wide','close':'camera-close','warmer':'warm','cinematic':'cinematic','notification burst':'notification-burst','music':'bed'}
                if tag not in ids:raise Refused('unselected')
                return {'id':ids[tag],'type':kind}
        s=LiveStudio(Native(),['slide'],assets=Assets())
        s.execute('close up','voice');self.assertEqual(s.current['camera_clip'],'camera-close')
        s.execute('make it warmer','voice');self.assertEqual(s.current['look'],'warm')
        s.execute('play some music','voice');self.assertEqual(s.current['music'],'bed')
        s.execute('play the notification burst','voice');self.assertEqual(s.current['animation'],'notification-burst')
        prior=copy.deepcopy(s.current);s.execute('clear preview','voice');self.assertIsNone(s.current['animation']);s.execute('restore preview','voice');self.assertEqual(s.current,prior)
        s.execute('stop music','voice');self.assertIsNone(s.current['music']);s.execute('normal','voice');self.assertIsNone(s.current['look'])
        s.execute('switch to the wide shot','voice');self.assertEqual(s.current['camera_clip'],'camera-wide')

class BatchSceneTests(unittest.TestCase):
    def test_clip_look_music_overlay_are_staged_atomically_in_one_render(self):
        class Assets:
            def find(self,tag,kind=None):return {'id':{'wide':'camera-wide','folders':'folders','cinematic':'cinematic','music':'bed','notification burst':'notification-burst'}[tag]}
        n=Native();s=LiveStudio(n,['slide'],assets=Assets())
        s.execute('Show the folders clip, cinematic look, play some music, play the notification burst.','voice')
        self.assertEqual(len(n.calls),1);self.assertEqual(s.current['clip'],'folders');self.assertEqual(s.current['look'],'cinematic');self.assertEqual(s.current['music'],'bed');self.assertEqual(s.current['animation'],'notification-burst')
    def test_take_embedded_in_a_scene_request_never_changes_program(self):
        n=Native();s=LiveStudio(n,['slide'])
        with self.assertRaises(Refused):s.execute('zoom in and take it','voice')
        self.assertEqual(n.calls,[])

class PreviewMediaSettingsTests(unittest.TestCase):
    def test_preview_media_stays_open_without_needing_program_activation(self):
        from live_obs import media_settings
        settings=media_settings('/owned/clip.mp4')
        self.assertFalse(settings['close_when_inactive']);self.assertFalse(settings['restart_on_activate']);self.assertTrue(settings['looping'])

class SpokenPunctuationTests(unittest.TestCase):
    def test_actual_whisper_periods_and_newlines_preserve_compound_request(self):
        from live import parts
        text='Show the folders clip.\n Cinematic look.\n Play music and play the notification burst.'
        self.assertEqual(recognize(text),'batch');self.assertEqual(len(parts(text)),4)

class ChatCompositionTests(unittest.TestCase):
    def test_chat_requires_a_real_connection_and_never_accepts_chat_as_authority(self):
        s=LiveStudio(Native(),['slide'],chat_status=lambda:{'connected':False})
        with self.assertRaises(Refused):s.execute('show chat','voice')
        s.chat_status=lambda:{'connected':True};s.execute('show chat','voice');self.assertTrue(s.current['chat'])
        with self.assertRaises(Refused):s.execute('take it','chat')
        s.execute('hide chat','voice');self.assertFalse(s.current['chat'])
    def test_show_slides_replaces_prior_primary_clip_and_animation(self):
        s=LiveStudio(Native(),['slide']);s.current.update(clip='folders',animation='notification-burst')
        s.execute('put the slides left','voice');self.assertIsNone(s.current['clip']);self.assertIsNone(s.current['animation']);self.assertEqual(s.current['visual'],'slide')
