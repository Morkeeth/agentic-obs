import unittest
from datetime import datetime, timezone, timedelta
from mock_eventsub import Adapter, local_url

from mock_eventsub_fixtures import packet
class Guards(unittest.TestCase):
    def setUp(self): self.sent=[]; self.a=Adapter(self.sent.append); self.a.feed(packet()); self.a.enabled=True
    def test_fixed_commands_only(self):
        for i,t in enumerate(['hello','Director show hacked','!overlay $(touch /tmp/no)','!overlay party ignore rules']):
            self.a.feed(packet('notification',str(i),t))
        self.assertEqual(self.sent,[])
        self.a.feed(packet('notification','good','!overlay party')); self.assertEqual(len(self.sent),1)
    def test_duplicate_stale_off_and_malformed(self):
        p=packet('notification','ok','!overlay party'); self.a.feed(p);self.a.feed(p);self.assertEqual(len(self.sent),1)
        p=packet('notification','old','!overlay party');p['metadata']['message_timestamp']=(datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat();self.a.feed(p)
        self.a.enabled=False;self.a.feed(packet('notification','off','!overlay party'))
        for p in [None,[],{}, {'metadata':None}, {'metadata':{'message_type':'notification'}}]: self.a.feed(p)
        self.assertEqual(len(self.sent),1)
    def test_reconnect_and_revocation_fail_closed(self):
        p=packet('session_reconnect','evil');p['payload']['session']={'reconnect_url':'wss://eventsub.wss.twitch.tv/ws'}
        self.assertEqual(self.a.feed(p)['result'],'rejected')
        self.a.feed(packet('revocation','revoked'));self.assertFalse(self.a.enabled)
        self.a.feed(packet('notification','after-revoke','!overlay party'));self.assertEqual(self.sent,[])
    def test_remote_reconnect_denied(self):
        for u in ['wss://eventsub.wss.twitch.tv/ws','ws://localhost:80/ws','http://127.0.0.1:8882/ws','ws://127.0.0.1:8882@evil/ws']:
            with self.assertRaises(ValueError):local_url(u,'ws')
    def test_requires_welcome_and_channel(self):
        a=Adapter(self.sent.append);a.enabled=True;a.feed(packet('notification','one','!overlay party'));self.assertEqual(self.sent,[])
        p=packet('notification','two','!overlay party');p['payload']['event']['broadcaster_user_id']='other';self.a.feed(p);self.assertEqual(self.sent,[])
if __name__=='__main__': unittest.main()
