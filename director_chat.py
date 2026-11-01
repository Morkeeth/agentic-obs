"""Queue admission after the original EventSub Adapter's validation, never viewer effects.

run has the original transport code object, bound to a private globals dictionary
with QueueAdapter. No global monkeypatch, second listener or copied identity rules.
"""
import json
import re
import types
import urllib.request

import twitch_eventsub as twitch
from director_audience import DirectorSink, _NoRedirect
from director_queue import INTENTS


class QueueSink(DirectorSink):
    def __init__(self,port=8880,enable_local_director_polls=False):
        super().__init__(port)
        if type(enable_local_director_polls) is not bool:raise ValueError('Explicit local director poll flag required')
        self.enable_local_director_polls=enable_local_director_polls

    def submit_numeric_vote(self,request):
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),_NoRedirect())
        get=urllib.request.Request(self.url+'/api/chat-poll',headers={'Origin':self.url})
        with opener.open(get,timeout=2) as response:context=json.load(response)
        if context.get('build')!='expanded-director-1':raise ValueError('Director identity mismatch')
        if not context.get('open'):return {'result':'poll off'}
        body={**request,'epoch':context['epoch'],'revision':context['revision']}
        post=urllib.request.Request(self.url+'/api/chat-vote',data=json.dumps(body).encode(),
            headers={'Content-Type':'application/json','Origin':self.url})
        with opener.open(post,timeout=2) as response:return json.load(response)

    def __call__(self, request):
        if not isinstance(request,dict) or set(request)!={'session','event_id','viewer_id','text','suggested'}:
            raise ValueError('Validated request contract required')
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),_NoRedirect())
        req=urllib.request.Request(self.url+'/api/chat-request',data=json.dumps(request).encode(),
            headers={'Content-Type':'application/json','Origin':self.url})
        with opener.open(req,timeout=2) as response:return json.load(response)


class QueueAdapter(twitch.Adapter):
    def __init__(self,cfg,endpoints,send):
        if cfg.rewards: raise ValueError('Queue receiver is read-chat-only')
        self.queue_sink=send
        self.suggested=None
        super().__init__(cfg,endpoints,lambda cue:setattr(self,'suggested',cue))

    def feed(self,envelope):
        self.suggested=None
        result=super().feed(envelope)  # All metadata/identity/session/dedup rules remain here.
        if result['result'] not in ('ignored','forwarded'):return result
        # Original unknown-chat ignore precedes enabled checks. Never treat ignore as permission.
        if not self.enabled or self.stopped or not self.session or not self.subscriptions.get(twitch.CHAT):return result
        payload=envelope['payload']
        if payload['subscription']['type']!=twitch.CHAT:return result
        event=payload['event'];viewer=event.get('chatter_user_id');text=event.get('message',{}).get('text')
        if not isinstance(viewer,str) or not re.fullmatch(r'[0-9]{1,32}',viewer) or not isinstance(text,str):
            return self.record('queue rejected')
        if getattr(self.queue_sink,'enable_local_director_polls',False) and re.fullmatch(r'!vote [1-6]',text):
            try:
                response=self.queue_sink.submit_numeric_vote({'session':self.session,
                    'event_id':envelope['metadata']['message_id'],'viewer_id':viewer,'choice':int(text[-1]),
                    'timestamp':envelope['metadata']['message_timestamp']})
            except Exception:return self.record('numeric poll unavailable')
            return self.record('numeric vote counted' if response.get('result')=='vote accepted' else 'numeric vote refused')
        suggested=next((key for key,cue in INTENTS.items() if cue==self.suggested),None)
        try:
            response=self.queue_sink({'session':self.session,'event_id':envelope['metadata']['message_id'],
                'viewer_id':viewer,'text':text,'suggested':suggested})
        except Exception:return self.record('queue unavailable')  # No raw text/error logging or mutation retry.
        return self.record('queued' if response.get('result')=='queued' else 'queue refused')


# Fresh globals per binding: keep the original module and its legacy users untouched.
run=types.FunctionType(twitch.run.__code__,{**twitch.run.__globals__,'Adapter':QueueAdapter},
                       name='run',argdefs=twitch.run.__defaults__,closure=twitch.run.__closure__)
