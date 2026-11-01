"""Simulated protocol and explicit operator queue effects; no live Twitch/OBS/audio."""
import asyncio
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import twitch_eventsub as twitch
import director_chat as chat
from director_queue import RequestQueue
from director import Conflict
from director_obs import ObsError
import test_director as existing


def envelope(text='!overlay hydrate', ident='message', viewer='789'):
    return {'metadata':{'message_type':'notification','message_id':ident,
        'message_timestamp':datetime.now(timezone.utc).isoformat(),'subscription_type':twitch.CHAT,'subscription_version':'1'},
        'payload':{'subscription':{'id':'sub','type':twitch.CHAT,'version':'1','status':'enabled',
            'condition':{'broadcaster_user_id':'123','user_id':'456'},'transport':{'method':'websocket','session_id':'session'}},
            'event':{'broadcaster_user_id':'123','chatter_user_id':viewer,'message':{'text':text}}}}


def adapter(send):
    value=chat.QueueAdapter(twitch.Config('client','123','456',{}),twitch.LIVE,send)
    value.feed({'metadata':{'message_type':'session_welcome','message_id':'welcome','message_timestamp':datetime.now(timezone.utc).isoformat()},'payload':{'session':{'id':'session'}}})
    value.subscriptions={twitch.CHAT:'sub'};value.enabled=True
    return value


class ValidatedBoundary(unittest.TestCase):
    def test_original_validator_is_base_and_run_code_unchanged_private_binding(self):
        self.assertIs(chat.QueueAdapter.__bases__[0],twitch.Adapter)
        self.assertIs(chat.run.__code__,twitch.run.__code__)
        self.assertIs(twitch.run.__globals__['Adapter'],twitch.Adapter)
        self.assertIs(chat.run.__globals__['Adapter'],chat.QueueAdapter)
        original=twitch.Adapter.feed;called=[];received=[]
        def spy(self,value):called.append(value);return original(self,value)
        with patch.object(twitch.Adapter,'feed',spy):
            a=adapter(lambda req:received.append(req) or {'result':'queued'})
            self.assertEqual(a.feed(envelope('ordinary viewer request'))['result'],'queued')
        self.assertEqual(len(called),2);self.assertEqual(len(received),1)
        self.assertIsNone(received[0]['suggested'])

    def test_malformed_stale_wrong_identity_off_revoked_and_duplicate_cannot_enqueue(self):
        cases=[]
        for field,value in [('id','wrong'),('status','revoked'),('version','2')]:
            item=envelope();item['payload']['subscription'][field]=value;cases.append(item)
        for field,value in [('session_id','wrong'),('method','webhook')]:
            item=envelope();item['payload']['subscription']['transport'][field]=value;cases.append(item)
        for field in ('broadcaster_user_id','user_id'):
            item=envelope();item['payload']['subscription']['condition'][field]='999';cases.append(item)
        item=envelope();item['payload']['event']['broadcaster_user_id']='999';cases.append(item)
        item=envelope();item['metadata']['message_timestamp']=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat();cases.append(item)
        item=envelope();item['payload']['event']['chatter_user_id']='not-numeric';cases.append(item)
        item=envelope();del item['payload']['event']['chatter_user_id'];cases.append(item)
        item=envelope();item['payload']['event']['message']=None;cases.append(item)
        for item in cases:
            received=[];a=adapter(lambda req:received.append(req) or {'result':'queued'})
            a.feed(item);self.assertEqual(received,[],item['metadata']['message_id'])
        for state in ('off','revoked','no-subscription'):
            received=[];a=adapter(lambda req:received.append(req) or {'result':'queued'})
            if state=='off':a.enabled=False
            elif state=='revoked':a.stop('revoked')
            else:a.subscriptions={}
            a.feed(envelope('unknown raw text'));self.assertEqual(received,[])
        received=[];a=adapter(lambda req:received.append(req) or {'result':'queued'})
        item=envelope();a.feed(item);a.feed(item)
        self.assertEqual(len(received),1)
        self.assertNotIn('!overlay hydrate',json.dumps(a.trace))

    def test_actual_original_run_with_simulated_socket_one_receiver_no_auto_effect(self):
        received=[];calls=[]
        welcome={'metadata':{'message_type':'session_welcome','message_id':'welcome','message_timestamp':datetime.now(timezone.utc).isoformat()},'payload':{'session':{'id':'session','keepalive_timeout_seconds':10}}}
        revoked=copy.deepcopy(welcome);revoked['metadata'].update(message_type='revocation',message_id='revocation')
        frames=iter([welcome,envelope(),envelope('viewer free text','free'),revoked])
        class Socket:
            async def recv(self):return json.dumps(next(frames))
            async def close(self):pass
        socket=Socket()
        class Connection:
            def __await__(self):
                async def result():return socket
                return result().__await__()
        def connect(*args,**kwargs):calls.append('connect');return Connection()
        class Helix:
            def __init__(self,*args):self.next_validation=float('inf')
            def validate(self):calls.append('validate')
            async def subscribe(self,session):calls.append('subscribe');return {twitch.CHAT:'sub'}
        # A second private globals dictionary substitutes effects only, not validation.
        import types
        run=types.FunctionType(chat.run.__code__,{**chat.run.__globals__,'Helix':Helix,
            'websockets':SimpleNamespace(connect=connect,exceptions=twitch.websockets.exceptions)},argdefs=chat.run.__defaults__)
        logs=[]
        result=asyncio.run(run(twitch.Config('client','123','456',{}),twitch.LIVE,lambda:None,
            lambda req:received.append(req) or {'result':'queued'},enabled=True,log=logs.append))
        self.assertEqual(calls,['validate','connect','subscribe'])
        self.assertEqual(len(received),2);self.assertTrue(result.stopped)
        self.assertNotIn('viewer free text',json.dumps(logs)+json.dumps(result.trace))


class QueueBounds(unittest.TestCase):
    def test_sanitization_rate_capacity_expiry_and_clear_dedup(self):
        now=[1.0];q=RequestQueue(clock=lambda:now[0])
        def admit(i,viewer='1',text='hello'):
            return q.admit('session',str(i),viewer,text)
        self.assertTrue(admit(1,text='\x00<b>INERT</b>\u202e'+('x'*300)))
        self.assertEqual(len(q.view()[0]['text']),240)
        self.assertNotIn('\u202e',q.view()[0]['text'])
        self.assertTrue(admit(2));self.assertFalse(admit(3))
        q.clear();self.assertFalse(admit(1))
        now[0]+=11
        for i in range(20):self.assertTrue(admit(100+i,str(i+20)))
        self.assertFalse(admit(500,'500'));self.assertEqual(len(q.view()),20)
        now[0]+=q.ttl+1;self.assertEqual(q.view(),[])
        self.assertTrue(admit(500,'500'))


class OperatorQueue(unittest.TestCase):
    setUp=existing.NativeIntegration.setUp
    tearDown=existing.NativeIntegration.tearDown
    do=existing.NativeIntegration.do
    preview=existing.NativeIntegration.preview
    def ready(self):
        self.do('stage_patch',fields={'mode':'live'});self.preview();self.do('take')
        self.do('audience',enabled=True)
    def enqueue(self,text='VIEWER_RAW_ONLY <img src=x onerror=alert(1)>',suggested=None):
        result=self.d.enqueue_request({'session':'session','event_id':str(self.d.version),
            'viewer_id':'789','text':text,'suggested':suggested})
        self.assertEqual(result['result'],'queued')
        return self.d.requests.view()[-1]
    def select(self,item,intent='hydrate'):
        self.do('request_select',id=item['id'],revision=item['revision'],intent=intent)
        return self.d.requests.view()[-1]
    def accept(self,item,intent='hydrate'):
        return self.do('request_accept',id=item['id'],revision=item['revision'],intent=intent)

    def test_exact_operator_selection_acceptance_once_no_automatic_viewer_action(self):
        self.ready();a=adapter(self.d.enqueue_request)
        a.feed(envelope());self.assertIsNone(self.d.alert)
        item=self.d.requests.view()[0]
        self.assertEqual(item['suggested'],'hydrate');self.assertIsNone(item['selected'])
        with self.assertRaises(ValueError):self.accept(item)
        selected=self.select(item,'celebration')  # Streamer can override suggestion.
        with self.assertRaises(ValueError):self.accept(item,'celebration')
        self.accept(selected,'celebration');self.assertEqual(self.d.alert['title'],'Celebration')
        with self.assertRaises(ValueError):self.accept(selected,'celebration')
        self.assertEqual(self.d.requests.view(),[])

    def test_unknown_text_is_inert_and_absent_from_agent_render_storage_export(self):
        self.ready();item=self.enqueue();self.assertIsNone(self.d.alert)
        self.assertIn('VIEWER_RAW_ONLY',json.dumps(self.d.state()['chat_requests']))
        for channel in ('program','preview','bank-A','bank-B'):
            self.assertNotIn('VIEWER_RAW_ONLY',json.dumps(self.d.render(channel)))
        self.assertNotIn('VIEWER_RAW_ONLY',json.dumps(self.d.agent_state()))
        self.assertNotIn('VIEWER_RAW_ONLY',self.d.markers_csv()+json.dumps(self.d.events))
        self.do('recipe_save',name='Queue privacy')
        for file in Path(self.tmp.name).rglob('*.json'):
            self.assertNotIn('VIEWER_RAW_ONLY',file.read_text())
        with self.assertRaises(ValueError):self.select(item,'make arbitrary overlay')
        selected=self.select(item);self.accept(selected)
        self.assertEqual(self.d.alert['title'],'Hydrate!')
        self.assertNotIn('VIEWER_RAW_ONLY',json.dumps(self.d.render('program')))

    def test_reject_expire_clear_pause_disarm_and_stale_version_refuse(self):
        self.ready();item=self.enqueue()
        version=self.d.version;selected=self.select(item)
        with self.assertRaises(Conflict):self.d.execute({'action':'request_accept','id':selected['id'],'revision':selected['revision'],'intent':'hydrate'},version)
        self.do('request_reject',id=selected['id'],revision=selected['revision'])
        with self.assertRaises(ValueError):self.accept(selected)
        self.d.requests.rate.clear()
        for mutation in ('requests_clear','pause','arm'):
            item=self.enqueue();selected=self.select(item)
            if mutation=='pause':self.do('pause',paused=True)
            elif mutation=='arm':self.do('arm',enabled=False)
            else:self.do(mutation)
            with self.assertRaises((ValueError,ObsError)):self.accept(selected)
            if mutation=='pause':self.do('pause',paused=False)
            elif mutation=='arm':self.do('arm',enabled=True)
            self.d.requests.rate.clear()
        now=[1.0];self.d.requests=RequestQueue(clock=lambda:now[0])
        item=self.enqueue();selected=self.select(item);now[0]+=100
        with self.assertRaises(ValueError):self.accept(selected)
        self.assertIsNone(self.d.alert)

    def test_refused_effect_consumes_request_and_disarms_without_retry(self):
        self.ready();item=self.enqueue();selected=self.select(item)
        with patch.object(self.d,'_fixed_alert',return_value={'result':'input off'}) as effect:
            with self.assertRaises(ObsError):self.accept(selected)
            self.assertFalse(self.d.armed);self.assertEqual(self.d.requests.view(),[])
            with self.assertRaises(ObsError):self.accept(selected)
            self.assertEqual(effect.call_count,1)

    def test_actual_loopback_ingress_and_operator_http_acceptance(self):
        import os, threading, urllib.request, urllib.error
        from director_server import make_server
        self.ready();server=make_server(0,self.d)
        worker=threading.Thread(target=server.serve_forever);worker.start()
        url=f'http://127.0.0.1:{server.server_port}'
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def call(path,body=None,origin=url):
            req=urllib.request.Request(url+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json','Origin':origin})
            with opener.open(req,timeout=8) as response:return json.load(response)
        try:
            self.assertEqual(call('/api/health')['pid'],os.getpid())
            print(f'Verified queue HTTP PID {os.getpid()} port {server.server_port}; stopped in teardown')
            a=adapter(chat.QueueSink(server.server_port))
            a.feed(envelope('RAW_QUEUE_HTTP_ONLY <script>inert</script>'))
            self.assertIsNone(self.d.alert)
            state=call('/api/state');item=state['chat_requests'][0]
            self.assertIn('RAW_QUEUE_HTTP_ONLY',item['text'])
            self.assertNotIn('RAW_QUEUE_HTTP_ONLY',json.dumps(call('/api/agent-state')))
            with self.assertRaises(urllib.error.HTTPError) as err:
                call('/api/chat-request',{'action':'request_accept'},origin='http://viewer.invalid')
            self.assertEqual(err.exception.code,403)
            with self.assertRaises(urllib.error.HTTPError):
                call('/api/agent',{'expected':self.d.version,'command':{'action':'request_select','id':item['id'],'revision':1,'intent':'hydrate'}})
            state=call('/api/action',{'expected':self.d.version,'command':{'action':'request_select','id':item['id'],'revision':1,'intent':'hydrate'}})
            item=state['chat_requests'][0]
            call('/api/action',{'expected':state['version'],'command':{'action':'request_accept','id':item['id'],'revision':item['revision'],'intent':'hydrate'}})
            self.assertEqual(self.d.alert['title'],'Hydrate!')
            self.assertEqual(self.d.requests.view(),[])
        finally:
            server.shutdown();server.server_close();worker.join(timeout=3)
            self.assertFalse(worker.is_alive())

    def test_agent_cannot_select_accept_or_get_raw_requests_or_approve_take(self):
        self.ready();item=self.enqueue()
        for action in ('request_select','request_accept','request_reject','requests_clear','approve_agent_take'):
            with self.assertRaises(ValueError):self.d.execute_agent({'action':action,'id':item['id'],'revision':1,'intent':'hydrate'},self.d.version)
        self.assertNotIn('chat_requests',self.d.agent_state())
        self.do('compose',title='Authored by operator');self.preview()
        with self.assertRaises(ValueError):self.d.execute_agent({'action':'take'},self.d.version)

if __name__=='__main__':unittest.main()
