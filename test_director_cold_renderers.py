"""Measured cold/visible/hidden lifecycle effects. Simulated OBS, not real frames."""
import copy
import tempfile
import threading
import time
import unittest
from director import Director, ROOT, Conflict
from director_obs import OVERLAYS, SCENES, ObsError
from director_simulator import SimulatedOBS

class ColdRenderer:
    """No ACK until source is enabled in program/preview; then hidden heartbeats continue."""
    def __init__(self,d,sim):self.d=d;self.sim=sim;self.hot=set();self.stop=threading.Event();self.worker=None
    def __enter__(self):
        def run():
            while not self.stop.wait(.01):
                for bank in ('A','B'):
                    for scene in (self.sim.program,self.sim.preview):
                        if any(x['sourceName']==OVERLAYS[bank] and x['sceneItemEnabled'] for x in self.sim.scenes.get(scene,[])):
                            self.hot.add(bank)
                    if bank not in self.hot:continue
                    payload=self.d.render('bank-'+bank)
                    args={'warm_epoch':payload['warm_epoch']} if 'warm_epoch' in payload else {}
                    try:self.d.bank_ack(bank,payload['id'],payload['serial'],'obs',**args)
                    except (ValueError,ObsError):pass
        self.worker=threading.Thread(target=run);self.worker.start();return self
    def __exit__(self,*args):self.stop.set();self.worker.join(2)

class ColdBanks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT,prefix='.director-test-')
        self.sim=SimulatedOBS().__enter__();self.d=Director(data_dir=self.tmp.name)
        self.do('connect',password=self.sim.password,port=self.sim.port)
        self.do('setup',camera='Camera',content='Content')
    def tearDown(self):self.d.close();self.sim.__exit__();self.tmp.cleanup()
    def do(self,action,**kw):return self.d.execute({'action':action,**kw},self.d.version)

    def test_explicit_arm_wakes_both_cold_banks_and_restores_preview_and_program(self):
        before=self.d.native.snapshot();payloads=copy.deepcopy(self.d.banks)
        self.do('checkpoint');anchor=copy.deepcopy(self.d.anchor)
        with ColdRenderer(self.d,self.sim) as renderer:
            result=self.do('arm',enabled=True)
            self.assertEqual(renderer.hot,{'A','B'},'Arm did not make either cold source render')
            self.assertTrue(all(result['bank_readiness'].values()))
            self.assertTrue(result['armed']);self.assertFalse(result['agent_take_approved'])
            self.assertEqual(self.d.native.snapshot(),before)
            self.assertEqual(self.d.banks,payloads);self.assertEqual(self.d.anchor,anchor)
            self.do('scene',mode='starting',target='obs')
            deadline=time.monotonic()+1
            while not self.d._bank_is_ready(self.d.native.prepared['bank']) and time.monotonic()<deadline:time.sleep(.01)
            self.assertTrue(self.d._bank_is_ready(self.d.native.prepared['bank']))
            self.assertFalse(self.d.native.graphics_item(self.sim.preview)['sceneItemEnabled'])

    def test_readonly_screenshot_does_not_wake_cold_but_warm_hidden_heartbeat_refreshes(self):
        with ColdRenderer(self.d,self.sim) as renderer:
            try:self.d.native.req('GetSourceScreenshot',{'sourceName':OVERLAYS['A'],'imageFormat':'png'})
            except ObsError:pass  # Synthetic server has no pixel renderer; readonly call cannot change fixture lifecycle.
            self.assertFalse(renderer.hot)
            self.do('arm',enabled=True)
            self.assertEqual(renderer.hot,{'A','B'})
            # A hot heartbeat arrives inside the TTL; a real gap now latches loss.
            for bank in ('A','B'):self.d.bank_ready[bank]['received']-=1
            deadline=time.monotonic()+1
            while not all(self.d._bank_is_ready(b) for b in ('A','B')) and time.monotonic()<deadline:time.sleep(.01)
            self.assertTrue(all(self.d._bank_is_ready(b) for b in ('A','B')))

    def test_post_restart_rearm_does_not_require_setup_or_drop_anchor(self):
        with ColdRenderer(self.d,self.sim):self.do('arm',enabled=True)
        self.do('checkpoint');saved=copy.deepcopy(self.d.anchor)
        self.do('disconnect');self.do('connect',password=self.sim.password,port=self.sim.port)
        self.d.bank_ready={'A':None,'B':None}
        offset=len(self.sim.requests)
        with ColdRenderer(self.d,self.sim) as renderer:
            self.do('arm',enabled=True);self.assertEqual(renderer.hot,{'A','B'})
        self.assertEqual(self.d.anchor,saved)
        self.assertFalse(set(self.sim.requests[offset:]) & {'CreateInput','CreateScene','CreateSceneItem','SetInputSettings','SetCurrentProgramScene'})

    def test_no_ack_cannot_arm_and_keeps_checkpoint(self):
        self.do('checkpoint');saved=copy.deepcopy(self.d.anchor)
        with self.assertRaisesRegex(ObsError,'render'):self.do('arm',enabled=True)
        self.assertFalse(self.d.armed);self.assertEqual(self.d.anchor,saved)

    def test_operator_cancel_during_unarmed_preparation_stops_all_further_writes(self):
        errors=[]
        def arm():
            try:self.do('arm',enabled=True)
            except Exception as exc:errors.append(exc)
        worker=threading.Thread(target=arm);worker.start()
        try:
            deadline=time.monotonic()+1
            while worker.is_alive() and not self.d.in_flight and time.monotonic()<deadline:time.sleep(.005)
            self.assertTrue(self.d.in_flight)
            self.do('arm',enabled=False)
            offset=len(self.sim.requests)
            worker.join(1);self.assertFalse(worker.is_alive());self.assertFalse(self.d.armed)
            self.assertEqual(len(errors),1)
            self.assertFalse(any(k.startswith(('Set','Create','Remove','Trigger')) for k in self.sim.requests[offset:]))
        finally:worker.join(6)

    def test_old_warm_epoch_cannot_authorize_preparation(self):
        errors=[]
        def arm():
            try:self.do('arm',enabled=True)
            except Exception as exc:errors.append(exc)
        worker=threading.Thread(target=arm);worker.start()
        try:
            deadline=time.monotonic()+1
            while not self.d.in_flight and time.monotonic()<deadline:time.sleep(.005)
            with self.d.lock:
                warming=copy.deepcopy(self.d.warming)
                payload=self.d.render('bank-'+warming['bank'])
                result=self.d.bank_ack(warming['bank'],payload['id'],payload['serial'],'obs',warm_epoch=warming['epoch']-1)
                self.assertTrue(result['stale']);self.assertFalse(self.d._bank_is_ready(warming['bank']))
            self.assertTrue(worker.is_alive())
            with ColdRenderer(self.d,self.sim):worker.join(2)
            self.assertFalse(worker.is_alive());self.assertFalse(errors,errors);self.assertTrue(self.d.armed)
        finally:
            if worker.is_alive():self.do('arm',enabled=False)
            worker.join(6)

    def test_connection_loss_stops_writes_and_next_operator_rearm_recovers_without_setup(self):
        self.do('checkpoint');anchor=copy.deepcopy(self.d.anchor)
        original=self.d.native.snapshot();errors=[]
        def arm():
            try:self.do('arm',enabled=True)
            except Exception as exc:errors.append(exc)
        worker=threading.Thread(target=arm);worker.start()
        try:
            deadline=time.monotonic()+1
            while not self.d.in_flight and time.monotonic()<deadline:time.sleep(.005)
            self.assertTrue(self.d.in_flight)
            with self.d.lock:self.d.native.client.close()
            offset=len(self.sim.requests)
            self.d.probe();worker.join(1)
            self.assertFalse(worker.is_alive());self.assertEqual(len(errors),1)
            self.assertFalse(any(k.startswith(('Set','Create','Remove','Trigger')) for k in self.sim.requests[offset:]))
            self.assertFalse(self.d.armed);self.assertIsNotNone(self.d.warm_recovery)
            self.do('connect',password=self.sim.password,port=self.sim.port)
            with ColdRenderer(self.d,self.sim):self.do('arm',enabled=True)
            self.assertEqual(self.d.anchor,anchor);self.assertEqual(self.d.native.snapshot(),original)
            self.assertIsNone(self.d.warm_recovery)
        finally:worker.join(6)

    def test_outputs_on_or_agent_request_cannot_authorize_warming(self):
        offset=len(self.sim.requests)
        with self.assertRaises(ValueError):self.d.execute_agent({'action':'arm','enabled':True},self.d.version)
        self.sim.active=True
        with self.assertRaises(ObsError):self.do('arm',enabled=True)
        self.assertFalse(self.d.armed)
        self.assertFalse(any(k.startswith(('Set','Create','Remove','Trigger')) for k in self.sim.requests[offset:]))

if __name__=='__main__':unittest.main()
