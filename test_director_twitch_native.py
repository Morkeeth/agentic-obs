"""Native host: fake I/O binds actual transport validation, no real endpoints."""
import asyncio
import contextlib
from datetime import datetime,timezone
import io
import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import websockets as real_websockets
import twitch_eventsub as twitch
import director_twitch_native as host
from test_director_queue import envelope

SECRET='SYNTHETIC_PRIVATE_PIPE_ONLY'
RAW='unique-raw-viewer-native-host-never-model'

def frame(**extra):
    return {'protocol':host.PROTOCOL,'enabled':True,'config':{'client_id':'publicclient','channel_login':'channeluser','reader_login':'chatuser'},'port':8880,'polls':False,'token':SECRET,**extra}

class Provider:
    def __init__(self,info=None,messages=None):
        self.info=info or {'client_id':'publicclient','user_id':'456','login':'chatuser','scopes':['user:read:chat'],'expires_in':3600}
        welcome={'metadata':{'message_type':'session_welcome','message_id':'hello','message_timestamp':datetime.now(timezone.utc).isoformat()},'payload':{'session':{'id':'session','keepalive_timeout_seconds':10}}}
        revoke={'metadata':{'message_type':'revocation','message_id':'revoke','message_timestamp':datetime.now(timezone.utc).isoformat()},'payload':{'subscription':{'id':'sub'}}}
        self.messages=[welcome,*(messages or []),revoke];self.http=[];self.closed=False;self.connects=0;self.expected_reader='456';self.lookup_rows=None
    def request(self,url,headers,body=None):
        self.http.append((url,body))
        if url.startswith('https://api.twitch.tv/helix/users?'):
            from urllib.parse import urlsplit,parse_qs
            names=parse_qs(urlsplit(url).query)['login']
            rows=self.lookup_rows if self.lookup_rows is not None else [{'login':name,'id':{'channeluser':'123','chatuser':'456'}[name]} for name in names]
            return {'data':rows}
        if url==twitch.LIVE.validate:return self.info
        assert url==twitch.LIVE.helix
        assert body['condition']=={'broadcaster_user_id':'123','user_id':self.expected_reader}
        return {'data':[{'id':'sub'}]}
    def sockets(self):
        parent=self
        class Socket:
            async def recv(self):
                if parent.messages:return json.dumps(parent.messages.pop(0))
                await asyncio.Event().wait()
            async def close(self):parent.closed=True
        class Connection:
            def __await__(self):
                async def connected():parent.connects+=1;return Socket()
                return connected().__await__()
        return SimpleNamespace(connect=lambda *a,**k:Connection(),exceptions=real_websockets.exceptions)

class Sink:
    def __init__(self,*args,**kwargs):self.enable_local_director_polls=kwargs['enable_local_director_polls'];self.requests=[];self.votes=[]
    def __call__(self,value):self.requests.append(value);return {'result':'queued'}
    def submit_numeric_vote(self,value):self.votes.append(value);return {'result':'vote accepted'}

class NativeHost(unittest.TestCase):
    def run_host(self,provider,body=None):
        statuses=[];sink=Sink(enable_local_director_polls=False)
        async def exercise():
            await host.receive(body or frame(),statuses.append,asyncio.Event(),request=provider.request,
                websockets=provider.sockets(),sink_factory=lambda *a,**k:(setattr(sink,'enable_local_director_polls',k['enable_local_director_polls']) or sink))
        asyncio.run(exercise());return statuses,sink
    def test_username_setup_resolves_authenticated_metadata_before_original_validation(self):
        p=Provider();original=p.request
        def lookup(url,headers,body=None):
            if url.startswith('https://api.twitch.tv/helix/users?'):
                p.http.append((url,body))
                self.assertEqual(headers['Authorization'],'Bearer '+SECRET)
                return {'data':[{'login':'channeluser','id':'123'},{'login':'chatuser','id':'456'}]}
            return original(url,headers,body)
        p.request=lookup;p.info['login']='chatuser'
        statuses,_=self.run_host(p,frame(config={'client_id':'publicclient','channel_login':'ChannelUser','reader_login':'ChatUser'}))
        self.assertIn('ready',statuses)
        self.assertIn('login=channeluser',p.http[0][0]);self.assertIn('login=chatuser',p.http[0][0])
        self.assertEqual(p.http[-1][1]['condition'],{'broadcaster_user_id':'123','user_id':'456'})

    def test_chat_username_defaults_to_channel_with_one_lookup(self):
        p=Provider();p.info.update(user_id='123',login='channeluser');p.expected_reader='123'
        statuses,_=self.run_host(p,frame(config={'client_id':'publicclient','channel_login':' ChannelUser ','reader_login':''}))
        self.assertIn('ready',statuses)
        self.assertTrue(p.http[0][0].endswith('?login=channeluser'))
        self.assertEqual(p.http[-1][1]['condition']['user_id'],'123')

    def test_missing_ambiguous_mismatched_metadata_cannot_authorize(self):
        cases=[[],[{'login':'channeluser','id':'123'}],
            [{'login':'channeluser','id':'123'},{'login':'wrong','id':'456'}],
            [{'login':'channeluser','id':'123'},{'login':'channeluser','id':'456'}],
            [{'login':'channeluser','id':'123'},{'login':'chatuser','id':'123'}],
            [{'login':'channeluser','id':None},{'login':'chatuser','id':'456'}],
            [{'login':'channeluser','id':'123'},{'login':'chatuser','id':'456'},{'login':'extra','id':'999'}]]
        for rows in cases:
            with self.subTest(rows=rows):
                p=Provider();p.lookup_rows=rows
                states,_=self.run_host(p)
                self.assertNotIn('ready',states);self.assertEqual(states[-1],'error')
                self.assertEqual(p.connects,0)
                self.assertTrue(all('helix/users?' in url for url,_ in p.http))
        p=Provider();p.info['login']='otheraccount'
        statuses,_=self.run_host(p)
        self.assertNotIn('ready',statuses);self.assertEqual(p.connects,0)
        for names in ({'channel_login':'https://twitch.tv/channeluser'}, {'channel_login':'channeluser','reader_login':False}):
            p=Provider()
            states,_=self.run_host(p,frame(config={'client_id':'publicclient',**names}))
            self.assertNotIn('ready',states);self.assertEqual(states[-1],'error')
            self.assertEqual(p.http,[])

    def test_default_does_not_read_pipe_prompt_credentials_or_network(self):
        class Never:
            def read(self,*a):raise AssertionError('secret read')
        out=io.StringIO()
        with contextlib.redirect_stdout(out),patch('socket.socket',side_effect=AssertionError('network')):
            self.assertEqual(host.main([],source=Never()),0)
        self.assertEqual(json.loads(out.getvalue())['state'],'disabled')
    def test_ready_requires_actual_base_validation_scope_session_subscription(self):
        for changed in ({'client_id':'wrong'},{'user_id':'999'},{'scopes':['user:read:chat','chat:edit']},{'scopes':[]},{'expires_in':0}):
            p=Provider();p.info.update(changed)
            statuses,sink=self.run_host(p)
            self.assertNotIn('ready',statuses);self.assertEqual(p.connects,0);self.assertFalse(sink.requests)
        p=Provider();statuses,_=self.run_host(p)
        self.assertIn('ready',statuses);self.assertEqual(p.connects,1)
        self.assertEqual(len(p.http),3);self.assertTrue(p.closed)
        self.assertIs(host.binding(lambda _:None).__code__,twitch.run.__code__)
    def test_adapter_real_identity_replay_and_raw_text_boundaries(self):
        good=envelope(RAW,'raw','1111')
        wrong=envelope('wrong-channel','wrong','2222');wrong['payload']['subscription']['condition']['broadcaster_user_id']='999'
        messages=[good,good,wrong,envelope('!vote 1','vote','3333')]
        statuses,sink=self.run_host(Provider(messages=messages),frame(polls=True))
        self.assertIn('ready',statuses)
        self.assertEqual([x['text'] for x in sink.requests],[RAW])
        self.assertEqual([x['choice'] for x in sink.votes],[1])
        self.assertNotIn('text',sink.votes[0]);self.assertNotIn(RAW,json.dumps(statuses))
        self.assertNotIn(SECRET,json.dumps(statuses));self.assertNotEqual(statuses[-1],'ready')
    def test_explicit_disable_never_validates_and_errors_are_sanitized(self):
        statuses=[]
        async def exercise():await host.receive(frame(enabled=False),statuses.append,asyncio.Event(),request=lambda *a:(_ for _ in ()).throw(AssertionError('network')))
        asyncio.run(exercise());self.assertEqual(statuses,['disabled'])
        out=io.StringIO();err=io.StringIO()
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            self.assertEqual(host.main(['--token',SECRET]),2)
        self.assertNotIn(SECRET,out.getvalue()+err.getvalue());self.assertNotIn('Traceback',err.getvalue())
    def test_subscription_failure_bad_welcome_and_external_error_never_ready(self):
        p=Provider()
        original=p.request
        def missing_sub(url,headers,body=None):
            return {'data':[]} if url==twitch.LIVE.helix else original(url,headers,body)
        p.request=missing_sub
        statuses,_=self.run_host(p);self.assertNotIn('ready',statuses)
        p=Provider();p.messages[0]['payload']['session']['id']=None
        statuses,_=self.run_host(p);self.assertNotIn('ready',statuses)
        p=Provider()
        def external(*args,**kwargs):raise RuntimeError(SECRET)
        p.request=external
        out=io.StringIO();err=io.StringIO()
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):statuses,_=self.run_host(p)
        self.assertEqual(statuses[-1],'error')
        self.assertNotIn(SECRET,out.getvalue()+err.getvalue()+json.dumps(statuses))

    def test_actual_private_pipe_main_ready_and_stop_with_fake_endpoint_io(self):
        import os
        readfd,writefd=os.pipe();p=Provider();p.messages=p.messages[:1]
        os.write(writefd,json.dumps(frame()).encode()+b'\n')
        class Output(io.StringIO):
            stopped=False
            def write(self,value):
                if '"state": "ready"' in value and not self.stopped:
                    self.stopped=True
                    os.write(writefd,b'{"command":"stop"}\n');os.close(writefd)
                return super().write(value)
        out=Output();err=io.StringIO()
        try:
            with os.fdopen(readfd,'rb',buffering=0) as source,contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
                code=host.main(['--live-host-rehearsal'],source=source,io_dependencies={'request':p.request,'websockets':p.sockets(),'sink_factory':Sink})
            self.assertEqual(code,0);self.assertTrue(out.stopped);self.assertTrue(p.closed)
            states=[json.loads(line)['state'] for line in out.getvalue().splitlines()]
            self.assertIn('ready',states);self.assertEqual(states[-1],'stopped')
            self.assertNotIn(SECRET,out.getvalue()+err.getvalue());self.assertNotIn('Traceback',err.getvalue())
        finally:
            if not out.stopped:os.close(writefd)

    def test_clean_stop_cancels_owned_socket_without_replaying(self):
        p=Provider();p.messages=p.messages[:1];statuses=[];stop=asyncio.Event()
        def emit(value):
            statuses.append(value)
            if value=='ready':stop.set()
        async def exercise():await host.receive(frame(),emit,stop,request=p.request,websockets=p.sockets(),sink_factory=Sink)
        asyncio.run(exercise())
        self.assertTrue(p.closed);self.assertEqual(statuses[-1],'stopped');self.assertEqual(p.connects,1)

if __name__=='__main__':unittest.main()
