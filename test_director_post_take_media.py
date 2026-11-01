"""Post-cut state tests against simulated OBS protocol; no real media/audio proof."""
import copy
from pathlib import Path
import unittest
import test_director as existing
from director_obs import ObsError, SCENES


class PostTakeMedia(unittest.TestCase):
    setUp = existing.NativeIntegration.setUp
    tearDown = existing.NativeIntegration.tearDown
    do = existing.NativeIntegration.do
    preview = existing.NativeIntegration.preview

    def prepare(self):
        folder = Path(self.tmp.name)/'media'
        folder.mkdir(exist_ok=True)
        path = folder/'owned.wav'
        path.write_bytes(b'simulated-media')
        self.do('stage_patch', fields={'mode': 'brb', 'media': 'owned.wav'})
        self.preview()
        return path

    def test_confirmed_cut_commits_segment_before_media_failure(self):
        self.prepare()
        staged = copy.deepcopy(self.d.staged)
        checkpoint = copy.deepcopy(self.d.preview_checkpoint)
        self.d.timer_state = {'anchor': 0, 'offset': 5, 'running': True}
        self.d.vote_state = {'counts': [9, 8], 'open': True}
        self.d.voters = {'old': 0}
        self.d.alert = {'title': 'old alert'}
        self.sim.refuse_on = 'SetInputSettings'
        with self.assertRaises(ObsError): self.do('take')
        self.assertIn(self.sim.program, SCENES['brb'])
        self.assertEqual(self.d.program, staged, 'confirmed program must survive post-cut failure')
        self.assertIsNone(self.d.timer_state)
        self.assertIsNone(self.d.vote_state)
        self.assertEqual(self.d.voters, {})
        self.assertIsNone(self.d.alert)
        rendered = self.d.render('bank-'+self.d.program_bank)
        self.assertEqual(rendered['segment'], staged)
        for key in ('timer', 'vote', 'alert'): self.assertIsNone(rendered[key])
        self.assertIsNone(self.d.preview_requested)
        self.assertFalse(self.d.armed)
        self.assertEqual(self.d.media_status['state'], 'unknown')
        self.assertEqual(self.d.checkpoint, checkpoint)
        self.assertTrue(self.d.state()['can_restore'])
        self.assertNotIn(str(self.d.media_dir), self.d.error)
        self.assertEqual(self.sim.requests.count('SetInputSettings'), 1)

    def invalid_media_before_cut(self, symlink=False):
        path = self.prepare()
        before = self.d.native.snapshot()
        program = copy.deepcopy(self.d.program)
        path.unlink()
        if symlink: path.symlink_to(Path(self.tmp.name)/'missing.wav')
        offset = len(self.sim.requests)
        with self.assertRaisesRegex(ValueError, 'owned file'): self.do('take')
        self.assertEqual(self.sim.program, before['program'])
        self.assertEqual(self.d.program, program)
        self.assertNotIn('SetCurrentProgramScene', self.sim.requests[offset:])
        self.assertTrue(self.d.armed)

    def test_disappeared_staged_media_refused_before_cut(self):
        self.invalid_media_before_cut()

    def test_invalid_staged_media_refused_before_cut(self):
        self.invalid_media_before_cut(symlink=True)

    def test_successful_media_take_reports_readback(self):
        self.prepare()
        self.do('take')
        self.assertEqual(self.d.program['mode'], 'brb')
        self.assertEqual(self.d.media_status['volume'], .25)
        self.assertNotEqual(self.d.media_status['state'], 'unknown')
        self.assertTrue(self.d.armed)

    def test_stop_failure_also_commits_confirmed_cut(self):
        self.do('stage_patch', fields={'mode': 'ending'})
        self.preview()
        self.d.media_status = {'state': 'playing', 'volume': .25}
        self.sim.refuse_on = 'TriggerMediaInputAction'
        with self.assertRaises(ObsError): self.do('take')
        self.assertIn(self.sim.program, SCENES['ending'])
        self.assertEqual(self.d.program['mode'], 'ending')
        self.assertEqual(self.d.media_status['state'], 'unknown')
        self.assertFalse(self.d.armed)
