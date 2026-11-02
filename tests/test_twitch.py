import unittest
from streamer import Show,Refused
from obs import RehearsalNative
from twitch_chat import TwitchChat,parse_message

class TwitchTests(unittest.TestCase):
    def test_actual_irc_shape_parses_channel_display_name_and_text(self):
        line='@display-name=Viewer;id=abc;tmi-sent-ts=1793629200000 :viewer!viewer@'+'viewer.tmi.twitch.tv PRIVMSG #twitch :Zoom in on me <script>alert(1)</script>'
        row=parse_message(line,'twitch');self.assertEqual(row['name'],'Viewer');self.assertEqual(row['id'],'abc');self.assertEqual(row['channel'],'twitch');self.assertIn('<script>',row['text'])
        self.assertIsNone(parse_message(line,'another_channel'))
    def test_public_chat_never_has_operator_authority(self):
        show=Show(RehearsalNative());show.enable()
        with self.assertRaises(Refused):show.operator_direction('take it',source='chat')
    def test_channel_validation_rejects_command_injection_and_urls(self):
        chat=TwitchChat()
        for channel in ('bad\r\nPRIVMSG #x :hello','https://twitch.tv/account','../private',''):
            with self.assertRaises(Refused):chat.connect(channel)
    def test_reader_has_no_chat_posting_api(self):
        chat=TwitchChat();self.assertFalse(hasattr(chat,'send_message'));self.assertFalse(hasattr(chat,'send'));self.assertFalse(chat.snapshot()['connected'])
    def test_messages_are_bounded_and_control_characters_are_removed(self):
        row=parse_message(':viewer!a@a PRIVMSG #twitch :'+('a'*1000)+'\x00','twitch')
        self.assertLessEqual(len(row['text']),300);self.assertNotIn('\x00',row['text'])

class RoomStateTests(unittest.TestCase):
    def test_real_guest_roomstate_shape_is_preserved_without_invented_messages(self):
        from twitch_chat import parse_roomstate
        line='@emote-only=0;followers-only=10;r9k=0;room-id=622498423;slow=3;subs-only=1 :tmi.twitch.tv ROOMSTATE #otplol_'
        r=parse_roomstate(line,'otplol_');self.assertEqual(r['room_id'],'622498423');self.assertEqual(r['slow_seconds'],3);self.assertTrue(r['subscribers_only']);self.assertEqual(r['followers_only_minutes'],10)
        self.assertIsNone(parse_roomstate(line,'another'))
