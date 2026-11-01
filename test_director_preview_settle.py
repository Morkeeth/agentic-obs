"""Delayed rehearsal readbacks, simulated OBS protocol only."""
import unittest
from unittest.mock import patch
import test_director_transitions as transitions
from director_obs import ObsError, SCENES

class PreviewObservation(unittest.TestCase):
    setUp = transitions.DirectorTransitionFailure.setUp
    tearDown = transitions.DirectorTransitionFailure.tearDown
    do = transitions.DirectorTransitionFailure.do

    def observe(self, forever=False, program_change=False):
        original = self.sim.rpc
        pending = [False]; reads = [0]
        def delayed(kind, data):
            value = original(kind, data)
            if kind == 'SetCurrentPreviewScene': pending[0] = True
            if kind == 'GetSceneList' and pending[0]:
                reads[0] += 1
                if forever or reads[0] <= 3:
                    value['currentPreviewSceneName'] = SCENES['ending'][0]
                if program_change: value['currentProgramSceneName'] = SCENES['brb'][0]
            return value
        return patch.object(self.sim, 'rpc', side_effect=delayed), reads

    def test_delayed_preview_settles_without_repeating_setter_or_program_change(self):
        before = self.sim.program
        count = self.sim.requests.count('SetCurrentPreviewScene')
        observer, reads = self.observe()
        with observer: self.do('preview', target='obs')
        self.assertGreater(reads[0], 3)
        self.assertEqual(self.sim.program, before)
        self.assertEqual(self.sim.requests.count('SetCurrentPreviewScene'), count+1)
        self.assertEqual(self.d.native.prepared['program'], before)

    def test_unconfirmed_preview_disarms_and_does_not_retry(self):
        self.d.native.transition_timeout = .08
        count = self.sim.requests.count('SetCurrentPreviewScene')
        observer, _ = self.observe(forever=True)
        with observer, self.assertRaises(ObsError): self.do('preview', target='obs')
        self.assertFalse(self.d.armed)
        self.assertIsNone(self.d.native.prepared)
        self.assertEqual(self.sim.requests.count('SetCurrentPreviewScene'), count+1)

    def test_changed_program_cannot_authorize_preview(self):
        self.d.native.transition_timeout = .08
        observer, _ = self.observe(program_change=True)
        with observer, self.assertRaises(ObsError): self.do('preview', target='obs')
        self.assertFalse(self.d.armed)
        self.assertIsNone(self.d.native.prepared)

if __name__ == '__main__': unittest.main()
