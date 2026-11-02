import unittest
from streamer import Show,Refused
from obs import RehearsalNative
from live import LiveStudio
from test_live import Native

class LivePreviewTests(unittest.TestCase):
    def studio(self):
        n=Native();n.outputs=True
        return n,LiveStudio(n,['slide'])
    def test_streaming_allows_off_program_preview_but_never_take(self):
        n,s=self.studio();s.execute('zoom in on me');self.assertEqual(n.program,'Camera');self.assertEqual(n.preview,'Director A');self.assertGreater(s.current['zoom'],1)
        with self.assertRaises(Refused):s.execute('take it','voice')
        self.assertEqual(n.program,'Camera')
    def test_recording_virtual_camera_and_program_race_are_still_blocked(self):
        n,s=self.studio();old=n.status
        for output in ('record','virtual'):
            n.status=lambda:{**old(),'outputs':{'stream':True,'record':output=='record','virtual':output=='virtual'}}
            with self.assertRaises(Refused):s.execute('add a border')
        n.status=old;n.hijack=True
        with self.assertRaises(Refused):s.execute('add a border')
        self.assertTrue(s.uncertain)
    def test_unrelated_program_change_after_render_is_refused_and_uncertain(self):
        n,s=self.studio();original=n.render
        def render(*args):original(*args);n.program='Other camera'
        n.render=render
        with self.assertRaisesRegex(Refused,'Program changed'):s.execute('add a border')
        self.assertTrue(s.uncertain);self.assertIsNone(s.staged_bank)
    def test_show_enable_shares_stream_preview_policy(self):
        class Streaming(RehearsalNative):
            def read(self):return dict(super().read(),outputs={'stream':True,'record':False,'virtual':False})
        show=Show(Streaming());self.assertTrue(show.enable()['enabled']);self.assertTrue(show.state()['allow_live_preview'])
