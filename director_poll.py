"""Local numeric-counter permission epochs; never a native Twitch Polls API."""
from collections import OrderedDict
from datetime import datetime
import hashlib
import json
import re
import time
import uuid


class LocalDirectorPoll:
    def __init__(self):
        self.enabled=False;self.taken=False
        self.instance=uuid.uuid4().hex;self.serial=0
        self.epoch=None;self.revision=None;self.opened_at=0
        self.seen=OrderedDict()

    def renew(self,definition,taken=None):
        if taken is not None:self.taken=bool(taken)
        self.serial+=1
        self.epoch=f'{self.instance}:{self.serial}' if definition else None
        self.revision=hashlib.sha256(json.dumps(definition,sort_keys=True).encode()).hexdigest() if definition else None
        self.opened_at=time.time()

    def context(self,definition,state,permitted):
        active=bool(self.enabled and self.taken and definition and definition['kind']=='vote' and state and state['open'] and permitted)
        return {'build':'expanded-director-1','feature_enabled':self.enabled,'taken':self.taken,
                'epoch':self.epoch,'revision':self.revision,'open':active,
                'choices':len(definition['options']) if definition else 0}

    def cast(self,data,context,state,voters,check_native):
        fields={'epoch','revision','session','event_id','viewer_id','choice','timestamp'}
        if not isinstance(data,dict) or set(data)!=fields:raise ValueError('Bounded numeric poll contract required')
        if any(not isinstance(data[key],str) or not 1<=len(data[key])<=128 for key in ('session','event_id','viewer_id','timestamp')):
            raise ValueError('Invalid numeric poll identity')
        if not re.fullmatch(r'[0-9]{1,32}',data['viewer_id']) or type(data['choice']) is not int or not 1<=data['choice']<=6:
            raise ValueError('Bounded numeric choice and chatter identity required')
        key=hashlib.sha256(data['event_id'].encode()).hexdigest()
        if key in self.seen:return {'result':'duplicate'}
        self.seen[key]=None
        while len(self.seen)>20000:self.seen.popitem(last=False)
        if not context['open']:return {'result':'poll off'}
        if data['epoch']!=self.epoch or data['revision']!=self.revision:return {'result':'stale poll'}
        try:
            stamp=datetime.fromisoformat(data['timestamp'].replace('Z','+00:00'))
            if stamp.tzinfo is None:raise ValueError()
            sent_at=stamp.timestamp()
        except (ValueError,OverflowError):return {'result':'stale poll'}
        # This opening boundary is additional to the original transport's timestamp check.
        if sent_at<self.opened_at:return {'result':'stale poll'}
        choice=data['choice']-1
        if choice>=len(state['counts']):return {'result':'rejected'}
        voter=hashlib.sha256(('twitch:'+data['viewer_id']).encode()).hexdigest()
        if voter in voters:return {'result':'duplicate'}
        if len(voters)>=10000:return {'result':'capacity reached'}
        check_native()  # Read-only ownership/program check; no scene or composition operation.
        voters[voter]=choice;state['counts'][choice]+=1
        return {'result':'vote accepted'}
