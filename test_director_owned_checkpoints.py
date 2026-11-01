"""Native review checkpoints reject unrelated scenes. Simulated OBS only."""
import copy
import unittest
import test_director_banks as banks
from director_obs import ObsError

class OwnedCheckpoints(unittest.TestCase):
    setUp=banks.BankContract.setUp
    tearDown=banks.BankContract.tearDown
    do=banks.BankContract.do

    def test_snapshot_rejects_unowned_program_or_preview_without_setters(self):
        for field in ('program','preview'):
            with self.subTest(field=field):
                old=getattr(self.sim,field);setattr(self.sim,field,'Scene')
                offset=len(self.sim.requests)
                try:
                    with self.assertRaisesRegex(ObsError,'not owned'):self.d.native.snapshot()
                    self.assertFalse(any(k.startswith(('Set','Create','Remove','Trigger')) for k in self.sim.requests[offset:]))
                finally:setattr(self.sim,field,old)

    def test_failed_restore_point_keeps_valid_anchor(self):
        self.do('checkpoint');saved=copy.deepcopy(self.d.anchor)
        self.sim.preview='Scene';offset=len(self.sim.requests)
        with self.assertRaisesRegex(ObsError,'not owned'):self.do('checkpoint')
        self.assertEqual(self.d.anchor,saved)
        self.assertEqual(self.sim.preview,'Scene')
        self.assertFalse(any(k.startswith(('Set','Create','Remove','Trigger')) for k in self.sim.requests[offset:]))

    def test_failed_preview_keeps_existing_checkpoint_and_has_no_setters(self):
        self.do('preview',target='obs')
        saved=copy.deepcopy(self.d.preview_checkpoint)
        self.sim.preview='Scene';offset=len(self.sim.requests)
        with self.assertRaisesRegex(ObsError,'not owned'):self.do('preview',target='obs')
        self.assertEqual(self.d.preview_checkpoint,saved)
        self.assertEqual(self.sim.preview,'Scene')
        self.assertFalse(any(k.startswith(('Set','Create','Remove','Trigger')) for k in self.sim.requests[offset:]))

    def test_direct_native_preview_rejects_unowned_preview_before_layout(self):
        self.sim.preview='Scene';offset=len(self.sim.requests)
        with self.assertRaisesRegex(ObsError,'not owned'):self.d.native.preview('live','pip')
        self.assertEqual(self.sim.preview,'Scene')
        self.assertFalse(any(k.startswith(('Set','Create','Remove','Trigger')) for k in self.sim.requests[offset:]))

if __name__=='__main__':unittest.main()
