import tempfile
import unittest
from pathlib import Path
from streamer import Show,Refused
from visuals import VisualLibrary,PreviewVisuals
from test_visuals import VisualNative

class Commands(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.show=Show(VisualNative());PreviewVisuals(self.show,VisualLibrary(Path(t.name)));self.show.enable()
    def test_spoken_show_slides_next_move_clear_restore_act_without_title_substitution(self):
        reply=self.show.operator_direction('Director, show the slideshow.',source='voice')
        self.assertTrue(reply['staged']);first=self.show.visuals.state()['asset_id']
        self.show.operator_direction('Next slide',source='voice')
        self.assertNotEqual(self.show.visuals.state()['asset_id'],first)
        self.show.operator_direction('Move it left',source='voice')
        self.assertEqual(self.show.visuals.state()['layout']['x'],0)
        prior=self.show.visuals.state()
        self.show.operator_direction('Clear the graphic',source='voice')
        self.assertFalse(self.show.visuals.state()['visible'])
        self.show.operator_direction('Restore preview',source='voice')
        self.assertEqual(self.show.visuals.state(),prior)
        self.assertEqual(self.show.native.program,'Camera')
    def test_chat_cannot_invoke_operator_commands(self):
        with self.assertRaises(Refused):self.show.operator_direction('Next slide',source='chat')
    def test_conversational_context_includes_last_direction_and_current_visual(self):
        captured=[]
        original=self.show.director.ask
        def ask(text,context):captured.append(context);return original(text,context)
        self.show.director.ask=ask
        self.show.direct('Put a title about coffee')
        self.show.direct('Make that title shorter')
        self.assertIn('coffee',repr(captured[1]['conversation']))
        self.assertIn('visual',captured[1])

if __name__=='__main__':unittest.main()
