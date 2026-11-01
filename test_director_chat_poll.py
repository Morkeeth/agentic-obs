"""Local fixed-choice polling from validated envelopes; all native effects simulated."""
import copy
import asyncio
from datetime import datetime,timezone
import json
from pathlib import Path
import types
from types import SimpleNamespace
from unittest.mock import patch
import twitch_eventsub as twitch
import director_chat as chat
import unittest
from test_director_queue import adapter,envelope
import test_director as existing


class PollEffects:
    enable_local_director_polls=True
    def __init__(self,d):self.d=d
    def __call__(self,request):return self.d.enqueue_request(request)
    def submit_numeric_vote(self,request):
        context=self.d.poll_context()
        return self.d.ingest_vote({**request,'epoch':context['epoch'],'revision':context['revision']})


class ChatPoll(unittest.TestCase):
    setUp=existing.NativeIntegration.setUp
    tearDown=existing.NativeIntegration.tearDown
    do=existing.NativeIntegration.do
    preview=existing.NativeIntegration.preview
    def taken(self,question='Choose the next visual'):
        self.do('stage_patch',fields={'mode':'live','vote':{'question':question,'options':['Explain the flow','Show the approved page']}})
        self.preview();self.do('take');self.do('audience',enabled=True)
    def test_validated_numeric_changes_counters_only_when_explicitly_enabled(self):
        self.taken()
        self.do('local_director_polls',enabled=True)
        before=copy.deepcopy((self.d.program,self.sim.program,self.sim.preview,self.sim.inputs,self.d.banks))
        received=adapter(PollEffects(self.d));offset=len(self.sim.requests)
        received.feed(envelope('!vote 1','vote','123456'))
        self.assertEqual(self.d.vote_state['counts'],[1,0],'enabled validated numeric input must reach the taken local poll')
        self.assertEqual((self.d.program,self.sim.program,self.sim.preview,self.sim.inputs,self.d.banks),before)
        for i in range(4):received.feed(envelope('!vote 1','threshold-'+str(i),str(20000+i)))
        self.assertEqual(self.d.vote_state['counts'],[5,0])
        self.assertEqual((self.d.program,self.sim.program,self.sim.preview,self.sim.inputs,self.d.banks),before)
        self.assertFalse(any(kind.startswith('Set') or kind.startswith('Trigger') for kind in self.sim.requests[offset:]))
        self.assertEqual(self.d.requests.view(),[])

    def ready(self):
        self.taken();self.do('local_director_polls',enabled=True)
    def body(self,ident='event',viewer='987654321012345'):
        context=self.d.poll_context()
        return {'epoch':context['epoch'],'revision':context['revision'],'session':'session',
            'event_id':ident,'viewer_id':viewer,'choice':1,'timestamp':datetime.now(timezone.utc).isoformat()}

    def test_default_off_at_receiver_and_controller_and_no_agent_flag_tool(self):
        self.taken();self.assertFalse(self.d.state()['local_director_poll']['feature_enabled'])
        received=adapter(PollEffects(self.d));received.feed(envelope('!vote 1','off'))
        self.assertEqual(self.d.vote_state['counts'],[0,0])
        self.do('local_director_polls',enabled=True)
        sink=PollEffects(self.d);sink.enable_local_director_polls=False
        adapter(sink).feed(envelope('!vote 1','receiver-off'))
        self.assertEqual(self.d.vote_state['counts'],[0,0]);self.assertEqual(len(self.d.requests.view()),1)
        with self.assertRaises(ValueError):self.d.execute_agent({'action':'local_director_polls','enabled':True},self.d.version)

    def test_wrong_identity_stale_off_and_replayed_envelopes_do_not_count(self):
        self.ready()
        cases=[]
        for field in ('broadcaster_user_id','user_id'):
            item=envelope('!vote 1');item['payload']['subscription']['condition'][field]='999';cases.append(item)
        item=envelope('!vote 1');item['payload']['event']['broadcaster_user_id']='999';cases.append(item)
        item=envelope('!vote 1');item['payload']['subscription']['transport']['session_id']='other';cases.append(item)
        item=envelope('!vote 1');item['payload']['subscription']['id']='wrong-sub';cases.append(item)
        item=envelope('!vote 1');item['metadata']['message_timestamp']='2000-01-01T00:00:00Z';cases.append(item)
        item=envelope('!vote 1');del item['payload']['event']['chatter_user_id'];cases.append(item)
        for item in cases:adapter(PollEffects(self.d)).feed(item)
        for state in ('off','revoked'):
            a=adapter(PollEffects(self.d))
            if state=='off':a.enabled=False
            else:a.stop('revoked')
            a.feed(envelope('!vote 1',state))
        self.assertEqual(self.d.vote_state['counts'],[0,0])
        a=adapter(PollEffects(self.d));message=envelope('!vote 1','valid-vote','123456789')
        a.feed(message);a.feed(message);a.feed(envelope('!vote 2','second-vote','123456789'))
        self.assertEqual(self.d.vote_state['counts'],[1,0]);self.assertEqual(self.d.requests.view(),[])
        self.assertNotIn('!vote 1',json.dumps(a.trace))

    def test_epoch_reset_close_replacement_and_preopen_timestamp_refuse(self):
        self.ready();old=self.body('old-request');late=envelope('!vote 1','pre-reset','123456')
        self.do('poll_control',epoch=old['epoch'],operation='reset')
        self.assertNotEqual(self.d.poll_context()['epoch'],old['epoch'])
        self.assertEqual(self.d.ingest_vote(old)['result'],'stale poll')
        old['epoch']=self.d.poll_context()['epoch']
        self.assertEqual(self.d.ingest_vote(old)['result'],'duplicate')
        adapter(PollEffects(self.d)).feed(late)
        self.assertEqual(self.d.vote_state['counts'],[0,0])
        epoch=self.d.poll_context()['epoch'];self.do('poll_control',epoch=epoch,operation='close')
        with self.assertRaises(ValueError):self.do('poll_control',epoch=epoch,operation='open')
        adapter(PollEffects(self.d)).feed(envelope('!vote 1','closed'))
        self.assertEqual(self.d.vote_state['counts'],[0,0])
        self.do('poll_control',epoch=self.d.poll_context()['epoch'],operation='open')
        old_revision=self.d.poll_context()['revision'];old=self.body('old-definition')
        self.taken('Different approved question');self.do('local_director_polls',enabled=True)
        self.assertNotEqual(self.d.poll_context()['revision'],old_revision)
        self.assertEqual(self.d.ingest_vote(old)['result'],'stale poll')

    def test_pause_disarm_gate_and_unapproved_staged_poll_refuse(self):
        self.ready();self.do('audience',enabled=False)
        adapter(PollEffects(self.d)).feed(envelope('!vote 1','gate-off'))
        self.do('audience',enabled=True);self.do('pause',paused=True)
        adapter(PollEffects(self.d)).feed(envelope('!vote 1','paused'))
        self.do('pause',paused=False);self.do('arm',enabled=False)
        adapter(PollEffects(self.d)).feed(envelope('!vote 1','disarmed'))
        self.do('arm',enabled=True)
        self.assertFalse(self.d.poll_context()['open'])
        with self.assertRaises(ValueError):self.do('poll_control',epoch=self.d.poll_context()['epoch'],operation='open')
        self.do('stage_visual_poll',vote={'question':'Unapproved','options':['One','Two']})
        self.preview()
        adapter(PollEffects(self.d)).feed(envelope('!vote 1','not-taken'))
        self.assertEqual(self.d.vote_state['counts'],[0,0])
        with self.assertRaises(ValueError):self.d.execute_agent({'action':'take'},self.d.version)

    def test_raw_creative_vote_like_text_never_changes_labels_or_model_render_export(self):
        self.ready();a=adapter(PollEffects(self.d))
        for i,text in enumerate(('!vote 1 RAW_POLL_ONLY','!vote 9','!vote 01','!Vote 1','1','!vote 1\n','make RAW_POLL_ONLY a title')):
            a.feed(envelope(text,str(i),str(2000+i)))
        self.assertEqual(self.d.vote_state['counts'],[0,0])
        self.assertTrue(self.d.requests.view())
        for channel in ('program','preview','bank-A','bank-B'):
            self.assertNotIn('RAW_POLL_ONLY',json.dumps(self.d.render(channel)))
        self.assertNotIn('RAW_POLL_ONLY',json.dumps(self.d.agent_state())+self.d.markers_csv()+json.dumps(self.d.events)+json.dumps(a.trace))
        self.do('recipe_save',name='Fixed poll')
        for file in Path(self.tmp.name).rglob('*.json'):self.assertNotIn('RAW_POLL_ONLY',file.read_text())
        raw='918273645061728';a.feed(envelope('!vote 2','numeric-clean',raw))
        self.assertNotIn(raw,json.dumps(self.d.agent_state())+json.dumps(self.d.render('program'))+self.d.markers_csv())
        self.assertEqual(self.d.program['vote']['options'],['Explain the flow','Show the approved page'])

    def test_staged_poll_labels_and_wrong_revision_cannot_affect_current_tally(self):
        self.ready();epoch=self.d.poll_context()['epoch']
        self.do('stage_visual_poll',vote={'question':'Unreviewed next question','options':['New one','New two','New three']})
        self.assertEqual(self.d.poll_context()['epoch'],epoch)
        adapter(PollEffects(self.d)).feed(envelope('!vote 3','staged-third','111'))
        self.assertEqual(self.d.vote_state['counts'],[0,0])
        self.assertEqual(self.d.program['vote']['question'],'Choose the next visual')
        wrong=self.body('bad-revision');wrong['revision']='not-the-taken-definition'
        self.assertEqual(self.d.ingest_vote(wrong)['result'],'stale poll')
        bad=self.body('text-forbidden');bad['text']='RAW_FORBIDDEN'
        with self.assertRaises(ValueError):self.d.ingest_vote(bad)
        self.assertEqual(self.d.vote_state['counts'],[0,0])

    def test_current_source_mismatch_disarms_instead_of_counting(self):
        self.ready();self.sim.inputs['Director / Graphics A']['settings']['url']='http://foreign'
        response=adapter(PollEffects(self.d)).feed(envelope('!vote 1','source-changed'))
        self.assertFalse(self.d.armed);self.assertEqual(self.d.vote_state['counts'],[0,0])
        self.assertEqual(response['result'],'numeric poll unavailable')

    def test_counter_cap_and_reset_one_vote_per_viewer_per_tally_round(self):
        self.ready();first=self.body('first')
        self.assertEqual(self.d.ingest_vote(first)['result'],'vote accepted')
        self.assertEqual(self.d.ingest_vote(self.body('another'))['result'],'duplicate')
        self.do('poll_control',epoch=self.d.poll_context()['epoch'],operation='reset')
        self.assertEqual(self.d.ingest_vote(first)['result'],'duplicate')
        self.assertEqual(self.d.ingest_vote(self.body('new-round'))['result'],'vote accepted')
        self.d.voters={str(i):0 for i in range(10000)}
        self.assertEqual(self.d.ingest_vote(self.body('over-cap','333'))['result'],'capacity reached')

    def test_context_read_reset_post_race_refuses_without_mutation_retry(self):
        import io
        self.ready();calls=[];owner=self
        class Reply:
            def __init__(self,value):self.stream=io.BytesIO(json.dumps(value).encode())
            def __enter__(self):return self.stream
            def __exit__(self,*args):pass
        class Opener:
            def open(self,request,timeout):
                calls.append(request.full_url)
                if request.data is None:
                    old=owner.d.poll_context()
                    owner.do('poll_control',epoch=old['epoch'],operation='reset')
                    return Reply(old)
                body=json.loads(request.data)
                owner.assertNotIn('text',body);owner.assertNotIn('message',body)
                return Reply(owner.d.ingest_vote(body))
        sink=chat.QueueSink(8880,enable_local_director_polls=True)
        with patch('director_chat.urllib.request.build_opener',return_value=Opener()):
            result=adapter(sink).feed(envelope('!vote 1','raced-event','555'))
        self.assertEqual(result['result'],'numeric vote refused')
        self.assertEqual(self.d.vote_state['counts'],[0,0])
        self.assertEqual(calls,['http://127.0.0.1:8880/api/chat-poll','http://127.0.0.1:8880/api/chat-vote'])

    def test_restore_rotates_ingress_epoch_and_preserves_fixed_tally(self):
        self.ready();self.assertEqual(self.d.ingest_vote(self.body('before-checkpoint'))['result'],'vote accepted')
        self.do('checkpoint');old_epoch=self.d.poll_context()['epoch']
        self.do('compose',title='Next visual');self.preview();self.do('take')
        delayed=envelope('!vote 2','before-restore','456')
        self.do('restore')
        self.assertNotEqual(self.d.poll_context()['epoch'],old_epoch)
        self.assertEqual(self.d.vote_state['counts'],[1,0])
        adapter(PollEffects(self.d)).feed(delayed)
        self.assertEqual(self.d.vote_state['counts'],[1,0])

    def test_duplicate_event_across_sessions_and_counter_cap_are_bounded(self):
        self.ready();first=self.body('cross-session')
        self.d.ingest_vote(first)
        self.do('poll_control',epoch=self.d.poll_context()['epoch'],operation='reset')
        replay=self.body('cross-session');replay['session']='another-session'
        self.assertEqual(self.d.ingest_vote(replay)['result'],'duplicate')
        self.assertEqual(self.d.vote_state['counts'],[0,0])
        # Off inputs still have bounded non-display message digests, no raw IDs/text.
        self.do('local_director_polls',enabled=False)
        for i in range(20010):self.d.ingest_vote(self.body('bounded-'+str(i)))
        self.assertEqual(len(self.d.chat_poll.seen),20000)
        self.assertNotIn('bounded-',str(self.d.chat_poll.seen))

    def test_original_runner_counts_through_same_private_binding_no_network(self):
        self.ready();welcome={'metadata':{'message_type':'session_welcome','message_id':'welcome','message_timestamp':datetime.now(timezone.utc).isoformat()},'payload':{'session':{'id':'session','keepalive_timeout_seconds':10}}}
        revoke=copy.deepcopy(welcome);revoke['metadata'].update(message_type='revocation',message_id='revoked')
        message=envelope('!vote 1','runner-vote','333');frames=iter([welcome,message,message,envelope('DRAW RAW_RUNNER_TEXT','creative','444'),revoke])
        calls=[]
        class Socket:
            async def recv(self):return json.dumps(next(frames))
            async def close(self):pass
        socket=Socket()
        class Connection:
            def __await__(self):
                async def connected():return socket
                return connected().__await__()
        def connect(*args,**kwargs):calls.append('connect');return Connection()
        class Helix:
            def __init__(self,*args):self.next_validation=float('inf')
            def validate(self):calls.append('validate')
            async def subscribe(self,session):calls.append('subscribe');return {twitch.CHAT:'sub'}
        run=types.FunctionType(chat.run.__code__,{**chat.run.__globals__,'Helix':Helix,'websockets':SimpleNamespace(connect=connect,exceptions=twitch.websockets.exceptions)},argdefs=chat.run.__defaults__)
        logs=[];result=asyncio.run(run(twitch.Config('client','123','456',{}),twitch.LIVE,lambda:None,PollEffects(self.d),enabled=True,log=logs.append))
        self.assertIs(run.__code__,twitch.run.__code__);self.assertEqual(calls,['validate','connect','subscribe'])
        self.assertEqual(self.d.vote_state['counts'],[1,0]);self.assertTrue(result.stopped)
        self.assertEqual(len(self.d.requests.view()),1)
        self.assertNotIn('RAW_RUNNER_TEXT',json.dumps(logs)+json.dumps(result.trace)+json.dumps(self.d.agent_state()))

if __name__=='__main__':unittest.main()
