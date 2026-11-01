"""Native operator setup HTTP boundary; simulated OBS, never real configuration."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import time
import urllib.error
import unittest
import urllib.request
from director import Director,ROOT,Conflict
from director_server import make_server
from director_simulator import SimulatedOBS
from director_obs import ObsError
from test_director_cold_renderers import ColdRenderer
from director_mcp import AgentAPI

class OperatorSetup(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT,prefix='.director-test-')
        self.addCleanup(self.tmp.cleanup)
        self.d=Director(data_dir=self.tmp.name)
        self.addCleanup(self.d.close)
        self.sim=SimulatedOBS().__enter__();self.addCleanup(self.sim.__exit__)
        self.server=make_server(0,director=self.d)
        self.thread=threading.Thread(target=self.server.serve_forever);self.thread.start()
        self.addCleanup(self.stop)
    def stop(self):self.server.shutdown();self.server.server_close();self.thread.join(timeout=3)
    def http(self,command=None,expected=None):
        root=f'http://127.0.0.1:{self.server.server_port}'
        data=None if command is None else json.dumps({'command':command,'expected':self.d.version if expected is None else expected}).encode()
        request=urllib.request.Request(root+'/api/operator-setup',data=data,headers={'Content-Type':'application/json','Origin':root})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=12) as response:return json.load(response)
    def connect(self):return self.http({'action':'connect','port':self.sim.port,'password':self.sim.password})
    def test_projection_separates_credentials_inbox_and_model_authority(self):
        state=self.http();self.assertFalse(state['obs_connected'])
        result=self.connect();self.assertTrue(result['obs_connected'])
        self.assertEqual({x['name'] for x in result['inputs']},{'Camera','Content'})
        self.d.execute({'action':'audience','enabled':True},self.d.version)
        from test_director_queue import adapter,envelope
        receiver=adapter(self.d.enqueue_request)
        self.assertEqual(receiver.feed(envelope('NATIVE_SETUP_VIEWER_PRIVATE','setup-inbox'))['result'],'queued')
        self.assertEqual(len(self.d.participation_state()['requests']),1)
        result=self.http()
        self.assertNotIn('NATIVE_SETUP_VIEWER_PRIVATE',json.dumps(result))
        for value in (result,self.d.agent_state(),self.d.state()['events']):
            encoded=json.dumps(value)
            self.assertNotIn(self.sim.password,encoded);self.assertNotIn('requests',value)
        with self.assertRaises(ValueError):AgentAPI().request('/api/operator-setup')
        with self.assertRaises(ValueError):self.d.execute_agent({'action':'arm','enabled':True},self.d.version)
    def test_real_bank_ack_enables_native_review_without_web_controller(self):
        self.connect();self.http({'action':'setup','fixtures':True})
        with ColdRenderer(self.d,self.sim):self.http({'action':'arm','enabled':True})
        self.d.execute({'action':'preview','target':'obs'},self.d.version)
        bank=self.d.native.prepared['bank'];value=self.d.render('bank-'+bank)
        self.d.bank_ack(bank,value['id'],value['serial'],'obs')
        state=self.d.agent_state();self.assertTrue(state['rendered_ready'])
        self.assertFalse(state['agent_take_approved'])
        with self.assertRaises(ValueError):self.d.execute_agent({'action':'take'},self.d.version)
        old=self.sim.program
        self.d.operator_review(state['native_review'],state['version'],'take')
        self.assertNotEqual(self.sim.program,old)

    def test_setup_catalog_validation_stale_version_and_agent_separation(self):
        before=self.d.version
        with self.assertRaises(urllib.error.HTTPError) as error:self.http({'action':'setup'},expected=before-1)
        self.assertEqual(error.exception.code,409);self.assertEqual(self.d.version,before)
        result=self.http({'action':'material_select','id':'twitch-story'})
        self.assertEqual(result['selected_material']['id'],'twitch-story')
        self.http({'action':'page_register','id':'public-demo','name':'Public demo','url':'https://example.com/demo'})
        result=self.http({'action':'page_select','id':'public-demo'})
        self.assertEqual(result['selected_page']['id'],'public-demo')
        self.assertFalse(self.sim.requests)
        with self.assertRaises(urllib.error.HTTPError):self.http({'action':'page_register','id':'bad','name':'Bad','url':'https://example.com/?token=secret'})
        with self.assertRaises(urllib.error.HTTPError):self.http({'action':'SetCurrentProgramScene','sceneName':'anything'})
        self.assertEqual(self.d.pages.entries['public-demo']['url'],'https://example.com/demo')
        self.assertNotIn('url',self.d.agent_state()['page_catalog'][0])

    def test_failed_connection_sanitizes_provider_error_and_public_events(self):
        def refuse(*args,**kwargs):raise ObsError(self.sim.password)
        self.d.obs_factory=refuse
        with self.assertRaises(urllib.error.HTTPError) as error:self.connect()
        self.assertNotIn(self.sim.password,error.exception.read().decode())
        self.assertNotIn(self.sim.password,json.dumps(self.d.state()))
        self.assertFalse(self.d.armed)

    def test_native_arm_can_be_cancelled_through_same_operator_boundary(self):
        self.connect();self.http({'action':'setup','fixtures':True})
        errors=[]
        def arm():
            try:self.http({'action':'arm','enabled':True})
            except urllib.error.HTTPError as error:errors.append(error.code)
        worker=threading.Thread(target=arm);worker.start()
        deadline=time.monotonic()+3
        while time.monotonic()<deadline and not self.d._arm_token:time.sleep(.01)
        pending=self.http();self.assertTrue(pending['preparing'])
        result=self.http({'action':'arm','enabled':False},expected=pending['version'])
        effects=len(self.sim.requests)
        worker.join(timeout=3)
        self.assertFalse(worker.is_alive());self.assertFalse(result['armed']);self.assertFalse(result['preparing'])
        self.assertEqual(errors,[400])
        self.assertFalse(any(r.startswith(('Create','Set','Remove')) for r in self.sim.requests[effects:]))
        self.assertTrue(self.http()['obs_connected'])

    def test_wrong_collection_readback_does_not_grant_setup_or_repeat_revision_churn(self):
        self.connect();self.sim.collection='Unowned collection'
        first=self.http();second=self.http()
        self.assertFalse(first['inputs_ready']);self.assertFalse(first['armed'])
        self.assertEqual(first['version'],second['version'])
        self.assertFalse(any(r.startswith(('Create','Set','Remove')) for r in self.sim.requests))

    def test_wrong_origin_cannot_use_operator_setup(self):
        root=f'http://127.0.0.1:{self.server.server_port}'
        request=urllib.request.Request(root+'/api/operator-setup',data=json.dumps({'expected':self.d.version,'command':{'action':'connect','port':self.sim.port,'password':self.sim.password}}).encode(),headers={'Content-Type':'application/json','Origin':'http://unowned.invalid'})
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=2)
        self.assertEqual(error.exception.code,403)
        self.assertFalse(self.sim.requests);self.assertFalse(self.d.armed)

if __name__=='__main__':unittest.main()
