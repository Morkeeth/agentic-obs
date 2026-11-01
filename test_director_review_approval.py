"""Explicit operator approval; simulated OBS/renderer, never human pixel proof."""
import copy
import unittest
import threading
from director import Conflict
import test_director_banks as banks

class ReviewApproval(unittest.TestCase):
    setUp=banks.BankContract.setUp
    tearDown=banks.BankContract.tearDown
    do=banks.BankContract.do
    ack=banks.BankContract.ack
    def prepare(self):
        self.do('compose',title='Arbitrary authored composition')
        self.do('preview',target='obs');self.ack()
    def agent_take(self):return self.d.execute_agent({'action':'take'},self.d.version)

    def test_rendered_acknowledgments_do_not_approve_agent_take(self):
        self.prepare();before=self.sim.program
        with self.assertRaisesRegex(ValueError,'operator approval'):self.agent_take()
        self.assertEqual(self.sim.program,before)
        self.assertFalse(self.d.agent_state()['agent_take_approved'])

    def test_explicit_operator_approval_allows_one_agent_take(self):
        self.prepare();self.do('approve_agent_take')
        self.assertTrue(self.d.agent_state()['agent_take_approved'])
        self.agent_take()
        self.assertFalse(self.d.agent_state()['agent_take_approved'])
        with self.assertRaises(ValueError):self.agent_take()

    def test_operator_take_remains_one_step_without_prior_approval(self):
        self.prepare();before=self.sim.program
        self.do('take');self.assertNotEqual(self.sim.program,before)

    def test_agent_cannot_approve_and_approval_requires_rendered_revision(self):
        with self.assertRaises(ValueError):self.do('approve_agent_take')
        self.prepare()
        with self.assertRaises(ValueError):
            self.d.execute_agent({'action':'approve_agent_take'},self.d.version)

    def test_changes_cannot_inherit_approval(self):
        for action,kw in [('compose',{'title':'Revised'}),('preview',{'target':'obs'}),
                          ('destination',{'target':'overlay'}),('arm',{'enabled':True}),
                          ('disconnect',{}),('stage_patch',{'fields':{'layout':'camera'}})]:
            with self.subTest(action=action):
                if not self.d.obs_state['connected']:
                    self.do('connect',password=self.sim.password,port=self.sim.port)
                    self.do('arm',enabled=True)
                self.do('destination',target='obs');self.prepare();self.do('approve_agent_take')
                self.do(action,**kw)
                self.assertFalse(self.d.agent_state()['agent_take_approved'])
                with self.assertRaises(ValueError):self.agent_take()

    def test_clear_and_restore_do_not_inherit_approval(self):
        stop=threading.Event()
        def renderer():
            while not stop.wait(.01):
                for bank in ('A','B'):
                    value=self.d.render('bank-'+bank)
                    try:self.d.bank_ack(bank,value['id'],value['serial'],'obs')
                    except Conflict:pass
        worker=threading.Thread(target=renderer);worker.start()
        try:
            self.prepare();self.do('approve_agent_take');self.do('clear')
            self.assertFalse(self.d.agent_state()['agent_take_approved'])
            self.prepare();self.do('approve_agent_take');self.do('restore')
            self.assertFalse(self.d.agent_state()['agent_take_approved'])
        finally:stop.set();worker.join(2)

    def test_exact_payload_and_prepared_target_binding(self):
        self.prepare();self.do('approve_agent_take')
        saved=copy.deepcopy(self.d.native.prepared)
        self.d.native.prepared['target']='Director / Ending A'
        self.assertFalse(self.d.agent_state()['agent_take_approved'])
        self.d.native.prepared=saved
        bank=saved['bank'];self.d.banks[bank]['id']+=100
        self.assertFalse(self.d.agent_state()['agent_take_approved'])
        with self.assertRaises(ValueError):self.agent_take()

if __name__=='__main__':unittest.main()
