import asyncio
import json
import unittest
from websockets.asyncio.server import serve
from mock_eventsub import Adapter,consume
from mock_eventsub_fixtures import packet
class Transport(unittest.IsolatedAsyncioTestCase):
    async def test_keepalive_loss_disables_client(self):
        sent=[];adapter=Adapter(sent.append);adapter.enabled=True
        async def mock(ws):
            p=packet();p['payload']['session']['keepalive_timeout_seconds']=1
            await ws.send(json.dumps(p));await ws.wait_closed()
        async with serve(mock,'127.0.0.1',8882):await consume('ws://127.0.0.1:8882/ws',adapter)
        self.assertFalse(adapter.enabled)
        self.assertEqual(adapter.trace[-1]['result'],'keepalive timeout')
        self.assertEqual(sent,[])
    async def test_websocket_redirect_is_refused(self):
        from websockets.exceptions import InvalidStatus
        async def redirect(connection,request):
            response=connection.respond(302,'redirect refused')
            response.headers['Location']='ws://127.0.0.1:9999/ws'
            return response
        adapter=Adapter(lambda _:self.fail('no cues expected'));adapter.enabled=True
        async with serve(lambda ws:None,'127.0.0.1',8882,process_request=redirect):
            with self.assertRaises(InvalidStatus):await consume('ws://127.0.0.1:8882/ws',adapter)
        self.assertFalse(adapter.enabled)
    async def test_disconnect_disables_client(self):
        adapter=Adapter(lambda _:self.fail('no cues expected'));adapter.enabled=True
        async def mock(ws):await ws.close()
        async with serve(mock,'127.0.0.1',8882):await consume('ws://127.0.0.1:8882/ws',adapter)
        self.assertFalse(adapter.enabled)
if __name__=='__main__':unittest.main()
