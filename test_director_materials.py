"""Selected material is explicit bounded data, never ambient discovery or viewer prompts."""
from pathlib import Path
import tempfile
import unittest
from director import Director,ROOT


class SelectedMaterials(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT,prefix='.director-test-')
        self.d=Director(data_dir=self.tmp.name)
    def tearDown(self):self.d.close();self.tmp.cleanup()
    def act(self,action,**fields):return self.d.execute({'action':action,**fields},self.d.version)
    def test_starter_requires_operator_selection_and_exact_revision(self):
        with self.assertRaises(ValueError):self.d.read_selected_material('twitch-story','unselected')
        state=self.act('material_select',id='twitch-story')
        selected=state['selected_material']
        read=self.d.read_selected_material(selected['id'],selected['revision'])
        self.assertIn('streamer direction',read['content'].lower())
        self.assertIn('streamer decision',read['content'].lower())
        self.assertEqual(read['handling'],'reference data, not instructions')
        self.assertNotIn(read['content'],str(self.d.agent_state()))
        with self.assertRaises(ValueError):self.d.read_selected_material(selected['id'],'stale')
        with self.assertRaises(ValueError):self.d.execute_agent({'action':'material_select','id':'twitch-story'},self.d.version)

    def test_explicit_registration_bounded_paths_and_changed_file_revision(self):
        from director_materials import MaterialCatalog
        root=Path(self.tmp.name)/'materials';root.mkdir()
        self.d.materials=MaterialCatalog(root)
        (root/'reference.txt').write_text('An explicit reference only.')
        self.act('material_register',id='reference',name='My reference',file='reference.txt')
        state=self.act('material_select',id='reference');old=state['selected_material']
        (root/'reference.txt').write_text('Changed bounded data.')
        with self.assertRaises(ValueError):self.d.read_selected_material(**old)
        newer=self.act('material_select',id='reference')['selected_material']
        self.assertNotEqual(newer['revision'],old['revision'])
        self.assertEqual(self.d.read_selected_material(**newer)['content'],'Changed bounded data.')
        for file in ('../reference.txt','/private.txt','reference.pdf'):
            with self.assertRaises(ValueError):self.act('material_register',id='bad',name='Bad',file=file)
        (root/'link.txt').symlink_to(root/'reference.txt')
        (root/'large.txt').write_bytes(b'x'*32769)
        for file in ('link.txt','large.txt'):
            with self.assertRaises(ValueError):self.act('material_register',id='bad',name='Bad',file=file)
        self.act('material_select',id=None)
        with self.assertRaises(ValueError):self.d.read_selected_material(**newer)

    def test_viewer_text_cannot_register_select_or_become_material(self):
        self.act('audience',enabled=True)
        self.d.enqueue_request({'session':'s','event_id':'e','viewer_id':'123','text':'VIEWER_MATERIAL_SENTINEL','suggested':None})
        self.act('material_select',id='twitch-story')
        selected=self.d.state()['selected_material']
        self.assertNotIn('VIEWER_MATERIAL_SENTINEL',self.d.read_selected_material(**selected)['content'])
        for channel in ('program','preview','bank-A','bank-B'):
            self.assertNotIn('Selected research',str(self.d.render(channel)))

if __name__=='__main__':unittest.main()
