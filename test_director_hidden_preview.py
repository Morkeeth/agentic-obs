"""Later hidden payloads can stall again after successful arm. Simulated lifecycle only."""
import copy
import threading
import time
import unittest
import test_director_native_visibility as visibility
from director_obs import OVERLAYS, ObsError

class LaterPayloadRenderer:
    def __init__(self,d,sim):self.d=d;self.sim=sim;self.frames=set();self.stop=threading.Event()
    def __enter__(self):
        def run():
            while not self.stop.wait(.01):
                for bank in ('A','B'):
                    value=self.d.render('bank-'+bank);key=(bank,value['id'],value['serial'])
                    visible=any(x['sourceName']==OVERLAYS[bank] and x['sceneItemEnabled']
                                for scene in (self.sim.program,self.sim.preview) for x in self.sim.scenes.get(scene,[]))
                    if visible:self.frames.add(key)
                    if key in self.frames:
                        try:self.d.bank_ack(bank,value['id'],value['serial'],'obs')
                        except (ValueError,ObsError):pass
        self.worker=threading.Thread(target=run);self.worker.start();return self
    def __exit__(self,*args):self.stop.set();self.worker.join(2)

class HiddenPreview(unittest.TestCase):
    setUp=visibility.NativeVisibility.setUp
    tearDown=visibility.NativeVisibility.tearDown
    do=visibility.NativeVisibility.do
    ack=visibility.NativeVisibility.ack
    item=visibility.NativeVisibility.item
    with_renderer=visibility.NativeVisibility.with_renderer
    clear=visibility.NativeVisibility.clear

    def preceding_sequence(self):
        self.do('scene',mode='starting',target='obs');self.ack();self.do('take')
        self.do('compose',title='Transientcheck',duration=30)
        self.do('preview',target='obs');self.ack();self.do('take');self.clear()
        for bank in ('A','B'):
            if self.d.bank_ready[bank]:self.d.bank_ready[bank]['received']-=9

    def test_later_empty_mode_payload_can_render_in_preview_then_finalizes_hidden(self):
        self.preceding_sequence()
        scene=self.sim.program;before=self.d.native.fingerprint(scene);payload=copy.deepcopy(self.d.banks[scene[-1]])
        with LaterPayloadRenderer(self.d,self.sim):
            self.do('scene',mode='brb',target='obs');self.d.preview_ack(self.d.stage_id)
            deadline=time.monotonic()+1
            while not self.d.state()['rendered_ready'] and time.monotonic()<deadline:time.sleep(.01)
            self.assertTrue(self.d.state()['rendered_ready'],'A previously warmed hidden bank stalled on a later mode/payload')
            self.assertFalse(self.item(self.sim.preview)['sceneItemEnabled'])
            self.assertEqual(self.d.native.fingerprint(scene),before)
            self.assertEqual(self.d.banks[scene[-1]],payload);self.assertEqual(self.sim.program,scene)
            with self.assertRaisesRegex(ValueError,'operator approval'):self.d.execute_agent({'action':'take'},self.d.version)
            self.do('approve_agent_take');self.d.execute_agent({'action':'take'},self.d.version)
            self.assertFalse(self.item(self.sim.program)['sceneItemEnabled'])

    def test_authored_preview_is_visible_but_unapproved_until_fresh_ack(self):
        self.preceding_sequence();scene=self.sim.program;before=self.d.native.fingerprint(scene)
        self.do('stage_patch',fields={'mode':'live'});self.do('compose',title='Later arbitrary authored graphic')
        self.do('preview',target='obs');target=self.sim.preview;bank=target[-1]
        self.assertTrue(self.item(target)['sceneItemEnabled'],'Inactive preview visibility must precede its ACK')
        value=self.d.render('bank-'+bank);self.d.preview_ack(self.d.stage_id)
        with self.assertRaises(ValueError):self.do('take')
        with self.assertRaises(ValueError):self.do('approve_agent_take')
        with self.assertRaises(ValueError):self.d.bank_ack(bank,value['id']-1,value['serial'],'obs')
        self.assertFalse(self.d.state()['rendered_ready'])
        self.assertTrue(self.d.probe()['armed'],'Expected preparation visibility must be fingerprinted')
        self.d.bank_ack(bank,value['id'],value['serial'],'obs')
        self.assertTrue(self.item(target)['sceneItemEnabled'])
        self.assertEqual(self.sim.program,scene);self.assertEqual(self.d.native.fingerprint(scene),before)
        self.assertFalse(self.d.agent_state()['agent_take_approved'])
        self.do('take')  # Deliberate one-step operator take still works.

    def test_unexpected_preview_geometry_before_ack_disarms_without_program_mutation(self):
        self.do('scene',mode='brb',target='obs');target=self.sim.preview;bank=target[-1]
        before=self.sim.program
        self.item(target)['transform']['positionX']+=17
        value=self.d.render('bank-'+bank)
        with self.assertRaisesRegex(ObsError,'layout changed'):self.d.bank_ack(bank,value['id'],value['serial'],'obs')
        self.assertFalse(self.d.armed);self.assertEqual(self.sim.program,before)

    def test_changed_program_before_ack_cannot_finalize_a_now_active_bank(self):
        self.do('scene',mode='brb',target='obs');target=self.sim.preview;bank=target[-1]
        value=self.d.render('bank-'+bank)
        self.sim.program=target  # Independent external scene change, never an authorized director take.
        offset=len(self.sim.requests)
        with self.assertRaises(ObsError):self.d.bank_ack(bank,value['id'],value['serial'],'obs')
        self.assertFalse(self.d.armed)
        self.assertEqual(self.sim.program,target)
        self.assertFalse(any(k.startswith(('Set','Create','Remove','Trigger')) for k in self.sim.requests[offset:]))

    def test_disarm_or_loss_cannot_finalize_visibility_after_ack(self):
        for lose_connection in (False,True):
            with self.subTest(loss=lose_connection):
                if not self.d.obs_state['connected']:
                    self.do('connect',password=self.sim.password,port=self.sim.port)
                if not self.d.armed:self.do('arm',enabled=True)
                self.do('scene',mode='ending',target='obs');bank=self.sim.preview[-1]
                value=self.d.render('bank-'+bank)
                if lose_connection:
                    with self.d.lock:self.d.native.client.close()
                    self.d.probe()
                else:self.do('arm',enabled=False)
                offset=len(self.sim.requests)
                self.d.bank_ack(bank,value['id'],value['serial'],'obs')
                self.assertFalse(self.d.armed)
                self.assertFalse(any(k.startswith(('Set','Create','Remove','Trigger')) for k in self.sim.requests[offset:]))
                self.assertFalse(self.d.state()['rendered_ready'])

if __name__=='__main__':unittest.main()
