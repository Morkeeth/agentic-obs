"""Real controller/RPC path, simulated renderer effects only; no OBS/CEF launch."""
import copy
import tempfile
import unittest
from unittest.mock import patch
from director import Director, ROOT
from director_obs import OVERLAYS, ObsError
from director_simulator import SimulatedOBS
from test_director_cold_renderers import ColdRenderer

class DeadRendererOBS(SimulatedOBS):
    def __init__(self):
        super().__init__();self.dead=set();self.document={'A':'a'*32,'B':'b'*32};self.reloads=[]
    def rpc(self,kind,data):
        if kind=='PressInputPropertiesButton':
            bank=next((b for b,n in OVERLAYS.items() if n==data.get('inputName')),None)
            if bank is None or data.get('propertyName')!='refreshnocache':raise ValueError('Wrong fixture refresh')
            self.reloads.append(copy.deepcopy(data));self.dead.discard(bank)
            self.document[bank]=('c' if bank=='A' else 'd')*32
            return {}  # RPC success does not pretend any frame has painted.
        return super().rpc(kind,data)

class DeadRendererRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT,prefix='.director-test-')
        self.sim=DeadRendererOBS().__enter__();self.d=Director(data_dir=self.tmp.name)
        self.do('connect',password=self.sim.password,port=self.sim.port)
        self.do('setup',fixtures=True)
        with ColdRenderer(self.d,self.sim):self.do('arm',enabled=True)
    def tearDown(self):self.d.close();self.sim.__exit__();self.tmp.cleanup()
    def do(self,action,**kw):return self.d.execute({'action':action,**kw},self.d.version)
    def paint(self,bank,instance=None):
        if bank in self.sim.dead:return None
        p=self.d.render('bank-'+bank)
        return self.d.bank_ack(bank,p['id'],p['serial'],'obs',renderer_instance=instance or self.sim.document[bank])
    def prepare_A_and_kill(self):
        self.do('compose',title='Own synthetic program B')
        self.do('preview',target='obs');self.paint('B');self.do('take')
        self.do('compose',title='Own synthetic pending A');self.do('preview',target='obs');self.paint('A')
        state=self.d.agent_state();self.d.operator_review(state['native_review'],state['version'],'approve')
        old=self.d.render('bank-A');self.sim.dead.add('A')
        self.d.bank_ready['A']['received']-=3
        state=self.d.agent_state();self.assertFalse(state['rendered_ready']);self.assertFalse(state['agent_take_approved'])
        self.assertIn('A',self.sim.dead,'Read-only expiry observation cannot reload a source')
        self.assertFalse(self.sim.reloads)
        return old
    def test_explicit_repreview_reloads_dead_A_and_requires_fresh_painted_ACK(self):
        old=self.prepare_A_and_kill();program=self.sim.program;on_air=copy.deepcopy(self.d.render('bank-B'))
        self.do('preview',target='obs')
        self.assertNotIn('A',self.sim.dead,'Re-preview must explicitly reload the dead browser renderer')
        self.assertEqual(self.sim.reloads,[{'inputName':OVERLAYS['A'],'propertyName':'refreshnocache'}])
        self.assertFalse(self.d.agent_state()['rendered_ready'],'RPC success is not a renderer ACK')
        fresh=self.d.render('bank-A');self.assertNotEqual(fresh['id'],old['id'])
        with self.assertRaises(ValueError):self.d.bank_ack('A',old['id'],old['serial'],'obs',renderer_instance='c'*32)
        self.assertTrue(self.d.bank_ack('A',fresh['id'],fresh['serial'],'obs',renderer_instance='a'*32)['stale'],'Old document cannot authorize reloaded preview')
        self.assertFalse(self.d.agent_state()['rendered_ready'])
        self.assertEqual(self.paint('A')['rendered'],'A')
        state=self.d.agent_state();self.assertTrue(state['rendered_ready']);self.assertFalse(state['agent_take_approved'])
        self.assertEqual(state['native_review']['renderer_instance'],'c'*32)
        with self.assertRaises(ValueError):self.d.execute_agent({'action':'take'},self.d.version)
        self.assertEqual(self.sim.program,program)
        after=self.d.render('bank-B');self.assertEqual({k:v for k,v in on_air.items() if k!='clock'},{k:v for k,v in after.items() if k!='clock'})
    def test_healthy_preview_never_refreshes_or_recreates_inputs(self):
        self.do('preview',target='obs');self.paint('B');offset=len(self.sim.requests)
        self.do('preview',target='obs');self.paint('B')
        self.assertFalse(self.sim.reloads)
        self.assertFalse(set(self.sim.requests[offset:]) & {'CreateInput','RemoveInput','PressInputPropertiesButton'})
    def test_refresh_refusal_disarms_without_retry_or_take(self):
        self.prepare_A_and_kill();program=self.sim.program;self.sim.refuse_on='PressInputPropertiesButton'
        with self.assertRaises(ObsError):self.do('preview',target='obs')
        self.assertFalse(self.d.armed);self.assertFalse(self.d.agent_state()['agent_take_approved'])
        self.assertFalse(self.sim.reloads);self.assertEqual(self.sim.program,program)
        self.assertEqual(self.sim.requests.count('PressInputPropertiesButton'),1)
    def test_raw_rpc_cannot_press_unowned_or_other_properties(self):
        offset=len(self.sim.requests)
        for data in [{'inputName':'Camera','propertyName':'refreshnocache'},
                     {'inputName':OVERLAYS['A'],'propertyName':'other'},
                     {'inputName':OVERLAYS['A'],'propertyName':'refreshnocache','extra':True}]:
            with self.assertRaises(ObsError):self.d.native.req('PressInputPropertiesButton',data)
        self.assertNotIn('PressInputPropertiesButton',self.sim.requests[offset:])

    def test_changed_program_or_graphics_identity_refuses_refresh(self):
        self.do('preview',target='obs');self.paint('B')
        self.sim.program=self.sim.preview
        with self.assertRaises(ObsError):self.d.native.reload_prepared_graphics('B')
        self.assertFalse(self.sim.reloads)
        self.sim.program='Director / Starting A'
        self.sim.inputs[OVERLAYS['B']]['settings']['url']='https://unowned.invalid/'
        with self.assertRaises(ObsError):self.d.native.reload_prepared_graphics('B')
        self.assertFalse(self.sim.reloads)

    def test_refresh_refuses_program_bank(self):
        self.do('preview',target='obs');self.paint('B')
        with self.assertRaises(ObsError):self.d.native.reload_prepared_graphics('A')
        self.assertFalse(self.sim.reloads)

if __name__=='__main__':unittest.main()
