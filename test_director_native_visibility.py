"""Owned item visibility with retained SOURCE textures. Simulated, never GPU pixels."""
import copy
import threading
import time
import unittest
from unittest.mock import patch
import test_director_banks as banks
from director_obs import OVERLAYS, SCENES, BASES, ObsError
from director import Conflict

class NativeVisibility(unittest.TestCase):
    setUp=banks.BankContract.setUp
    tearDown=banks.BankContract.tearDown
    do=banks.BankContract.do
    ack=banks.BankContract.ack
    def item(self,scene):
        return next(x for x in self.sim.scenes[scene] if x['sourceName']==OVERLAYS[scene[-1]])
    def author(self,mode='live'):
        self.do('scene',mode=mode,target='obs');self.do('compose',title='Old chapter')
        self.do('preview',target='obs');self.ack();self.do('take')
    def with_renderer(self,action):
        stop=threading.Event()
        def render():
            while not stop.wait(.01):
                for bank in ('A','B'):
                    value=self.d.render('bank-'+bank)
                    try:self.d.bank_ack(bank,value['id'],value['serial'],'obs')
                    except Conflict:pass
        worker=threading.Thread(target=render);worker.start()
        try:return action()
        finally:stop.set();worker.join(2)
    def clear(self):return self.with_renderer(lambda:self.do('clear'))

    def test_live_clear_excludes_retained_source_texture_without_changing_content(self):
        self.author();scene=self.sim.program;bank=scene[-1]
        before=copy.deepcopy(self.sim.scenes);inputs=copy.deepcopy(self.sim.inputs)
        raw_source={bank:'Old chapter'}  # Independent stale-texture effect, unchanged by ACK.
        self.clear()
        program_graphics=raw_source[bank] if self.item(scene)['sceneItemEnabled'] else None
        self.assertIsNone(program_graphics,'ACK did not remove stale texture from simulated program')
        self.assertEqual(raw_source[bank],'Old chapter','Hiding is not SOURCE texture clearing')
        expected=copy.deepcopy(before)
        next(x for x in expected[scene] if x['sourceName']==OVERLAYS[bank])['sceneItemEnabled']=False
        self.assertEqual(self.sim.scenes,expected)
        self.assertEqual(self.sim.inputs,inputs,'No source reload/recreation/settings change')
        self.assertEqual(self.sim.program,scene)

    def test_persistent_mode_clear_keeps_owned_base_visible(self):
        for mode in ('starting','brb','ending'):
            self.author(mode);self.clear()
            self.assertFalse(self.item(self.sim.program)['sceneItemEnabled'])
            self.assertTrue(next(x for x in self.sim.scenes[self.sim.program] if x['sourceName']==BASES[mode])['sceneItemEnabled'])

    def test_hidden_next_preview_reveals_only_after_fresh_ack_and_agent_approval(self):
        self.author();self.clear()
        # Return to the other bank, then preview the previously hidden Live item.
        self.do('scene',mode='brb',target='obs');self.ack();self.do('take')
        old_scene=self.sim.program;old=copy.deepcopy(self.sim.scenes[old_scene])
        self.do('scene',mode='live',target='obs');self.do('compose',title='New authored graphics')
        self.do('stage_patch',fields={'lower':{'title':'Next guest','subtitle':'Community'},'timer':{'kind':'countdown','seconds':90,'label':'Next'}})
        self.do('preview',target='obs');bank=self.d.native.prepared['bank'];target=self.sim.preview
        self.assertTrue(self.item(target)['sceneItemEnabled'],'Unapproved inactive preview is visible while awaiting fresh ACK')
        value=self.d.render('bank-'+bank)
        self.d.preview_ack(self.d.stage_id)
        with self.assertRaises(ValueError):self.d.bank_ack(bank,value['id']-1,value['serial'],'obs')
        self.assertTrue(self.item(target)['sceneItemEnabled'],'Unapproved inactive preview is visible while awaiting fresh ACK')
        self.d.bank_ack(bank,value['id'],value['serial'],'obs')
        self.assertTrue(self.item(target)['sceneItemEnabled'])
        self.assertEqual(self.sim.scenes[old_scene],old);self.assertEqual(self.sim.program,old_scene)
        with self.assertRaisesRegex(ValueError,'operator approval'):self.d.execute_agent({'action':'take'},self.d.version)
        self.do('approve_agent_take');self.d.execute_agent({'action':'take'},self.d.version)
        self.assertEqual(self.sim.program,target)
        self.assertTrue(self.item(target)['sceneItemEnabled'])
        self.assertEqual(self.d.program['lower']['title'],'Next guest')
        self.assertTrue(self.d.timer_state['running'])

    def test_revealed_visibility_is_checked_by_take_fingerprint(self):
        self.do('stage_patch',fields={'mode':'live'})
        self.do('compose',title='Authored reveal');self.do('preview',target='obs');self.ack()
        self.item(self.sim.preview)['sceneItemEnabled']=False
        count=self.sim.requests.count('SetCurrentProgramScene')
        with self.assertRaisesRegex(ObsError,'layout changed'):self.do('take')
        self.assertFalse(self.d.armed)
        self.assertEqual(self.sim.requests.count('SetCurrentProgramScene'),count)

    def test_refused_final_visibility_readback_disarms_without_heartbeat_mutation_retry(self):
        self.do('scene',mode='live',target='obs')
        bank=self.d.native.prepared['bank'];value=self.d.render('bank-'+bank)
        original=self.sim.rpc
        def ignored_enable(kind,data):
            if kind=='SetSceneItemEnabled' and not data['sceneItemEnabled']:return {}
            return original(kind,data)
        with patch.object(self.sim,'rpc',side_effect=ignored_enable):
            with self.assertRaisesRegex(ObsError,'visibility not confirmed'):
                self.d.bank_ack(bank,value['id'],value['serial'],'obs')
        count=self.sim.requests.count('SetSceneItemEnabled')
        self.assertFalse(self.d.armed);self.assertIsNone(self.d.native.prepared)
        self.d.bank_ack(bank,value['id'],value['serial'],'obs')
        self.assertEqual(self.sim.requests.count('SetSceneItemEnabled'),count)
        self.assertFalse(self.d.state()['rendered_ready'])

    def test_restore_preserves_enabled_state_in_both_directions(self):
        self.author();scene=self.sim.program
        self.clear();self.assertFalse(self.item(scene)['sceneItemEnabled'])
        self.with_renderer(lambda:self.do('restore'));self.assertTrue(self.item(scene)['sceneItemEnabled'])
        self.clear();self.do('checkpoint');snapshot=self.d.native.snapshot()
        self.do('scene',mode='ending',target='obs');self.ack();self.do('take')
        self.with_renderer(lambda:self.do('restore'))
        self.assertEqual(self.d.native.snapshot(),snapshot)
        self.assertFalse(self.item(scene)['sceneItemEnabled'])

    def test_fixed_popup_reveals_current_live_after_clear_only_with_new_ready_payload(self):
        self.author();self.clear();scene=self.sim.program;self.do('audience',enabled=True)
        self.assertFalse(self.item(scene)['sceneItemEnabled'])
        errors=[];results=[]
        worker=threading.Thread(target=lambda:self.popup_result(results,errors));worker.start()
        try:
            deadline=time.monotonic()+1
            while worker.is_alive() and not self.d.in_flight and time.monotonic()<deadline:time.sleep(.005)
            self.assertTrue(worker.is_alive(),'Popup must wait for new hidden-bank paint')
            self.assertFalse(self.item(scene)['sceneItemEnabled'])
            payload=self.d.render('bank-'+scene[-1])
            self.assertFalse(payload['segment']['composition']['elements'])
            self.assertEqual(payload['alert']['title'],'Celebration')
            self.d.bank_ack(scene[-1],payload['id'],payload['serial'],'obs')
            worker.join(2);self.assertFalse(errors,errors);self.assertFalse(worker.is_alive())
            self.assertEqual(results[0]['result'],'fixed cue accepted')
            self.assertTrue(self.item(scene)['sceneItemEnabled'])
            self.assertEqual(self.sim.program,scene)
        finally:worker.join(6)
    def popup_result(self,results,errors):
        try:results.append(self.d.audience('local',cue='Director party'))
        except Exception as exc:errors.append(exc)

    def test_popup_cannot_bypass_disarm_allowlist_or_missing_readiness(self):
        self.author();self.clear();scene=self.sim.program;self.do('audience',enabled=True)
        before=copy.deepcopy(self.d.banks)
        self.assertEqual(self.d.audience('local',cue='Director show arbitrary text')['result'],'rejected')
        self.assertEqual(self.d.banks,before)
        self.do('arm',enabled=False)
        self.assertEqual(self.d.audience('local',cue='Director party')['result'],'input off')
        self.assertFalse(self.item(scene)['sceneItemEnabled'])
        self.do('arm',enabled=True)
        with self.assertRaisesRegex(ObsError,'render'):self.d.audience('local',cue='Director party')
        self.assertFalse(self.d.armed);self.assertFalse(self.item(scene)['sceneItemEnabled'])

if __name__=='__main__':unittest.main()
