import unittest
from streamer import Show,Refused
from obs import RehearsalNative
from chat_commands import ChatCommands

class CommandsTests(unittest.TestCase):
    def setUp(self):
        from test_live import Native
        from live import LiveStudio
        self.show=Show(RehearsalNative());self.native=Native();self.show.live=LiveStudio(self.native,['slide']);self.show.enable();self.now=100
        self.router=ChatCommands(self.show,clock=lambda:self.now)
    def row(self,text,ident='one'):
        return {'id':ident,'name':'Viewer','channel':'demo','text':text,'received_at':'now'}
    def test_opt_in_and_preview_control_required(self):
        self.router.receive(self.row('!brb'));self.assertEqual(self.native.calls,[])
        self.router.configure(True);self.show.disable();self.router.receive(self.row('!zoom','two'));self.assertEqual(self.native.calls,[])
    def test_real_message_fields_drive_only_bounded_preview_and_visible_trigger(self):
        self.router.configure(True)
        for i,(cmd,title) in enumerate([('!brb','Be right back'),('!title Demo the demo','Demo the demo'),('!title take it','take it')]):
            self.now+=3;self.router.receive(self.row(cmd,str(i)));self.assertEqual(self.show.live.current['lower_third'],title)
        self.now+=3;self.router.receive(self.row('!zoom','zoom'));self.assertGreater(self.show.live.current['zoom'],1)
        status=self.router.snapshot();self.assertEqual(status['last']['message']['text'],'!zoom');self.assertEqual(status['last']['status'],'staged');self.assertEqual(self.native.program,'Camera')
    def test_no_take_browser_or_model_injection_and_titles_are_bounded(self):
        self.router.configure(True)
        for i,text in enumerate(['!take','!go live','!zoom and take it','take it','!title '+('x'*181),'!title bad\nline','!title','!open https://example.org']):
            self.now+=3;self.router.receive(self.row(text,str(i)))
        self.assertEqual(self.native.calls,[])
        with self.assertRaises(Refused):self.show.live.execute('take it','chat_preview')
    def test_duplicate_and_rate_limit_do_not_replay_or_queue(self):
        self.router.configure(True);r=self.row('!zoom');self.router.receive(r);zoom=self.show.live.current['zoom']
        self.now+=3;self.router.receive(r);self.assertEqual(self.show.live.current['zoom'],zoom)
        self.router.receive(self.row('!brb','two'));self.router.receive(self.row('!zoom','three'));self.assertEqual(self.show.live.current['zoom'],zoom)
        self.assertEqual(self.router.snapshot()['last']['status'],'rate_limited')
    def test_output_or_program_guard_refuses_chat(self):
        self.router.configure(True);old=self.native.status;self.native.status=lambda:dict(old(),outputs={'stream':True,'record':True,'virtual':False});self.router.receive(self.row('!brb'));self.assertEqual(self.native.calls,[]);self.assertEqual(self.router.snapshot()['last']['status'],'refused')

class ReceiverIntegrationTests(unittest.TestCase):
    def test_actual_irc_parser_dispatches_tagged_message_to_preview_rule(self):
        from unittest.mock import patch
        from twitch_chat import TwitchChat
        from test_live import Native
        from live import LiveStudio
        show=Show(RehearsalNative());native=Native();show.live=LiveStudio(native,['slide']);show.enable()
        chat=TwitchChat();chat.commands=ChatCommands(show);chat.commands.configure(True)
        frame='@emote-only=0;room-id=1;slow=0 :tmi.twitch.tv ROOMSTATE #demo\r\n@display-name=Viewer;id=actual-shape-1 :viewer!viewer@'+'viewer.tmi.twitch.tv PRIVMSG #demo :!title Live chat direction\r\n'
        class Socket:
            def __init__(self):self.frames=iter([frame,'']);self.sent=[]
            def send(self,text):self.sent.append(text)
            def settimeout(self,value):pass
            def recv(self):return next(self.frames)
            def close(self):pass
        socket=Socket()
        with patch('twitch_chat.websocket.create_connection',return_value=socket):chat._receive('demo',chat.stop_event)
        self.assertEqual(chat.snapshot()['received'],1);self.assertEqual(chat.commands.snapshot()['last']['message']['text'],'!title Live chat direction');self.assertEqual(chat.commands.snapshot()['last']['status'],'staged');self.assertEqual(show.live.current['lower_third'],'Live chat direction');self.assertEqual(native.program,'Camera');self.assertFalse(any(s.startswith('PRIVMSG') for s in socket.sent))
