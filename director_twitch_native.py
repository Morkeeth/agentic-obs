"""DEFAULT-OFF native read-chat host. Secret arrives only on owned stdin pipe.

No credential lookup, OAuth, refresh, environment token, config file or UI here.
The parent performs a deliberate Keychain lookup. Private binding reuses the
original transport run/Helix validation code and QueueAdapter identity boundary.
"""
import argparse
import asyncio
import json
import re
from urllib.parse import urlencode
import sys
import threading
import types

import twitch_eventsub as twitch
from director_chat import QueueAdapter, QueueSink
from director_twitch import public_config, public_client_id

PROTOCOL='director-twitch-host-1'

class Parser(argparse.ArgumentParser):
    def error(self,_message): raise ValueError('Invalid native host arguments')


def binding(emit, *, request=None, websockets=None, expected_login=None):
    """Inject endpoint I/O for independent tests, retaining real validators/code."""
    state={'validated':False,'adapter':None,'last':None}
    def status(value):
        if state['last']!=value:
            state['last']=value;emit(value)
    def readiness():
        a=state['adapter']
        ready=bool(state['validated'] and a and a.enabled and not a.stopped and a.session
                   and isinstance(a.subscriptions.get(twitch.CHAT),str) and a.subscriptions[twitch.CHAT])
        status('ready' if ready else 'not-ready')
    def original(method):
        if request is None:return method
        return types.FunctionType(method.__code__,{**method.__globals__,'request':request},
                                  method.__name__,method.__defaults__,method.__closure__)
    BaseHelix=type('BoundOriginalHelix',(twitch.Helix,),{
        'validate':original(twitch.Helix.validate),'subscribe':original(twitch.Helix.subscribe)})
    class ReadChatHelix(BaseHelix):
        def validate(self):
            state['validated']=False;readiness()
            info=super().validate()  # Original client/reader/expiry validation, not copied.
            if expected_login is not None and info.get('login')!=expected_login:
                raise twitch.TwitchError('Resolved chat account login mismatch')
            if info.get('scopes')!=['user:read:chat']:
                raise twitch.TwitchError('Native host requires exact read-chat scope')
            state['validated']=True;readiness()
            return info
    class ObservedQueueAdapter(QueueAdapter):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs);state['adapter']=self
        def __setattr__(self,name,value):
            super().__setattr__(name,value)
            if name=='enabled' and state['adapter'] is self:readiness()
        def record(self,*args,**kwargs):
            result=super().record(*args,**kwargs)
            if self.stopped:status('not-ready')
            return result
    environment={**twitch.run.__globals__,'Adapter':ObservedQueueAdapter,'Helix':ReadChatHelix}
    if websockets is not None:environment['websockets']=websockets
    run=types.FunctionType(twitch.run.__code__,environment,'run',twitch.run.__defaults__,twitch.run.__closure__)
    return run


def resolve_usernames(value,token,request):
    """Authenticated read-only Get Users metadata, never an authorization substitute."""
    if not isinstance(value,dict) or set(value)-{'client_id','channel_login','reader_login'}:
        raise ValueError('Client ID and Twitch usernames required')
    client=public_client_id(value.get('client_id'))
    def login(text):
        if not isinstance(text,str):raise ValueError('Twitch username required')
        text=text.strip().lower()
        if not re.fullmatch(r'[a-z0-9_]{1,25}',text):raise ValueError('Use a Twitch login name, not a URL or ID lookup')
        return text
    channel=login(value.get('channel_login'))
    reader_value=value.get('reader_login','')
    if not isinstance(reader_value,str):raise ValueError('Chat account username required')
    reader=login(reader_value.strip() or channel)
    names=tuple(dict.fromkeys((channel,reader)))
    url='https://api.twitch.tv/helix/users?'+urlencode([('login',name) for name in names])
    reply=request(url,{'Client-Id':client,'Authorization':'Bearer '+token.removeprefix('oauth:')})
    rows=reply.get('data') if isinstance(reply,dict) else None
    if not isinstance(rows,list) or len(rows)!=len(names):raise ValueError('Missing or ambiguous username metadata')
    found={}
    for row in rows:
        if not isinstance(row,dict) or row.get('login') not in names or row['login'] in found:
            raise ValueError('Username metadata mismatch')
        found[row['login']]=row.get('id')
    if set(found)!=set(names) or any(not isinstance(ident,str) for ident in found.values()) or len(set(found.values()))!=len(names):
        raise ValueError('Ambiguous username identities')
    # Numeric identifiers remain internal and pass through the existing boundary.
    cfg=public_config({'client_id':client,'broadcaster_user_id':found[channel],'reader_user_id':found[reader]})
    return cfg,reader


async def receive(frame,emit,stop,*,request=None,websockets=None,sink_factory=QueueSink,commands=None):
    if not isinstance(frame,dict) or set(frame)!={'protocol','enabled','config','port','polls','token'}:
        raise ValueError('Native private pipe contract required')
    if frame['protocol']!=PROTOCOL or frame['enabled'] is not True:
        emit('disabled');return
    if type(frame['polls']) is not bool:raise ValueError('Explicit numeric flag required')
    sink=sink_factory(frame['port'],enable_local_director_polls=frame['polls'])
    token=frame.pop('token')
    if not isinstance(token,str) or not 1<=len(token)<=4096 or any(ord(c)<33 or ord(c)>126 for c in token):
        raise ValueError('Invalid secret input')
    emit('starting')
    try:cfg,reader_login=await asyncio.to_thread(resolve_usernames,frame['config'],token,request or twitch.request)
    except Exception:
        token=None;frame.clear();emit('error');return
    run=binding(emit,request=request,websockets=websockets,expected_login=reader_login)
    task=asyncio.create_task(run(cfg,twitch.LIVE,lambda:token,sink,enabled=True,max_fresh_sessions=1,log=lambda _record:None))
    stopped=asyncio.create_task(stop.wait())
    def command(data):
        if data=={'command':'stop'}:stop.set()
        elif isinstance(data,dict) and set(data)=={'command','enabled'} and data['command']=='polls' and type(data['enabled']) is bool:
            sink.enable_local_director_polls=data['enabled']
        else:stop.set()
    if commands is not None:commands(command)
    try:
        await asyncio.wait((task,stopped),return_when=asyncio.FIRST_COMPLETED)
    finally:
        task.cancel();stopped.cancel()
        await asyncio.gather(task,stopped,return_exceptions=True)
        token=None;frame.clear();emit('stopped' if stop.is_set() else 'error')


async def pipe_session(frame,emit,source,**dependencies):
    stop=asyncio.Event();loop=asyncio.get_running_loop();buffer=bytearray()
    def commands(callback):
        def readable():
            import os
            chunk=os.read(source.fileno(),4096)
            if not chunk:stop.set();return
            buffer.extend(chunk)
            if len(buffer)>4096:stop.set();return
            while b'\n' in buffer:
                line,_,rest=buffer.partition(b'\n');buffer[:]=rest
                try:callback(json.loads(line))
                except Exception:stop.set()
        loop.add_reader(source.fileno(),readable)
    try:await receive(frame,emit,stop,commands=commands,**dependencies)
    finally:loop.remove_reader(source.fileno())


def main(argv=None,source=None,*,io_dependencies=None):
    lock=threading.Lock()
    def emit(state):
        with lock:print(json.dumps({'protocol':PROTOCOL,'state':state}),flush=True)
    try:
        parser=Parser(description=__doc__)
        parser.add_argument('--live-host-rehearsal',action='store_true')
        args=parser.parse_args(argv)
        if not args.live_host_rehearsal:
            emit('disabled');return 0  # No stdin, credential or network read in default mode.
        source=source or sys.stdin.buffer.raw
        if source.isatty():raise ValueError('Private parent pipe required')
        # Unbuffered read avoids consuming following stop/flag commands into a hidden buffer.
        raw=bytearray()
        while len(raw)<=16384:
            value=source.read(1)
            if not value or value==b'\n':break
            raw.extend(value)
        if len(raw)>16384:raise ValueError('Pipe frame too large')
        frame=json.loads(raw);raw.clear()
        asyncio.run(pipe_session(frame,emit,source,**(io_dependencies or {})))
        return 0
    except KeyboardInterrupt:
        emit('stopped');return 130
    except Exception:
        emit('error');return 2  # No external exception text, secret, traceback or trace serialization.

if __name__=='__main__':raise SystemExit(main())
