"""Browser availability/renderer-loss boundaries against SIMULATED owned OBS only."""
import copy
import tempfile
import unittest
import threading
import urllib.request
from director_server import make_server
from pathlib import Path
from director import Director, ROOT, Conflict
from director_obs import ObsError
from director_simulator import SimulatedOBS
from test_director_cold_renderers import ColdRenderer


class BrowserBoundary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT, prefix='.director-test-')
        self.sim = SimulatedOBS().__enter__()
        self.d = Director(data_dir=Path(self.tmp.name))
        self.do('connect', password=self.sim.password, port=self.sim.port)

    def tearDown(self):
        self.d.close(); self.sim.__exit__(); self.tmp.cleanup()

    def do(self, action, **fields):
        return self.d.execute({'action': action, **fields}, self.d.version)

    def test_missing_browser_kind_refuses_before_creating_owned_scenes(self):
        self.sim.input_kinds.remove('browser_source')
        before = copy.deepcopy((self.sim.scenes, self.sim.inputs, self.sim.program))
        with self.assertRaisesRegex(ObsError, 'Browser sources unavailable'):
            self.do('setup', camera='Camera', content='Content')
        self.assertEqual((self.sim.scenes, self.sim.inputs, self.sim.program), before)
        self.assertFalse(self.d.armed)
        self.assertFalse(self.d.agent_state()['rendered_ready'])
        self.assertFalse(any(r.startswith(('Create', 'Set', 'Remove')) for r in self.sim.requests))

    def test_operator_local_fixture_setup_never_uses_remote_default_url(self):
        self.do('setup', fixtures=True)
        self.assertEqual(set(self.d.bindings), {'camera','content'})
        for role, binding in self.d.bindings.items():
            self.assertEqual(binding['name'], 'Director / Fixture '+role.title())
            settings = self.sim.inputs[binding['name']]['settings']
            self.assertEqual(settings['url'], f'http://127.0.0.1:{self.d.port}/fixture-{role}.html')
            self.assertFalse(settings['shutdown'])
        self.assertFalse(self.d.armed)
        inputs = copy.deepcopy(self.sim.inputs)
        self.do('setup',fixtures=True)
        self.assertEqual(self.sim.inputs,inputs)
        with self.assertRaises(ValueError): self.d.execute_agent({'action':'setup','fixtures':True},self.d.version)

    def test_local_fixture_setup_rejects_unowned_conflict_and_active_outputs(self):
        self.sim.inputs['Director / Fixture Camera'] = {'kind':'test_camera','settings':{}}
        with self.assertRaises(ObsError): self.do('setup',fixtures=True)
        self.assertFalse(any(r.startswith(('Create','Set','Remove')) for r in self.sim.requests))
        del self.sim.inputs['Director / Fixture Camera']
        self.sim.active=True
        with self.assertRaises(ObsError):self.do('setup',fixtures=True)
        self.assertFalse(any(r.startswith(('Create','Set','Remove')) for r in self.sim.requests))

    def test_local_camera_content_fixtures_are_scriptless_same_origin_assets(self):
        server = make_server(0, director=self.d)
        worker = threading.Thread(target=server.serve_forever)
        worker.start()
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for name in ('camera','content'):
                with opener.open(f'http://127.0.0.1:{server.server_port}/fixture-{name}.html', timeout=2) as response:
                    body = response.read().decode()
                    self.assertEqual(response.status, 200)
                    self.assertIn("default-src 'self'", response.headers['Content-Security-Policy'])
                    self.assertIn('text/html',response.headers['Content-Type'])
                for prohibited in ('<script','http:', 'https:', '<iframe','<video','<audio','<input'):
                    self.assertNotIn(prohibited,body.lower())
                self.assertIn('fixture',body.lower())
        finally:
            server.shutdown(); server.server_close(); worker.join(timeout=3)
        self.assertFalse(worker.is_alive())

    def test_renderer_ack_expiry_removes_exact_review_and_take_authority(self):
        self.do('setup', camera='Camera', content='Content')
        with ColdRenderer(self.d, self.sim): self.do('arm', enabled=True)
        self.do('destination', target='obs')
        self.do('compose', title='Local renderer lifecycle fixture')
        self.do('preview', target='obs')
        self.d.preview_ack(self.d.stage_id)
        bank = self.d.native.prepared['bank']; payload = self.d.render('bank-'+bank)
        self.d.bank_ack(bank, payload['id'], payload['serial'], 'obs')
        before = self.d.agent_state(); old_program = self.sim.program
        self.assertTrue(before['rendered_ready'])
        self.d.operator_review(before['native_review'], before['version'], 'approve')
        self.assertTrue(self.d.agent_state()['agent_take_approved'])
        # Simulated lost renderer heartbeat, not a real CEF crash or GPU proof.
        self.d.bank_ready[bank]['received'] -= 3
        expired = self.d.agent_state()
        self.assertFalse(expired['rendered_ready'])
        self.assertFalse(expired['agent_take_approved'])
        self.assertIsNone(expired['native_review'])
        with self.assertRaises((ValueError, Conflict)):
            self.d.execute_agent({'action':'take'}, self.d.version)
        self.assertEqual(self.sim.program, old_program)
        self.assertEqual(self.d.banks[bank]['id'], payload['id'])


if __name__ == '__main__': unittest.main()
