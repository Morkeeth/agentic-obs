"""Operator-only participation protocol, simulated OBS; no real service/device."""
import copy
import json
import unittest
import test_director_chat_poll as polling

SENTINEL='RAW_VIEWER_ONLY_<sentinel>_never_model_render_export'
class Participation(unittest.TestCase):
    setUp=polling.ChatPoll.setUp
    tearDown=polling.ChatPoll.tearDown
    do=polling.ChatPoll.do
    preview=polling.ChatPoll.preview
    taken=polling.ChatPoll.taken
    ready=polling.ChatPoll.ready
    def test_operator_projection_and_exact_select_accept_keeps_other(self):
        self.ready()
        for ident,text in [('one',SENTINEL),('two','second inert request')]:
            self.d.enqueue_request({'session':'session','event_id':ident,'viewer_id':ident=='one' and '1001' or '1002','text':text,'suggested':None})
        state=self.d.participation_state()
        self.assertEqual(len(state['requests']),2)
        self.assertIn(SENTINEL,json.dumps(state))
        self.assertNotIn('viewer_id',json.dumps(state))
        row=state['requests'][0]
        state=self.d.participation_action({'action':'request_select','id':row['id'],'revision':row['revision'],'intent':'hydrate'},state['version'])
        row2=next(x for x in state['requests'] if x['id']==row['id'])
        with self.assertRaises(ValueError):
            self.d.participation_action({'action':'request_accept','id':row['id'],'revision':row['revision'],'intent':'hydrate'},state['version'])
        state=self.d.participation_state()
        result=self.d.participation_action({'action':'request_accept','id':row2['id'],'revision':row2['revision'],'intent':'hydrate'},state['version'])
        self.assertEqual(len(result['requests']),1)
        self.assertEqual(result['requests'][0]['text'],'second inert request')
        with self.assertRaises(ValueError):self.d.participation_action({'action':'request_accept','id':row2['id'],'revision':row2['revision'],'intent':'hydrate'},result['version'])
        for value in (self.d.agent_state(),self.d.render('program'),self.d.render('preview'),self.d.markers_csv(),self.d.recipes,self.d.events):
            self.assertNotIn(SENTINEL,json.dumps(value))
        with self.assertRaises(ValueError):self.d.execute_agent({'action':'request_select','id':row2['id'],'revision':row2['revision'],'intent':'hydrate'},self.d.version)

    def test_waiting_traffic_keeps_version_but_request_revision_ttl_and_cue_stay_guarded(self):
        from test_director_queue import adapter,envelope
        from director import Conflict
        self.ready();receiver=adapter(self.d.enqueue_request);version=self.d.version
        receiver.feed(envelope('fixed request','fixed-traffic','3001'))
        self.assertEqual(self.d.version,version)
        row=self.d.participation_state()['requests'][0]
        selected=self.d.participation_action({'action':'request_select','id':row['id'],'revision':row['revision'],'intent':'hydrate'},version)
        selected_row=selected['requests'][0]
        receiver.feed(envelope('other waiting request','extra-traffic','3002'))
        self.assertEqual(self.d.version,selected['version'])
        with self.assertRaises(ValueError):
            self.d.participation_action({'action':'request_accept','id':row['id'],'revision':row['revision'],'intent':'hydrate'},self.d.version)
        self.preview();reviewed=self.d.agent_state()
        accepted=self.d.participation_action({'action':'request_accept','id':selected_row['id'],'revision':selected_row['revision'],'intent':'hydrate'},reviewed['version'])
        with self.assertRaises(Conflict):self.d.operator_review(reviewed['native_review'],reviewed['version'],'take')
        with self.assertRaises(ValueError):self.d.participation_action({'action':'request_accept','id':selected_row['id'],'revision':selected_row['revision'],'intent':'hydrate'},accepted['version'])
        remaining=self.d.participation_state()['requests'][0]
        expiry=self.d.requests.items[remaining['id']]['expires'];self.d.requests.clock=lambda:expiry+1
        with self.assertRaises(ValueError):self.d.participation_action({'action':'request_select','id':remaining['id'],'revision':remaining['revision'],'intent':'hydrate'},self.d.version)
        self.assertEqual(self.d.participation_state()['requests'],[])

    def test_poll_controls_bind_epoch_and_revision_no_graphics_effects(self):
        self.ready();state=self.d.participation_state();context=state['local_director_poll']
        before=copy.deepcopy((self.d.program,self.d.banks,self.sim.inputs,self.sim.program))
        with self.assertRaises(ValueError):
            self.d.participation_action({'action':'poll_control','epoch':context['epoch'],'revision':'old','operation':'reset'},state['version'])
        result=self.d.participation_action({'action':'poll_control','epoch':context['epoch'],'revision':context['revision'],'operation':'reset'},self.d.version)
        self.assertNotEqual(result['local_director_poll']['epoch'],context['epoch'])
        with self.assertRaises(ValueError):self.d.participation_action({'action':'poll_control','epoch':context['epoch'],'revision':context['revision'],'operation':'open'},self.d.version)
        self.assertEqual((self.d.program,self.d.banks,self.sim.inputs,self.sim.program),before)
        with self.assertRaises(ValueError):self.d.participation_action({'action':'take'},self.d.version)

if __name__=='__main__':unittest.main()

class HTTPParticipation(unittest.TestCase):
    setUp=Participation.setUp
    tearDown=Participation.tearDown
    do=Participation.do
    preview=Participation.preview
    taken=Participation.taken
    ready=Participation.ready
    def test_real_http_projection_and_validated_host_never_route_viewer_to_model(self):
        import asyncio
        import threading
        import urllib.request
        from director_server import make_server
        import director_twitch_native as host
        from test_director_twitch_native import Provider,frame
        from test_director_queue import envelope
        self.ready()
        server=make_server(0,director=self.d)
        worker=threading.Thread(target=server.serve_forever);worker.start()
        base=f'http://127.0.0.1:{server.server_port}'
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def read(path):
            with opener.open(base+path,timeout=2) as reply:return reply.read().decode()
        try:
            self.assertTrue(worker.is_alive());self.assertEqual(json.loads(read('/api/health'))['build'],'expanded-director-1')
            provider=Provider(messages=[envelope(SENTINEL,'raw-http','2001'),envelope('second request','other-http','2002'),envelope('!vote 1','numeric-http','2003')])
            before=copy.deepcopy((self.d.program,self.d.banks,self.sim.program,self.sim.inputs))
            states=[]
            async def exercise():
                await host.receive(frame(port=server.server_port,polls=True),states.append,asyncio.Event(),request=provider.request,websockets=provider.sockets())
            asyncio.run(exercise())
            operator=json.loads(read('/api/participation'))
            self.assertEqual(len(operator['requests']),2);self.assertEqual(operator['poll_tally']['counts'],[1,0])
            self.assertIn(SENTINEL,json.dumps(operator));self.assertEqual((self.d.program,self.d.banks,self.sim.program,self.sim.inputs),before)
            for path in ('/api/agent-state','/api/render?channel=program','/api/render?channel=preview','/api/markers.csv'):
                self.assertNotIn(SENTINEL,read(path))
            self.assertNotIn(SENTINEL,json.dumps(states))
        finally:server.shutdown();server.server_close();worker.join(3)
        self.assertFalse(worker.is_alive())
