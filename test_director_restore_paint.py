"""Recorded restore completion effects; simulated protocol/paint, never OBS pixels."""
import copy
import threading
import time
import unittest
from unittest.mock import patch
import test_director_banks as banks
import test_director_transitions as transitions


class RestorePaint(unittest.TestCase):
    setUp = banks.BankContract.setUp
    tearDown = banks.BankContract.tearDown
    do = banks.BankContract.do
    ack = banks.BankContract.ack
    def exercise_restore(self, modes):
        self.do('compose',title='Saved authored checkpoint')
        self.do('preview',target='obs');self.ack();self.do('take')
        self.do('checkpoint')
        historical = copy.deepcopy(self.d.banks)
        for mode in modes:
            self.do('scene', mode=mode, target='obs'); self.ack(); self.do('take')
        old = copy.deepcopy(self.d.banks)
        bank = self.d.anchor['native']['program'][-1]
        result = []; errors = []
        def restore():
            try: result.append(self.do('restore'))
            except Exception as exc: errors.append(exc)
        worker = threading.Thread(target=restore); worker.start()
        try:
            deadline = time.monotonic()+1
            while not self.d.in_flight and worker.is_alive() and time.monotonic()<deadline:
                time.sleep(.005)
            self.assertTrue(worker.is_alive(), 'Restore returned before recovered bank paint')
            value = self.d.render('bank-'+bank)
            self.assertGreater(value['id'], max(p['id'] for p in old.values()))
            self.assertEqual(value['segment'], historical[bank]['segment'])
            ignored = self.d.bank_ack(bank,historical[bank]['id'],historical[bank]['serial'],'obs')
            self.assertTrue(ignored['stale'])
            self.assertFalse(self.d._bank_is_ready(bank))
            self.assertTrue(worker.is_alive())
            other = 'B' if bank=='A' else 'A'
            self.assertEqual(self.d.banks[other], old[other])
            self.d.bank_ack(bank,value['id'],value['serial'],'obs')
            worker.join(2)
            self.assertFalse(worker.is_alive(), 'ACK deadlocked behind action lock')
            self.assertFalse(errors, errors)
            self.assertEqual(self.d.banks[bank]['id'],value['id'])
            self.assertTrue(self.d._bank_is_ready(bank))
            self.assertEqual(len(result),1)
        finally:
            worker.join(6)

    def test_missing_paint_disarms_without_native_restore_or_mutation_retry(self):
        from director_obs import ObsError
        self.do('compose',title='Saved authored checkpoint');self.do('preview',target='obs');self.ack();self.do('take')
        self.do('checkpoint')
        self.do('scene',mode='ending',target='obs'); self.ack(); self.do('take')
        offset = len(self.sim.requests)
        with self.assertRaisesRegex(ObsError,'did not render'):
            self.do('restore')
        self.assertFalse(self.d.armed)
        self.assertIsNotNone(self.d.anchor)
        self.assertFalse(set(self.sim.requests[offset:]) & {'SetCurrentProgramScene','SetSceneItemTransform'})

    def test_same_bank_restore_requires_fresh_paint(self):
        self.exercise_restore(('live','brb','ending','ending'))

    def test_opposite_bank_restore_keeps_fresh_paint_identity(self):
        self.exercise_restore(('ending',))


class DelayedRestoreReadback(unittest.TestCase):
    setUp = transitions.TransitionRegression.setUp
    tearDown = transitions.TransitionRegression.tearDown
    def test_final_preview_readback_can_settle_after_ack_without_mutation_retry(self):
        saved = self.native.snapshot()
        self.native.preview('ending','pip'); self.native.take()
        original = self.sim.rpc
        pending = [0]
        def delayed(kind,data):
            value = original(kind,data)
            if kind=='SetCurrentPreviewScene': pending[0]=3
            if kind=='GetSceneList' and pending[0]:
                pending[0]-=1
                value['currentPreviewSceneName']='Director / Ending B'
            return value
        count = self.sim.requests.count('SetCurrentPreviewScene')
        with patch.object(self.sim,'rpc',side_effect=delayed):
            actual = self.native.restore(saved)
        self.assertEqual(actual,saved)
        self.assertEqual(pending[0],0)
        self.assertEqual(self.sim.requests.count('SetCurrentPreviewScene'),count+1)

    def test_unsettled_preview_times_out_without_retry(self):
        from director_obs import ObsError
        saved = self.native.snapshot()
        self.native.transition_timeout = .08
        original = self.sim.rpc
        def stale(kind,data):
            value = original(kind,data)
            if kind=='GetSceneList': value['currentPreviewSceneName']='Director / Ending B'
            return value
        count = self.sim.requests.count('SetCurrentPreviewScene')
        with patch.object(self.sim,'rpc',side_effect=stale):
            with self.assertRaisesRegex(ObsError,'timed out.*uncertain'):
                self.native.restore(saved)
        self.assertEqual(self.sim.requests.count('SetCurrentPreviewScene'),count+1)

if __name__=='__main__': unittest.main()
