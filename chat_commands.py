"""Opt-in, bounded Twitch-to-preview rules; never operator authority."""
from collections import deque
import re
import threading
import time
from streamer import Refused

def preview_command(text):
    if not isinstance(text,str) or any(ord(c)<32 for c in text):return None
    if text=='!brb':return {'action':'title','title':'Be right back'}
    if text=='!zoom':return {'action':'zoom'}
    if text.startswith('!title '):
        title=text[7:].strip()
        if 1<=len(title)<=180:return {'action':'title','title':title}
    return None

class ChatCommands:
    def __init__(self,show,clock=time.monotonic):
        self.show=show;self.clock=clock;self.lock=threading.RLock();self.processing=threading.Lock();self.enabled=False;self.last=None;self.seen=deque(maxlen=256);self.last_action=float('-inf')
    def configure(self,enabled):
        if not isinstance(enabled,bool):raise Refused('Chat commands must be explicitly enabled or disabled')
        with self.lock:self.enabled=enabled
        return self.snapshot()
    def snapshot(self):
        with self.lock:return {'enabled':self.enabled,'allowed':['!brb','!title <text>','!zoom'],'cooldown_seconds':2,'last':self.last}
    def receive(self,row):
        command=preview_command(row.get('text'))
        if command is None:return
        # No state lock is held during OBS work; voice rendering may inspect chat state.
        if not self.processing.acquire(blocking=False):return
        try:
            with self.lock:
                if not self.enabled:return
                ident=row.get('id')
                if not ident or ident in self.seen:return
                self.seen.append(ident)
                message={key:row.get(key) for key in ('id','name','channel','text','received_at')}
                self.last={'message':message,'status':'received'}
                now=self.clock()
                if now-self.last_action<2:self.last['status']='rate_limited';return
                self.last_action=now
            def check():
                with self.lock:
                    if not self.enabled:raise Refused('Chat preview commands disabled')
            try:
                self.show.chat_preview(command,check)
                result=dict(message=message,status='staged',answer='Staged in preview. Program unchanged.')
            except Refused as exc:
                result=dict(message=message,status='refused',answer=str(exc))
            except Exception:
                result=dict(message=message,status='refused',answer='Preview transport failed; native state is uncertain.')
            with self.lock:self.last=result
        finally:self.processing.release()
