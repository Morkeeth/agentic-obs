"""Headless real Director readiness logic; simulated OBS, no native launch."""
import json
import threading
import urllib.request
import urllib.error
from director_server import make_server
import unittest
from unittest.mock import patch
import test_director_banks as banks

class RendererExpiry(unittest.TestCase):
    setUp=banks.BankContract.setUp
    tearDown=banks.BankContract.tearDown
    do=banks.BankContract.do

    def prepare(self, instance=None):
        self.do('compose',title='Own synthetic expiry fixture')
        self.do('preview',target='obs')
        bank=self.d.native.prepared['bank']; payload=self.d.render('bank-'+bank)
        kw={} if instance is None else {'renderer_instance':instance}
        self.d.bank_ack(bank,payload['id'],payload['serial'],'obs',**kw)
        state=self.d.agent_state()
        self.d.operator_review(state['native_review'],state['version'],'approve')
        self.assertTrue(self.d.agent_state()['agent_take_approved'])
        return bank,payload

    def check_held(self, before):
        state=self.d.agent_state()
        self.assertFalse(state['rendered_ready'])
        self.assertFalse(state['agent_take_approved'])
        self.assertIsNone(state['native_review'])
        with self.assertRaises(ValueError):self.d.execute_agent({'action':'take'},self.d.version)
        self.assertEqual(self.sim.program,before)

    def test_expiry_is_cleared_and_late_ack_cannot_resurrect_review(self):
        bank,p=self.prepare();before=self.sim.program
        now=self.d.bank_ready[bank]['received']
        with patch('director.time.monotonic',return_value=now+3):
            self.check_held(before)
            self.assertIsNone(self.d.bank_ready[bank], 'Expired bank must be cleared, not only masked')
            self.d.bank_ack(bank,p['id'],p['serial'],'obs')
            self.check_held(before)
        self.check_held(before)
        self.do('preview',target='obs');p=self.d.render('bank-'+bank)
        self.d.bank_ack(bank,p['id'],p['serial'],'obs')
        self.assertTrue(self.d.agent_state()['rendered_ready'])
        self.assertFalse(self.d.agent_state()['agent_take_approved'])

    def test_late_heartbeat_detects_gap_even_without_state_poll(self):
        bank,p=self.prepare();before=self.sim.program
        now=self.d.bank_ready[bank]['received']
        with patch('director.time.monotonic',return_value=now+3):
            self.d.bank_ack(bank,p['id'],p['serial'],'obs')
            self.check_held(before)

    def test_new_document_instance_invalidates_even_inside_ttl(self):
        bank,p=self.prepare('a'*32);before=self.sim.program
        self.d.bank_ack(bank,p['id'],p['serial'],'obs',renderer_instance='b'*32)
        self.check_held(before)
        self.d.bank_ack(bank,p['id'],p['serial'],'obs',renderer_instance='b'*32)
        self.check_held(before)
        self.do('preview',target='obs');p=self.d.render('bank-'+bank)
        self.d.bank_ack(bank,p['id'],p['serial'],'obs',renderer_instance='c'*32)
        self.assertTrue(self.d.agent_state()['rendered_ready'])
        self.assertFalse(self.d.agent_state()['agent_take_approved'])

    def test_expired_bank_can_be_rearmed_only_with_explicit_warm_challenge(self):
        bank,p=self.prepare()
        self.d.bank_ready[bank]['received']-=3
        self.assertFalse(self.d._bank_is_ready(bank))
        self.do('arm',enabled=True)
        self.assertTrue(all(self.d.agent_state()['bank_readiness'].values()))
        self.assertFalse(self.d.agent_state()['agent_take_approved'])
        self.assertIsNone(self.d.agent_state()['native_review'])

    def test_http_route_requires_document_identity_and_expires_real_ack(self):
        bank,p=self.prepare()
        server=make_server(0,director=self.d)
        worker=threading.Thread(target=server.serve_forever);worker.start()
        origin=f'http://127.0.0.1:{server.server_port}'
        def post(data):
            request=urllib.request.Request(origin+'/api/rendered',data=json.dumps(data).encode(),headers={'Content-Type':'application/json','Origin':origin})
            try:
                with urllib.request.urlopen(request,timeout=2) as response:return response.status,json.load(response)
            except urllib.error.HTTPError as error:return error.code,json.load(error)
        body={'bank':bank,'id':p['id'],'serial':p['serial'],'renderer':'obs'}
        try:
            self.assertEqual(post(body)[0],400)
            self.assertEqual(post({**body,'renderer_instance':None})[0],400)
            self.assertEqual(post({**body,'renderer_instance':'bad'})[0],400)
            self.assertEqual(post({**body,'renderer_instance':'a'*32})[1]['rendered'],bank)
            now=self.d.bank_ready[bank]['received']
            with patch('director.time.monotonic',return_value=now+3):
                self.assertTrue(post({**body,'renderer_instance':'a'*32})[1]['preview_required'])
                self.check_held(self.sim.program)
        finally:server.shutdown();server.server_close();worker.join(3)

    def test_same_document_hot_heartbeats_preserve_exact_approval(self):
        bank,p=self.prepare('a'*32)
        for _ in range(3):self.d.bank_ack(bank,p['id'],p['serial'],'obs',renderer_instance='a'*32)
        self.assertTrue(self.d.agent_state()['agent_take_approved'])
        with self.assertRaises(ValueError):self.d.bank_ack(bank,p['id'],p['serial'],'obs',renderer_instance='bad')

if __name__=='__main__':unittest.main()
