"""Read-only probe and genuine loss during owned waits; simulated protocol only."""
import threading
import time
import unittest
from unittest.mock import patch
import test_director_banks as banks
from director_obs import SCENES, ObsError

class InflightReview(unittest.TestCase):
    setUp=banks.BankContract.setUp
    tearDown=banks.BankContract.tearDown
    do=banks.BankContract.do
    ack=banks.BankContract.ack

    def prepare(self):
        self.do('compose',title='Visible recovery point');self.do('preview',target='obs');self.ack();self.do('take')
        self.do('checkpoint')
        self.do('scene',mode='ending',target='obs');self.ack();self.do('take')
        self.do('scene',mode='live',target='obs')

    def begin(self,action):
        results=[];errors=[]
        def run():
            try:results.append(self.do(action))
            except Exception as exc:errors.append(exc)
        worker=threading.Thread(target=run);worker.start()
        deadline=time.monotonic()+1
        while worker.is_alive() and not self.d.in_flight and time.monotonic()<deadline:time.sleep(.005)
        self.assertTrue(self.d.in_flight)
        return worker,results,errors

    def acknowledge(self):
        for bank in ('A','B'):
            payload=self.d.render('bank-'+bank)
            self.d.bank_ack(bank,payload['id'],payload['serial'],'obs')

    def test_probe_does_not_apply_stale_prepared_comparison_during_owned_restore(self):
        self.prepare();worker,results,errors=self.begin('restore')
        original=self.sim.rpc
        def readback(kind,data):
            value=original(kind,data)
            if kind=='GetSceneList':value['currentPreviewSceneName']=SCENES['starting'][0]
            return value
        try:
            version=self.d.version
            with patch.object(self.sim,'rpc',side_effect=readback):state=self.d.probe()
            self.assertTrue(state['armed'],'Probe falsely disarmed an owned transaction on transitional preview readback')
            self.assertEqual(self.d.version,version)
            self.acknowledge();worker.join(2)
            self.assertFalse(worker.is_alive());self.assertFalse(errors,errors);self.assertEqual(len(results),1)
        finally:
            if worker.is_alive():self.acknowledge()
            worker.join(6)

    def test_genuine_disarm_cannot_continue_restore_or_report_clear_success_after_ack(self):
        for action in ('restore',):
            with self.subTest(action=action):
                if not self.d.armed:self.do('arm',enabled=True)
                self.prepare();worker,results,errors=self.begin(action)
                try:
                    offset=len(self.sim.requests)
                    with self.d.lock:self.d._obs_failed()
                    self.acknowledge();worker.join(1)
                    self.assertFalse(worker.is_alive())
                    self.assertFalse(results,'Disarmed transaction falsely reported completion')
                    self.assertEqual(len(errors),1);self.assertIsInstance(errors[0],ObsError)
                    self.assertFalse(any(k.startswith(('Set','Create','Remove','Trigger')) for k in self.sim.requests[offset:]))
                    self.assertTrue(self.d.state()['can_restore'])
                finally:
                    if worker.is_alive():self.acknowledge()
                    worker.join(6)

    def test_connection_loss_probe_wakes_waiter_without_ack_or_mutation(self):
        self.prepare();worker,results,errors=self.begin('restore')
        try:
            offset=len(self.sim.requests)
            with self.d.lock:self.d.native.client.close()
            state=self.d.probe();self.assertFalse(state['armed'])
            worker.join(1)
            self.assertFalse(worker.is_alive(),'Genuine connection loss must wake the render wait')
            self.assertFalse(results);self.assertEqual(len(errors),1)
            self.assertFalse(any(k.startswith(('Set','Create','Remove','Trigger')) for k in self.sim.requests[offset:]))
            self.assertTrue(self.d.state()['can_restore'])
        finally:worker.join(6)

if __name__=='__main__':unittest.main()
