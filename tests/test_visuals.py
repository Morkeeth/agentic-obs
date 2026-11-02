import io
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from streamer import Refused,Show
from test_director import Native
from visuals import VisualLibrary,PreviewVisuals

class VisualNative(Native):
    def __init__(self): super().__init__();self.active_visual=None
    def visual_write(self,kind,value,layout):
        self.active_visual={'kind':kind,'value':str(value),'layout':dict(layout)}
    def visual_hide(self):self.active_visual=None

class VisualTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.library=VisualLibrary(Path(self.temp.name).resolve())
        self.native=VisualNative();self.show=Show(self.native)
        self.visual=PreviewVisuals(self.show,self.library)
    def test_slide_then_next_then_move_are_preview_only(self):
        self.show.enable();self.visual.command('slideshow')
        first=self.visual.state()['asset_id']
        self.visual.command('next');self.assertNotEqual(self.visual.state()['asset_id'],first)
        self.visual.command('move',x=.15,y=.2,width=.6,height=.6)
        self.assertEqual(self.visual.state()['layout']['x'],.15)
        self.assertEqual(self.native.program,'Camera')
    def test_images_are_decoded_and_renamed_no_arbitrary_path(self):
        image=Image.new('RGB',(40,20),'blue');data=io.BytesIO();image.save(data,format='PNG')
        asset=self.library.add_image('Selected picture',data.getvalue())
        self.assertRegex(asset['id'],r'^[a-f0-9]{24}$')
        self.assertEqual(self.library.path(asset['id']).parent,Path(self.temp.name).resolve())
        with self.assertRaises(Refused):self.library.path('../../private')
        with self.assertRaises(Refused):self.library.add_image('script',b'<svg onload="evil"/>')
    def test_preview_guard_applies_to_visual_moves(self):
        self.show.enable();self.native.program='Staging'
        with self.assertRaises(Refused):self.visual.command('slideshow')
        self.assertIsNone(self.native.active_visual)
    def test_clear_restore_preserves_selected_slide_and_layout(self):
        self.show.enable();self.visual.command('slideshow')
        self.visual.command('move',x=.2,y=.1,width=.6,height=.7)
        prior=self.visual.state()
        self.show.clear();self.assertFalse(self.visual.state()['visible'])
        self.show.restore();self.assertEqual(self.visual.state(),prior)
    def test_disabled_title_does_not_hide_existing_visual(self):
        self.show.enable();self.visual.command('slideshow');prior=self.native.active_visual
        self.show.disable()
        with self.assertRaises(Refused):self.show.stage('Forbidden')
        self.assertEqual(self.native.active_visual,prior)
    def test_title_replaces_image_and_restore_brings_image_back(self):
        self.show.enable();self.visual.command('slideshow');prior=self.visual.state()
        self.show.stage('The director gets a director')
        self.assertFalse(self.visual.state()['visible'])
        self.show.restore();self.assertEqual(self.visual.state(),prior)
    def test_clear_and_restore_disarm_when_visual_write_fails(self):
        for operation in ('clear','restore'):
            with self.subTest(operation=operation):
                self.show.enable();self.visual.command('slideshow')
                if operation=='restore':self.show.clear()
                def fail(*args):raise OSError('native disconnected')
                if operation=='clear':self.native.visual_hide=fail
                else:self.native.visual_write=fail
                with self.assertRaises(Refused):getattr(self.show,operation)()
                self.assertFalse(self.show.enabled);self.assertTrue(self.show.uncertain)
                self.native=VisualNative();self.show=Show(self.native)
                self.visual=PreviewVisuals(self.show,self.library)
    def test_bounds_and_arbitrary_urls_refused(self):
        self.show.enable()
        with self.assertRaises(Refused):self.visual.command('move',x=-1,y=0,width=1,height=1)
        for value in ('file:///private','http://127.0.0.1/private','https://user:pass@93.184.215.14','javascript:alert(1)'):
            with self.assertRaises(Refused):self.library.add_page(value)
    def test_browser_uses_only_operator_selected_page_id(self):
        page=self.library.add_page('https://example.org/')
        self.show.enable();self.visual.command('show',asset_id=page['id'])
        self.assertEqual(self.native.active_visual['kind'],'page')
        with self.assertRaises(Refused):self.visual.command('show',asset_id='https://unselected.example')

if __name__=='__main__':unittest.main()
