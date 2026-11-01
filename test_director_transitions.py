"""Sanitized OBS Fade causal regression. Simulated effects, not real OBS acceptance."""
import unittest
import copy
import tempfile
import time
from unittest.mock import patch
from director import Director, ROOT
from director_obs import ObsClient, OwnedOBS, SCENES, ObsError
from director_simulator import SimulatedOBS


class Clock:
    def __init__(self): self.now = 0.0
    def __call__(self): return self.now
    def advance(self, seconds): self.now += seconds


class ObservedFade(SimulatedOBS):
    """Deterministic 300ms causal fixture, advancing only on cursor observations."""
    def __init__(self):
        self.test_clock = Clock()
        super().__init__(transition_seconds=.3, clock=self.test_clock)
    def rpc(self, kind, data):
        if kind == 'GetCurrentSceneTransitionCursor': self.test_clock.advance(.07)
        return super().rpc(kind, data)
    def finish_external_effects(self):
        self.test_clock.advance(1)


class TransitionRegression(unittest.TestCase):
    def setUp(self):
        self.sim = ObservedFade().__enter__()
        self.client = ObsClient(self.sim.password, port=self.sim.port)
        self.native = OwnedOBS(self.client)
        self.native.setup('Camera', 'Content')
        # Isolate the journey from initial setup's own transition in the old implementation.
        self.sim.finish_external_effects()
        self.client.req('GetSceneList')
        self.client.req('SetCurrentPreviewScene', {'sceneName': SCENES['starting'][0]})
    def tearDown(self): self.client.close(); self.sim.__exit__()

    def test_fixture_ack_and_new_program_precede_late_preview_swap(self):
        old = self.sim.program
        target = SCENES['live'][1]
        self.client.req('SetCurrentProgramScene', {'sceneName': target})
        self.assertEqual(self.client.req('GetSceneList')['currentProgramSceneName'], target)
        self.assertIsNotNone(self.sim.transition)
        self.assertLess(self.client.req('GetCurrentSceneTransitionCursor')['transitionCursor'], 1.0)
        self.client.req('SetCurrentPreviewScene', {'sceneName': SCENES['ending'][0]})
        self.sim.finish_external_effects()
        self.assertEqual(self.client.req('GetSceneList')['currentPreviewSceneName'], old)
        self.assertEqual(self.client.req('GetCurrentSceneTransitionCursor')['transitionCursor'], 1.0)

    def test_take_does_not_confirm_while_fade_remains_active(self):
        self.native.preview('starting', 'pip')
        count = self.sim.requests.count('SetCurrentProgramScene')
        actual = self.native.take()
        self.assertEqual(self.sim.requests.count('SetCurrentProgramScene'), count+1)
        self.assertIsNone(self.sim.transition, 'Immediate program readback is not Fade completion')
        self.assertEqual(actual['currentPreviewSceneName'], SCENES['starting'][0])

    def test_next_preview_survives_previous_take_completion(self):
        self.native.preview('starting', 'pip'); self.native.take()
        self.native.preview('live', 'pip')
        expected = self.native.prepared['target']
        self.sim.finish_external_effects()
        self.assertEqual(self.client.req('GetSceneList')['currentPreviewSceneName'], expected,
                         'Previous Fade completion overwrote the next preview')
        self.native.take()

    def test_restore_saved_preview_is_applied_after_program_transition(self):
        saved = self.native.snapshot()
        self.native.preview('ending', 'pip'); self.native.take()
        self.sim.finish_external_effects(); self.client.req('GetSceneList')
        self.native.restore(saved)
        self.sim.finish_external_effects()
        actual = self.native.snapshot()
        self.assertEqual(actual, saved, 'Late program-transition completion overwrote restored preview')

    def test_inflight_external_transition_finishes_before_preview_geometry_or_selection(self):
        self.client.req('SetCurrentProgramScene', {'sceneName': SCENES['starting'][1]})
        self.sim.effects.clear()
        self.native.preview('live', 'pip')
        self.assertIsNone(self.sim.transition)
        self.assertEqual(self.sim.effects[0]['effect'], 'transition_complete')
        mutations = [effect for effect in self.sim.effects if effect['effect'] in ('preview_set','transform_set')]
        self.assertTrue(mutations)
        self.assertTrue(all(not effect['during_transition'] for effect in mutations))
        self.sim.finish_external_effects()
        self.assertEqual(self.client.req('GetSceneList')['currentPreviewSceneName'], self.native.prepared['target'])

    def test_restore_program_completion_precedes_saved_preview_mutation(self):
        self.client.req('SetCurrentPreviewScene', {'sceneName': SCENES['brb'][1]})
        saved = self.native.snapshot()
        self.native.preview('ending', 'pip'); self.native.take()
        count = self.sim.requests.count('SetCurrentProgramScene')
        self.sim.effects.clear()
        self.native.restore(saved)
        self.assertEqual(self.sim.requests.count('SetCurrentProgramScene'), count+1)
        relevant = [effect['effect'] for effect in self.sim.effects if effect['effect'] != 'transform_set']
        self.assertEqual(relevant, ['program_ack','transition_complete','preview_set'])
        self.assertEqual(self.native.snapshot(), saved)


class DirectorTransitionFailure(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT, prefix='.director-test-')
        self.sim = ObservedFade().__enter__()
        self.d = Director(data_dir=self.tmp.name)
        self.do('connect', password=self.sim.password, port=self.sim.port)
        self.do('setup', camera='Camera', content='Content'); self.do('arm', enabled=True)
    def tearDown(self): self.d.close(); self.sim.__exit__(); self.tmp.cleanup()
    def do(self, action, **kw):
        if action == 'arm' and kw.get('enabled') is True:
            from test_director_cold_renderers import ColdRenderer
            with ColdRenderer(self.d,self.sim):return self.d.execute({'action':action,**kw},self.d.version)
        return self.d.execute({'action':action,**kw},self.d.version)
    def prepare(self):
        self.do('preview', target='obs')
        self.d.preview_ack(self.d.stage_id)
        bank = self.d.native.prepared['bank']; value = self.d.render('bank-'+bank)
        self.d.bank_ack(bank, value['id'], value['serial'], 'obs')
        return bank

    def test_stalled_take_times_out_disarms_retains_banks_and_checkpoint_without_retry(self):
        bank = self.prepare()
        old_bank = self.d.program_bank
        banks = copy.deepcopy(self.d.banks)
        self.d.native.transition_timeout = .08; self.sim.transition_stuck = True
        count = self.sim.requests.count('SetCurrentProgramScene')
        started = time.monotonic()
        with self.assertRaisesRegex(ObsError, 'timed out.*uncertain'): self.do('take')
        self.assertLess(time.monotonic()-started, .4)
        self.assertEqual(self.sim.requests.count('SetCurrentProgramScene'), count+1)
        self.assertFalse(self.d.armed); self.assertTrue(self.d.state()['can_restore'])
        self.assertEqual(self.d.program_bank, old_bank)
        self.assertEqual(self.d.banks[old_bank], banks[old_bank])
        self.assertEqual(self.d.banks[bank], banks[bank])

    def test_stalled_existing_fade_cannot_republish_or_reposition_the_old_bank(self):
        self.d.native.req('SetCurrentProgramScene', {'sceneName': SCENES['starting'][1]})
        self.sim.transition_stuck = True; self.d.native.transition_timeout = .08
        before = copy.deepcopy(self.d.banks)
        offset = len(self.sim.requests)
        with self.assertRaises(ObsError): self.do('preview', target='obs')
        self.assertFalse(self.d.armed)
        self.assertEqual(self.d.banks, before)
        self.assertFalse(set(self.sim.requests[offset:]) & {'SetCurrentPreviewScene','SetSceneItemTransform','SetCurrentProgramScene'})

    def test_refused_or_invalid_cursor_refuses_preview_and_disarms(self):
        self.sim.refuse_on = 'GetCurrentSceneTransitionCursor'
        with self.assertRaises(ObsError): self.do('preview', target='obs')
        self.assertFalse(self.d.armed)
        self.do('arm', enabled=True)
        original = self.sim.rpc
        def invalid(kind, data):
            if kind == 'GetCurrentSceneTransitionCursor': return {'transitionCursor': float('nan')}
            return original(kind, data)
        with patch.object(self.sim, 'rpc', side_effect=invalid):
            with self.assertRaisesRegex(ObsError, 'cursor readback invalid'): self.do('preview', target='obs')
        self.assertFalse(self.d.armed)

    def test_completed_take_keeps_rendered_identity_and_releases_the_current_pose(self):
        self.do('compose', title='Resident during Fade', duration=8)
        bank = self.prepare()
        prepared = self.d.render('bank-'+bank)
        old_bank = self.d.program_bank; old = copy.deepcopy(self.d.banks[old_bank])
        self.do('take')
        actual = self.d.render('bank-'+bank)
        self.assertIsNone(self.sim.transition)
        self.assertEqual((actual['id'],actual['serial'],actual['segment']), (prepared['id'],prepared['serial'],prepared['segment']))
        self.assertAlmostEqual(actual['started'], prepared['started'], delta=.01)
        self.assertEqual(self.d.banks[old_bank], old)

if __name__ == '__main__': unittest.main()
