"""Native review boundary against simulated owned OBS; no real pixels/devices."""
import copy
import unittest
from director import Conflict
from test_director_review_approval import ReviewApproval

class NativePanelReview(ReviewApproval):
    def test_native_review_requires_exact_rendered_identity(self):
        self.prepare()
        state=self.d.agent_state()
        self.assertIsNotNone(state.get('native_review'))
        old=copy.deepcopy(state['native_review'])
        self.do('preview',target='obs');self.ack()
        before=self.sim.program
        with self.assertRaises(Conflict):
            self.d.operator_review(old,self.d.version,'take')
        self.assertEqual(before,self.sim.program)
        state=self.d.agent_state()
        result=self.d.operator_review(state['native_review'],state['version'],'approve')
        self.assertTrue(result['agent_take_approved'])
        with self.assertRaises(Conflict):self.d.operator_review(state['native_review'],state['version'],'take')

    def test_waiting_validated_chat_does_not_invalidate_exact_native_review(self):
        from test_director_queue import adapter,envelope
        self.do('audience',enabled=True);self.prepare()
        reviewed=copy.deepcopy(self.d.agent_state())
        before=copy.deepcopy((self.sim.program,self.d.banks))
        receiver=adapter(self.d.enqueue_request)
        for i in range(5):
            result=receiver.feed(envelope('waiting-only-'+str(i),'waiting-'+str(i),str(9000+i)))
            self.assertEqual(result['result'],'queued')
        self.assertEqual(len(self.d.participation_state()['requests']),5)
        self.assertEqual(self.d.agent_state()['native_review'],reviewed['native_review'])
        self.assertEqual((self.sim.program,self.d.banks),before)
        result=self.d.operator_review(reviewed['native_review'],reviewed['version'],'take')
        self.assertNotEqual(self.sim.program,before[0])
        self.assertEqual(result['version'],reviewed['version']+1)

    def test_waiting_chat_does_not_starve_draft_but_show_change_invalidates_review(self):
        from test_director_queue import adapter,envelope
        self.do('audience',enabled=True);self.prepare();reviewed=self.d.agent_state()
        receiver=adapter(self.d.enqueue_request)
        receiver.feed(envelope('inert queue','inert','9010'))
        result=self.d.execute_agent({'action':'stage_patch','fields':{'layout':'camera'}},reviewed['version'])
        self.assertGreater(result['version'],reviewed['version'])
        with self.assertRaises(Conflict):self.d.operator_review(reviewed['native_review'],reviewed['version'],'take')

    def test_native_take_is_one_deliberate_exact_review_action(self):
        self.prepare();state=self.d.agent_state()
        before=self.sim.program
        result=self.d.operator_review(state['native_review'],state['version'],'take')
        self.assertNotEqual(before,self.sim.program)
        self.assertFalse(result['agent_take_approved'])
        with self.assertRaises(ValueError):
            self.d.execute_agent({'action':'operator_review'},result['version'])

if __name__=='__main__':unittest.main()
