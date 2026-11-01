"""Actual rehearsal clear contract, simulated OBS and renderer acknowledgments."""
import copy
from pathlib import Path
from unittest.mock import patch
import unittest
import test_director_banks as banks
from director import Conflict
from director_obs import ObsError, SCENES, OVERLAYS


class ClearCompletion(unittest.TestCase):
    setUp = banks.BankContract.setUp
    tearDown = banks.BankContract.tearDown
    do = banks.BankContract.do
    ack = banks.BankContract.ack

    def author(self):
        self.do('scene',mode='live',layout='pip',target='obs')
        self.do('compose',title='Authored, not a template selection')
        self.do('stage_patch',fields={
            'timer':{'kind':'elapsed','seconds':0,'label':'Session'},
            'vote':{'question':'Choose','options':['One','Two']},
            'lower':{'title':'Community','subtitle':'Together'}})
        self.do('preview',target='obs'); self.ack(); self.do('take')
        self.d.alert={'title':'Celebration','start':self.d.clock(),'until':self.d.clock()+30}
        self.d.voters={'local':'1'}

    def test_clear_confirms_native_hide_and_cleanup_without_waiting_for_texture_ack(self):
        self.author()
        folder=Path(self.tmp.name);(folder/'owned.wav').write_bytes(b'simulated media')
        self.d.media_dir=folder;self.d.native.media_root=folder
        self.do('media_play',name='owned.wav',volume=.3)
        before=self.d.native.snapshot();program=copy.deepcopy(self.d.program)
        bank=self.d.program_bank;other='B' if bank=='A' else 'A'
        old=copy.deepcopy(self.d.banks);offset=len(self.sim.requests)
        result=self.do('clear')
        payload=self.d.render('bank-'+bank)
        self.assertGreater(payload['id'],max(p['id'] for p in old.values()))
        self.assertFalse(result['bank_readiness'][bank],'No invisible texture paint is claimed')
        self.assertFalse(payload['segment']['composition']['elements'])
        for field in ('lower','timer','vote','media'):self.assertIsNone(payload['segment'][field])
        for field in ('timer','vote','alert'):self.assertIsNone(payload[field])
        self.assertEqual(self.d.voters,{})
        self.assertEqual(self.d.banks[other],old[other])
        self.assertTrue(self.d.armed);self.assertEqual(self.d.checkpoint['program'],program)
        expected=copy.deepcopy(before)
        next(item for item in expected['geometry'][before['program']] if item['source']==OVERLAYS[bank])['enabled']=False
        self.assertEqual(self.d.native.snapshot(),expected)
        self.assertEqual(self.sim.volume,0);self.assertEqual(self.sim.media_state,'OBS_MEDIA_STATE_STOPPED')
        self.assertFalse(set(self.sim.requests[offset:]) & {'SetCurrentProgramScene','SetCurrentPreviewScene','SetSceneItemTransform','RemoveInput','RemoveSceneItem'})

    def test_no_clear_ack_is_needed_but_authored_restore_requires_visible_prepaint(self):
        from test_director_hidden_operations import VisibleRenderer
        self.author();before=copy.deepcopy(self.d.program)
        self.do('clear')
        self.assertTrue(self.d.armed);self.assertEqual(self.d.checkpoint['program'],before)
        self.assertEqual(self.d.events[-1]['outcome'],'applied')
        with VisibleRenderer(self.d,self.sim):self.do('restore')
        self.assertEqual(self.d.program,before)

    def test_existing_stalled_fade_prevents_publication(self):
        self.author()
        self.d.native.req('SetCurrentProgramScene',{'sceneName':SCENES['brb'][0]})
        self.sim.transition_stuck=True;self.d.native.transition_timeout=.08
        before=copy.deepcopy(self.d.banks)
        with self.assertRaises(ObsError):self.do('clear')
        self.assertEqual(self.d.banks,before);self.assertFalse(self.d.armed)

    def test_program_change_during_native_hide_cannot_report_cleared(self):
        self.author();original=self.sim.rpc
        def change(kind,data):
            value=original(kind,data)
            if kind=='SetSceneItemEnabled' and not data['sceneItemEnabled']:self.sim.program=SCENES['ending'][0]
            return value
        with patch.object(self.sim,'rpc',side_effect=change):
            with self.assertRaises(ObsError):self.do('clear')
        self.assertFalse(self.d.armed);self.assertIsNotNone(self.d.checkpoint)
        self.assertEqual(self.d.events[-1]['outcome'],'not confirmed')

    def test_other_scene_on_same_bank_is_not_cleared(self):
        self.author()
        bank=self.d.program_bank
        self.d.native.req('SetCurrentProgramScene',{'sceneName':SCENES['ending'][0 if bank=='A' else 1]})
        self.d.native.wait_transition()
        before=copy.deepcopy(self.d.banks)
        with self.assertRaisesRegex(ObsError,'program changed before clear'):self.do('clear')
        self.assertEqual(self.d.banks,before);self.assertFalse(self.d.armed)

    def test_native_clear_requires_human_arming(self):
        self.author();self.do('arm',enabled=False)
        before=copy.deepcopy(self.d.banks)
        with self.assertRaises(ObsError):self.do('clear')
        self.assertEqual(self.d.banks,before)

if __name__=='__main__':unittest.main()
