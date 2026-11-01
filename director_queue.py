"""Bounded ephemeral operator inbox. Display text never leaves this object except controller state."""
from collections import OrderedDict, deque
import re
import time
import unicodedata
import uuid

INTENTS = {'celebration': 'Director party', 'hydrate': 'Director show Hydrate!', 'dismiss-alert': 'Director clear'}


class RequestQueue:
    ttl = 90
    capacity = 20
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.items = OrderedDict()
        self.seen = OrderedDict()
        self.rate = deque(maxlen=20)

    def expire(self):
        now = self.clock()
        for key in list(self.items):
            if self.items[key]['expires'] <= now: del self.items[key]
        for key in list(self.seen):
            if self.seen[key] <= now: del self.seen[key]
        while self.rate and self.rate[0][0] <= now-10: self.rate.popleft()

    def clear(self):
        self.items.clear()  # Keep bounded dedup/rate history; clearing is not admission reset.

    def admit(self, session, event_id, viewer_id, text, suggested=None):
        if any(not isinstance(v,str) or not 1 <= len(v) <= 128 for v in (session,event_id)):
            raise ValueError('Invalid request identity')
        if not isinstance(viewer_id,str) or not re.fullmatch(r'[0-9]{1,32}',viewer_id):
            raise ValueError('Numeric chatter identity required')
        if not isinstance(text,str) or len(text)>5000: raise ValueError('Invalid request text')
        if suggested is not None and (not isinstance(suggested,str) or suggested not in INTENTS): raise ValueError('Invalid request suggestion')
        text=''.join(c for c in text if not unicodedata.category(c).startswith('C'))[:240].strip()
        if not text: raise ValueError('Empty request text')
        self.expire();now=self.clock();key=(session,event_id)
        if key in self.seen: return False
        self.seen[key]=now+self.ttl
        while len(self.seen)>200: self.seen.popitem(last=False)
        if len(self.items)>=self.capacity or len(self.rate)>=20 or sum(v==viewer_id for _,v in self.rate)>=2:
            return False
        self.rate.append((now,viewer_id))
        ident=uuid.uuid4().hex
        self.items[ident]={'id':ident,'revision':1,'text':text,'suggested':suggested,'selected':None,
                           'viewer_id':viewer_id,'expires':now+self.ttl}
        return True

    def view(self):
        self.expire()
        return [{k:v for k,v in item.items() if k!='viewer_id'} for item in self.items.values()]

    def item(self, ident, revision):
        self.expire()
        if not isinstance(ident,str) or ident not in self.items: raise ValueError('Request unavailable or expired')
        item=self.items[ident]
        if type(revision) is not int or item['revision']!=revision: raise ValueError('Request revision changed')
        return item

    def select(self, ident, revision, intent):
        if not isinstance(intent,str) or intent not in INTENTS: raise ValueError('Select one fixed request intent')
        item=self.item(ident,revision)
        item['selected']=intent;item['revision']+=1

    def consume(self, ident, revision, intent):
        item=self.item(ident,revision)
        if not isinstance(intent,str) or intent not in INTENTS or item['selected']!=intent:
            raise ValueError('Select and accept the exact fixed request intent')
        del self.items[ident]
        return INTENTS[intent]
