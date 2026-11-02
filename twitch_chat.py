"""Anonymous, read-only Twitch IRC reception. No credentials or chat-send path."""
from collections import deque
import datetime,re,secrets,threading,time
import websocket
from streamer import Refused

CHANNEL=re.compile(r'^[a-z0-9_]{1,25}$')
def parse_message(line,channel):
    tags={}
    if line.startswith('@'):
        raw,_,line=line.partition(' ')
        tags=dict(pair.split('=',1) for pair in raw[1:].split(';') if '=' in pair)
    match=re.fullmatch(r':([^! ]+)![^ ]+ PRIVMSG #([a-z0-9_]+) :(.*)',line,re.S)
    if not match or match[2]!=channel:return None
    def bounded(value,size):return ''.join(c for c in value if ord(c)>=32).strip()[:size]
    return {'id':bounded(tags.get('id',''),80),'name':bounded(tags.get('display-name') or match[1],30),'channel':channel,'text':bounded(match[3],300),'received_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}

def parse_roomstate(line,channel):
    if not line.startswith('@') or not line.endswith(' ROOMSTATE #'+channel):return None
    raw,_,_=line.partition(' ');tags=dict(pair.split('=',1) for pair in raw[1:].split(';') if '=' in pair)
    try:return {'room_id':tags.get('room-id'),'slow_seconds':int(tags.get('slow','0')),'followers_only_minutes':int(tags.get('followers-only','-1')),'subscribers_only':tags.get('subs-only')=='1','emote_only':tags.get('emote-only')=='1'}
    except ValueError:return None

class TwitchChat:
    def __init__(self):
        self.lock=threading.RLock();self.messages=deque(maxlen=50);self.channel=None;self.connected=False;self.error=None;self.stop_event=threading.Event();self.ws=None;self.worker=None;self.received=0;self.room=None;self.commands=None
    def snapshot(self):
        with self.lock:return {'channel':self.channel,'connected':self.connected,'error':self.error,'messages':list(self.messages),'received':self.received,'room':self.room,'commands':self.commands.snapshot() if self.commands else None,'mode':'Anonymous read-only Twitch chat; opt-in fixed preview commands only'}
    def connect(self,channel):
        if not isinstance(channel,str) or not CHANNEL.fullmatch(channel):raise Refused('Use a public Twitch channel name, without URL or punctuation')
        self.stop()
        with self.lock:self.channel=channel;self.connected=False;self.error=None;self.messages.clear();self.received=0;self.room=None;self.stop_event=threading.Event()
        self.worker=threading.Thread(target=self._receive,args=(channel,self.stop_event),daemon=True);self.worker.start();return self.snapshot()
    def _receive(self,channel,stopped):
        connection=None
        try:
            connection=websocket.create_connection('wss://irc-ws.chat.twitch.tv:443',timeout=5,suppress_origin=True)
            if stopped.is_set():return
            self.ws=connection
            # These are protocol negotiation and a public room subscription, never PRIVMSG.
            connection.send('NICK justinfan'+str(secrets.randbelow(900000)+100000)+'\r\n')
            connection.send('CAP REQ :twitch.tv/tags twitch.tv/commands\r\n')
            connection.send('JOIN #'+channel+'\r\n');connection.settimeout(1)
            while not stopped.is_set():
                try:payload=connection.recv()
                except websocket.WebSocketTimeoutException:continue
                if not payload:raise OSError('Chat socket closed')
                for line in payload.split('\r\n'):
                    if line=='PING :tmi.twitch.tv':connection.send('PONG :tmi.twitch.tv\r\n');continue
                    if (' 366 ' in line or ' ROOMSTATE ' in line) and '#'+channel in line:
                        with self.lock:
                            if self.stop_event is stopped:self.connected=True
                    room=parse_roomstate(line,channel)
                    if room:
                        with self.lock:
                            if self.stop_event is stopped:self.room=room
                    row=parse_message(line,channel)
                    if row:
                        with self.lock:
                            if self.stop_event is stopped:self.messages.append(row);self.received+=1
                        if self.stop_event is stopped and not stopped.is_set() and self.commands:self.commands.receive(row)
        except Exception:
            if not stopped.is_set():
                with self.lock:
                    if self.stop_event is stopped:self.error='Twitch chat disconnected. Reconnect to resume.'
        finally:
            with self.lock:
                if self.stop_event is stopped:self.connected=False
            if connection:connection.close()
    def stop(self):
        self.stop_event.set()
        if self.ws:
            try:self.ws.close()
            except Exception:pass
        if self.worker and self.worker.is_alive():self.worker.join(timeout=2)
        self.ws=None;self.worker=None
