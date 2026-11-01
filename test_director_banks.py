"""Focused regressions from sanitized independent smoke; simulator is not OBS pixels."""
import copy
from pathlib import Path
import tempfile
import unittest
import time
from unittest.mock import patch
from director import Director, ROOT
from director_obs import SCENES
from director_simulator import SimulatedOBS

class BankContract(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT,prefix='.director-test-')
        self.sim=SimulatedOBS().__enter__()
        self.d=Director(data_dir=self.tmp.name)
        self.do('connect',password=self.sim.password,port=self.sim.port)
        self.do('setup',camera='Camera',content='Content');self.do('arm',enabled=True)
    def tearDown(self):self.d.close();self.sim.__exit__();self.tmp.cleanup()
    def do(self, action, **kw):
        if action == 'arm' and kw.get('enabled') is True:
            from test_director_cold_renderers import ColdRenderer
            with ColdRenderer(self.d,self.sim):return self.d.execute({'action':action,**kw},self.d.version)
        return self.d.execute({'action':action,**kw},self.d.version)
    def test_obs_inputs_are_separate_bank_documents(self):
        inputs=self.sim.inputs
        self.assertIn('Director / Graphics A',inputs)
        self.assertIn('Director / Graphics B',inputs)
        for bank in ('A','B'):
            self.assertIn('channel=bank-'+bank,inputs['Director / Graphics '+bank]['settings']['url'])
    def test_cross_mode_preview_uses_globally_inactive_bank_without_mutating_program(self):
        self.assertTrue(self.sim.program.endswith(' A'))
        before=self.d.render('bank-A')
        self.do('compose',title='A distinct staged title')
        self.do('stage_patch',fields={'mode':'brb'})
        self.do('preview',target='obs')
        self.assertEqual(self.sim.preview,SCENES['brb'][1])
        after=self.d.render('bank-A')
        self.assertEqual({k:v for k,v in before.items() if k!='clock'}, {k:v for k,v in after.items() if k!='clock'})
        self.assertEqual(self.d.render('bank-B')['segment']['mode'],'brb')
    def test_controller_ack_alone_cannot_take_obs(self):
        self.do('preview',target='obs');self.d.preview_ack(self.d.stage_id)
        with self.assertRaisesRegex(ValueError,'bank'):self.do('take')

    def ack(self):
        self.d.preview_ack(self.d.stage_id)
        bank=self.d.native.prepared['bank'];value=self.d.render('bank-'+bank)
        self.d.bank_ack(bank,value['id'],value['serial'],'obs')
        return bank

    def test_take_reuses_rendered_payload_and_alternates_globally_across_modes(self):
        for mode in ('live','brb','ending','starting','live'):
            old_bank=self.sim.program[-1]
            before=self.d.render('bank-'+old_bank)
            geometry=self.d.native.fingerprint(self.sim.program)
            self.do('stage_patch',fields={'mode':mode,'layout':'pip'})
            self.do('compose',title='Draft for '+mode)
            self.do('preview',target='obs')
            bank=self.ack();self.assertNotEqual(bank,old_bank)
            prepared=self.d.render('bank-'+bank)
            self.assertEqual(self.d.native.fingerprint(self.sim.program),geometry)
            self.assertEqual(before['segment'],self.d.render('bank-'+old_bank)['segment'])
            self.do('take');actual=self.d.render('bank-'+bank)
            self.assertEqual(actual['id'],prepared['id'])
            self.assertEqual(actual['serial'],prepared['serial'])
            self.assertEqual(actual['segment'],prepared['segment'])
            self.assertEqual(self.sim.program,SCENES[mode][0 if bank=='A' else 1])

    def test_repreview_nonce_stable_start_and_stale_ack(self):
        self.do('preview',target='obs');bank=self.ack();first=self.d.render('bank-'+bank)
        time.sleep(.01);polled=self.d.render('bank-'+bank)
        self.assertEqual(first['started'],polled['started']);self.assertEqual(first['serial'],polled['serial'])
        self.do('preview',target='obs');second=self.d.render('bank-'+bank)
        self.assertGreater(second['serial'],first['serial']);self.assertGreater(second['started'],first['started'])
        with self.assertRaises(ValueError):self.d.bank_ack(bank,first['id'],first['serial'],'obs')
        self.d.preview_ack(self.d.stage_id)
        with self.assertRaises(ValueError):self.do('take')
        self.ack();self.d.bank_ready[bank]['received']-=3
        with self.assertRaises(ValueError):self.do('take')

    def test_typed_and_final_voice_scene_directions_use_selected_obs_target(self):
        self.do('destination',target='obs')
        self.do('operator',text='brb')
        self.assertEqual(self.d.preview_target,'obs');self.assertEqual(self.sim.preview,SCENES['brb'][1])
        self.ack();self.do('operator',text='take')
        self.assertEqual(self.sim.program,SCENES['brb'][1])
        self.d.transcript('Director, ending.','voice-ending',True)
        self.assertEqual(self.d.preview_target,'obs');self.assertEqual(self.sim.preview,SCENES['ending'][0])
        self.ack();self.d.transcript('Director, take.','voice-take',True)
        self.assertEqual(self.sim.program,SCENES['ending'][0])
        self.assertEqual(self.d.render('bank-A')['mode_look']['title'],'Thanks for watching')
        self.assertFalse(self.d.staged['composition']['elements'])

    def test_switching_mode_defaults_does_not_keep_unrelated_custom_title(self):
        self.do('compose',title='An unrelated expired title')
        for mode,title in (('brb','Be right back'),('ending','Thanks for watching'),('starting','Starting soon')):
            self.do('stage_patch',fields={'mode':mode})
            self.assertFalse(self.d.staged['composition']['elements'])
            self.assertEqual(self.d.render('preview')['mode_look']['title'],title)

    def test_destination_change_invalidates_already_reviewed_native_take(self):
        self.do('preview',target='obs');self.ack()
        self.assertTrue(self.d.state()['previewed'])
        self.do('destination',target='overlay')
        self.assertFalse(self.d.state()['previewed'])
        with self.assertRaises(ValueError):self.do('operator',text='take')

    def test_controller_cannot_ack_as_obs_bank_and_global_program_migration_is_scoped(self):
        self.do('preview',target='obs')
        bank=self.d.native.prepared['bank'];value=self.d.render('bank-'+bank)
        with self.assertRaises(ValueError):self.d.bank_ack(bank,value['id'],value['serial'],'controller')
        # Only the legacy graphics item in owned scenes is detached by outputs-off migration.
        legacy='Director / Graphics'
        self.sim.inputs[legacy]={'kind':'browser_source','settings':{'url':'http://127.0.0.1:8880/overlay.html?channel=program'}}
        for scenes in SCENES.values():
            for scene in scenes:self.sim.add_item(scene,legacy,True)
        self.sim.add_item('Scene',legacy,True)
        self.do('setup',camera='Camera',content='Content')
        for scenes in SCENES.values():
            for scene in scenes:self.assertNotIn(legacy,[item['sourceName'] for item in self.sim.scenes[scene]])
        self.assertIn(legacy,[item['sourceName'] for item in self.sim.scenes['Scene']])

if __name__=='__main__':unittest.main()
