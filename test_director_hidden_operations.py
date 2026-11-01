"""Visible-per-payload native lifecycle; simulated protocol, never GPU/pixel acceptance."""
import copy
import threading
import time
import unittest
import test_director_native_visibility as visibility
from director_obs import OVERLAYS, BASES, ObsError

class VisibleRenderer:
    def __init__(self,d,sim):self.d=d;self.sim=sim;self.stop=threading.Event()
    def __enter__(self):
        def run():
            while not self.stop.wait(.01):
                for bank in ('A','B'):
                    if not any(x['sourceName']==OVERLAYS[bank] and x['sceneItemEnabled']
                               for scene in (self.sim.program,self.sim.preview) for x in self.sim.scenes.get(scene,[])):continue
                    value=self.d.render('bank-'+bank)
                    try:self.d.bank_ack(bank,value['id'],value['serial'],'obs',**({'warm_epoch':value['warm_epoch']} if 'warm_epoch' in value else {}))
                    except (ValueError,ObsError):pass
        self.worker=threading.Thread(target=run);self.worker.start();return self
    def __exit__(self,*args):self.stop.set();self.worker.join(2)

class HiddenOperations(unittest.TestCase):
    setUp=visibility.NativeVisibility.setUp
    tearDown=visibility.NativeVisibility.tearDown
    do=visibility.NativeVisibility.do
    ack=visibility.NativeVisibility.ack
    item=visibility.NativeVisibility.item
    def preview_take(self,mode,title=None):
        self.do('stage_patch',fields={'mode':mode,'composition':{'elements':[]}})
        if title:self.do('compose',title=title,duration=30)
        self.do('preview',target='obs');self.d.preview_ack(self.d.stage_id)
        deadline=time.monotonic()+1
        while not self.d.state()['rendered_ready'] and time.monotonic()<deadline:time.sleep(.01)
        self.assertTrue(self.d.state()['rendered_ready'])
        self.do('take')

    def test_three_modes_then_blank_live_clear_hydrate_clear_restore(self):
        with VisibleRenderer(self.d,self.sim):
            for mode in ('starting','brb','ending'):
                self.preview_take(mode);base=self.d.native.snapshot()
                self.preview_take(mode,'Transientcheck');self.do('clear')
                self.assertFalse(self.item(self.sim.program)['sceneItemEnabled'])
                expected=next(x for x in base['geometry'][base['program']] if x['source']==BASES[mode])
                actual=next(x for x in self.d.native.snapshot()['geometry'][self.sim.program] if x['source']==BASES[mode])
                self.assertEqual(actual,expected)
            self.preview_take('live');scene=self.sim.program
            self.do('clear');blank=self.d.native.snapshot()
            self.assertFalse(self.item(scene)['sceneItemEnabled'])
            self.do('audience',enabled=True)
            self.assertEqual(self.d.audience('local',cue='Director show Hydrate!')['result'],'fixed cue accepted')
            self.assertTrue(self.item(scene)['sceneItemEnabled'])
            self.assertFalse(self.d.program['composition']['elements'])
            self.do('clear');self.assertFalse(self.item(scene)['sceneItemEnabled'])
            self.do('restore');self.assertTrue(self.item(scene)['sceneItemEnabled'])
            self.assertEqual(self.d.alert['title'],'Hydrate!')
            self.assertEqual(self.sim.program,scene)

    def test_clear_already_hidden_needs_no_invisible_paint_or_ack(self):
        before=self.d.native.snapshot();bank=self.d.program_bank
        self.d.bank_ready={'A':None,'B':None}
        result=self.do('clear')
        self.assertTrue(result['armed']);self.assertFalse(result['bank_readiness'][bank])
        self.assertFalse(self.item(self.sim.program)['sceneItemEnabled'])
        self.assertEqual(self.d.native.snapshot(),before)
        self.assertIsNotNone(self.d.checkpoint)

    def test_authored_hidden_restore_prepaints_without_changing_program_then_restores_preview(self):
        with VisibleRenderer(self.d,self.sim):
            self.preview_take('starting','Saved original')
            saved=self.d.native.snapshot();self.do('clear')
            scene=self.sim.program;signature=self.d.native.fingerprint(scene);preview=self.sim.preview
            self.do('restore')
            self.assertTrue(self.item(scene)['sceneItemEnabled'])
            self.assertEqual(self.d.program['composition']['elements'][1]['text'],'Saved original')
            self.assertEqual(self.d.native.snapshot(),saved)

    def test_fixed_hydrate_on_hidden_blank_live_requires_visible_preview_prepaint(self):
        with VisibleRenderer(self.d,self.sim):
            self.preview_take('live');scene=self.sim.program
            self.do('audience',enabled=True)
            self.assertFalse(self.item(scene)['sceneItemEnabled'])
            result=self.d.audience('local',cue='Director show Hydrate!')
            self.assertEqual(result['result'],'fixed cue accepted')
            self.assertEqual(self.d.alert['title'],'Hydrate!')
            self.assertTrue(self.item(scene)['sceneItemEnabled'])
            self.assertFalse(self.d.program['composition']['elements'])

    def begin_popup(self):
        results=[];errors=[]
        def run():
            try:results.append(self.d.audience('local',cue='Director show Hydrate!'))
            except Exception as exc:errors.append(exc)
        worker=threading.Thread(target=run);worker.start()
        deadline=time.monotonic()+1
        while worker.is_alive() and not self.d.in_flight and time.monotonic()<deadline:time.sleep(.005)
        self.assertTrue(self.d.in_flight)
        return worker,results,errors

    def blank_live(self):
        with VisibleRenderer(self.d,self.sim):self.preview_take('live')
        self.do('clear');self.do('audience',enabled=True)

    def test_popup_prepaint_keeps_program_hidden_until_exact_fresh_ack_and_restores_scratch(self):
        self.blank_live();before=self.d.native.snapshot();bank=self.sim.program[-1]
        old=copy.deepcopy(self.d.banks[bank]);inputs=copy.deepcopy(self.sim.inputs)
        worker,results,errors=self.begin_popup()
        try:
            self.assertEqual(self.sim.program,before['program'])
            self.assertFalse(self.item(self.sim.program)['sceneItemEnabled'])
            self.assertEqual(self.d.native.fingerprint(self.sim.program)[OVERLAYS[bank]]['enabled'],False)
            payload=self.d.render('bank-'+bank)
            self.assertFalse(payload['segment']['composition']['elements'])
            self.assertEqual(payload['alert']['title'],'Hydrate!')
            stale=self.d.bank_ack(bank,old['id'],old['serial'],'obs')
            self.assertTrue(stale['stale']);self.assertTrue(worker.is_alive())
            self.assertFalse(self.item(self.sim.program)['sceneItemEnabled'])
            self.d.bank_ack(bank,payload['id'],payload['serial'],'obs')
            worker.join(2);self.assertFalse(worker.is_alive());self.assertFalse(errors,errors)
            expected=copy.deepcopy(before)
            next(x for x in expected['geometry'][before['program']] if x['source']==OVERLAYS[bank])['enabled']=True
            self.assertEqual(self.d.native.snapshot(),expected)
            self.assertEqual(self.sim.inputs,inputs)
        finally:
            if worker.is_alive():self.do('arm',enabled=False)
            worker.join(6)

    def test_payload_cancel_or_connection_loss_stops_cleanup_and_rearm_preserves_checkpoint(self):
        for loss in (False,True):
            with self.subTest(loss=loss):
                if not self.d.obs_state['connected']:self.do('connect',password=self.sim.password,port=self.sim.port)
                if not self.d.armed:self.do('arm',enabled=True)
                self.blank_live();original=self.d.native.snapshot()
                self.do('checkpoint');anchor=copy.deepcopy(self.d.anchor)
                worker,results,errors=self.begin_popup()
                try:
                    if loss:
                        with self.d.lock:self.d.native.client.close()
                        self.d.probe()
                    else:self.do('arm',enabled=False)
                    offset=len(self.sim.requests);worker.join(1)
                    self.assertFalse(worker.is_alive());self.assertFalse(results);self.assertEqual(len(errors),1)
                    self.assertFalse(any(k.startswith(('Set','Create','Remove','Trigger')) for k in self.sim.requests[offset:]))
                    self.assertIsNotNone(self.d.payload_recovery);self.assertEqual(self.d.anchor,anchor)
                    if loss:self.do('connect',password=self.sim.password,port=self.sim.port)
                    self.do('arm',enabled=True)
                    self.assertIsNone(self.d.payload_recovery)
                    self.assertEqual(self.d.native.snapshot(),original);self.assertEqual(self.d.anchor,anchor)
                finally:worker.join(6)

    def test_default_review_expiry_requires_explicit_fresh_repreview(self):
        with VisibleRenderer(self.d,self.sim):
            self.do('scene',mode='brb',target='obs');self.d.preview_ack(self.d.stage_id)
            deadline=time.monotonic()+1
            while not self.d.state()['rendered_ready'] and time.monotonic()<deadline:time.sleep(.01)
            self.assertTrue(self.d.state()['rendered_ready']);bank=self.sim.preview[-1]
            self.assertFalse(self.item(self.sim.preview)['sceneItemEnabled'])
            self.do('approve_agent_take')
            self.d.bank_ready[bank]['received']-=3
            self.assertTrue(self.d.state()['preview_refresh_required'])
            self.assertFalse(self.d.agent_state()['agent_take_approved'])
            self.assertFalse(self.d.state()['rendered_ready'])
            with self.assertRaises(ValueError):self.do('take')
            with self.assertRaises(ValueError):self.do('approve_agent_take')
            self.do('preview',target='obs');self.d.preview_ack(self.d.stage_id)
            deadline=time.monotonic()+1
            while not self.d.state()['rendered_ready'] and time.monotonic()<deadline:time.sleep(.01)
            self.assertTrue(self.d.state()['rendered_ready']);self.do('approve_agent_take')
            self.d.execute_agent({'action':'take'},self.d.version)
            self.assertFalse(self.item(self.sim.program)['sceneItemEnabled'])

if __name__=='__main__':unittest.main()
