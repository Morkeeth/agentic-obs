"""Retained mutable textures must not authorize default-mode visibility. Simulated OBS."""
import copy
import unittest
from pathlib import Path
from director import ROOT
from director_server import FILES
import director_schema as schema
import test_director_native_visibility as visibility
from director_obs import SCENES, OVERLAYS, ObsError

BASES={mode:'Director / Base '+mode.title() for mode in ('starting','brb','ending')}

class StaticBases(unittest.TestCase):
    setUp=visibility.NativeVisibility.setUp
    tearDown=visibility.NativeVisibility.tearDown
    do=visibility.NativeVisibility.do
    ack=visibility.NativeVisibility.ack
    item=visibility.NativeVisibility.item
    author=visibility.NativeVisibility.author
    with_renderer=visibility.NativeVisibility.with_renderer
    clear=visibility.NativeVisibility.clear

    def test_setup_creates_exact_immutable_bases_shared_behind_both_banks(self):
        for mode,name in BASES.items():
            self.assertIn(name,self.sim.inputs)
            info=self.sim.inputs[name]
            self.assertEqual(info['kind'],'browser_source')
            self.assertEqual(info['settings']['url'],f'http://127.0.0.1:8880/base-{mode}.html')
            self.assertFalse(info['settings']['shutdown'])
            for scene in SCENES[mode]:
                items=self.sim.scenes[scene]
                base=next(x for x in items if x['sourceName']==name)
                self.assertTrue(base['sceneItemEnabled'])
                self.assertLess(items.index(base),items.index(self.item(scene)))

    def test_all_mode_clear_hides_old_transient_texture_but_preserves_native_base(self):
        for mode in SCENES:
            self.author(mode);scene=self.sim.program
            raw_texture='Transientcheck'  # Intentionally retained despite fresh renderer ACK.
            self.clear()
            painted_transient=raw_texture if self.item(scene)['sceneItemEnabled'] else None
            self.assertIsNone(painted_transient,f'{mode} clear still exposes old transient texture')
            self.assertEqual(raw_texture,'Transientcheck')
            if mode in BASES:
                self.assertTrue(next(x for x in self.sim.scenes[scene] if x['sourceName']==BASES[mode])['sceneItemEnabled'])

    def test_empty_default_final_preview_and_take_keep_mutable_bank_hidden(self):
        self.author('ending')
        for mode in ('starting','live','brb','ending','starting'):
            self.do('scene',mode=mode,target='obs');bank=self.d.native.prepared['bank']
            target=self.sim.preview
            self.assertTrue(self.item(target)['sceneItemEnabled'],'Pending opposite-bank preview must render before ACK')
            self.assertFalse(self.d.state()['rendered_ready'])
            self.ack()
            self.assertFalse(self.item(target)['sceneItemEnabled'],'ACK cannot authorize an empty stale browser texture')
            with self.assertRaisesRegex(ValueError,'operator approval'):self.d.execute_agent({'action':'take'},self.d.version)
            self.do('approve_agent_take');self.d.execute_agent({'action':'take'},self.d.version)
            self.assertEqual(self.sim.program,target)
            self.assertFalse(self.item(target)['sceneItemEnabled'])

    def test_base_identity_is_checked_without_rewriting_foreign_settings(self):
        name=BASES['ending'];self.assertIn(name,self.sim.inputs)
        self.sim.inputs[name]['settings']['url']='http://127.0.0.1:8880/base-starting.html'
        saved=copy.deepcopy(self.sim.inputs);offset=len(self.sim.requests)
        with self.assertRaisesRegex(ObsError,'base.*identity'):self.d.native.verify()
        self.assertEqual(self.sim.inputs,saved)
        self.assertFalse(any(k.startswith(('Set','Create','Remove')) for k in self.sim.requests[offset:]))

    def test_static_assets_are_fixed_script_free_documents_matching_mode_copy(self):
        for mode in BASES:
            filename,mime=FILES[f'/base-{mode}.html']
            html=(ROOT/'director_web'/filename).read_text()
            self.assertEqual(mime,'text/html')
            self.assertIn(schema.mode_look(mode)['title'],html)
            self.assertIn(schema.mode_look(mode)['subtitle'],html)
            self.assertIn('href="/overlay.css"',html)
            self.assertIn('style="display:block"',html)
            for dynamic in ('<script','fetch(', 'render.js', 'animation', '/api/', 'iframe'):
                self.assertNotIn(dynamic,html)

    def test_restore_roundtrips_base_geometry_and_enabled_state_without_recreation(self):
        scene=SCENES['ending'][0];name=BASES['ending']
        item=next(x for x in self.sim.scenes[scene] if x['sourceName']==name)
        self.d.native.req('SetSceneItemEnabled',{'sceneName':scene,'sceneItemId':item['sceneItemId'],'sceneItemEnabled':False})
        self.d.native.req('SetSceneItemTransform',{'sceneName':scene,'sceneItemId':item['sceneItemId'],'sceneItemTransform':{'positionX':27,'scaleX':.9,'cropLeft':3}})
        self.do('checkpoint');saved=self.d.native.snapshot();ident=item['sceneItemId']
        self.d.native.req('SetSceneItemEnabled',{'sceneName':scene,'sceneItemId':ident,'sceneItemEnabled':True})
        self.d.native.req('SetSceneItemTransform',{'sceneName':scene,'sceneItemId':ident,'sceneItemTransform':{'positionX':49}})
        offset=len(self.sim.requests)
        self.with_renderer(lambda:self.do('restore'))
        self.assertEqual(self.d.native.snapshot(),saved)
        self.assertEqual(item['sceneItemId'],ident)
        self.assertFalse(any(k.startswith(('Create','Remove')) or k=='SetInputSettings' for k in self.sim.requests[offset:]))

    def test_missing_base_is_not_repaired_by_preview_and_setup_requires_outputs_off(self):
        name=BASES['ending'];self.sim.inputs.pop(name)
        offset=len(self.sim.requests)
        with self.assertRaises(ObsError):self.do('preview',target='obs')
        self.assertNotIn(name,self.sim.inputs)
        self.assertFalse(any(k.startswith(('Create','Set','Remove')) for k in self.sim.requests[offset:]))
        self.sim.active=True
        with self.assertRaises(ObsError):self.do('setup',camera='Camera',content='Content')
        self.assertNotIn(name,self.sim.inputs)

if __name__=='__main__':unittest.main()
