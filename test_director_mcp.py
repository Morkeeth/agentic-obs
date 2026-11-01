"""Actual stdio MCP invocation against simulated OBS, no model/Codex calls."""
import asyncio
import copy
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from director import Director, ROOT
from director_server import make_server
from director_simulator import SimulatedOBS


class MCPIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT,prefix='.director-test-')
        self.sim=SimulatedOBS().__enter__()
        self.d=Director(data_dir=self.tmp.name)
        self.server=make_server(0,self.d)
        self.worker=threading.Thread(target=self.server.serve_forever);self.worker.start()
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://127.0.0.1:{self.server.server_port}/api/health') as response:health=json.load(response)
        self.assertEqual(health['pid'],os.getpid())
        print(f'Verified temporary MCP test HTTP PID {health["pid"]} port {health["port"]}; stopped in teardown')
        self.do('connect',password=self.sim.password,port=self.sim.port)
        self.do('setup',camera='Camera',content='Content')
    def do(self, action, **kw):
        if action == 'arm' and kw.get('enabled') is True:
            from test_director_cold_renderers import ColdRenderer
            with ColdRenderer(self.d,self.sim):return self.d.execute({'action':action,**kw},self.d.version)
        return self.d.execute({'action':action,**kw},self.d.version)
    def tearDown(self):
        self.d.close();self.server.shutdown();self.server.server_close();self.worker.join(timeout=3)
        self.sim.__exit__();self.tmp.cleanup()
    def decode(self,result):
        self.assertFalse(result.isError,result.content)
        return json.loads(next(item.text for item in result.content if item.type=='text'))

    async def test_mcp_fixed_visual_poll_requires_exact_take_and_numeric_http_epoch(self):
        from director_chat import QueueSink
        from test_director_queue import adapter,envelope
        self.do('arm',enabled=True);self.do('audience',enabled=True);self.do('local_director_polls',enabled=True)
        params=StdioServerParameters(command=sys.executable,args=[str(ROOT/'director_mcp.py'),'--port',str(self.server.server_port)],env={})
        async with stdio_client(params) as (r,w):
            async with ClientSession(r,w) as session:
                await session.initialize()
                self.do('stage_patch',fields={'mode':'live'})
                staged=self.decode(await session.call_tool('stage_visual_poll',{'expected_version':self.d.version,'question':'Which visual next?','choices':['Explain the flow','Show the approved page']}))
                self.assertFalse(staged['local_director_poll']['taken'])
                self.assertTrue((await session.call_tool('stage_visual_poll',{'expected_version':self.d.version,'question':'Invalid','choices':['Only one']})).isError)
                before=self.sim.program
                self.decode(await session.call_tool('preview_segment',{'expected_version':self.d.version,'target':'obs'}))
                bank=self.d.native.prepared['bank'];value=self.d.render('bank-'+bank)
                self.d.preview_ack(self.d.stage_id);self.d.bank_ack(bank,value['id'],value['serial'],'obs')
                self.assertTrue((await session.call_tool('take_segment',{'expected_version':self.d.version})).isError)
                self.assertEqual(self.sim.program,before)
                self.do('approve_agent_take')
                taken=self.decode(await session.call_tool('take_segment',{'expected_version':self.d.version}))
                epoch=taken['local_director_poll']['epoch'];self.assertTrue(taken['local_director_poll']['open'])
                before=(self.sim.program,copy.deepcopy(self.d.program),copy.deepcopy(self.sim.inputs),copy.deepcopy(self.d.banks))
                received=adapter(QueueSink(self.server.server_port,enable_local_director_polls=True))
                received.feed(envelope('!vote 2','http-numeric','123456789'))
                status=self.decode(await session.call_tool('director_status',{}))
                self.assertEqual(status['poll_tally']['counts'],[0,1])
                self.assertNotIn('123456789',json.dumps(status))
                self.assertEqual((self.sim.program,self.d.program,self.sim.inputs,self.d.banks),before)
                closed=self.decode(await session.call_tool('control_visual_poll',{'expected_version':self.d.version,'epoch':epoch,'operation':'close'}))
                self.assertFalse(closed['local_director_poll']['open'])
                self.assertTrue((await session.call_tool('control_visual_poll',{'expected_version':self.d.version,'epoch':epoch,'operation':'open'})).isError)
                received.feed(envelope('!vote 1','http-closed','999'))
                self.assertEqual(self.d.vote_state['counts'],[0,1])
                opened=self.decode(await session.call_tool('control_visual_poll',{'expected_version':self.d.version,'epoch':closed['local_director_poll']['epoch'],'operation':'open'}))
                self.assertTrue(opened['local_director_poll']['open'])
                removed=self.decode(await session.call_tool('stage_visual_poll',{'expected_version':self.d.version}))
                self.assertIsNone(removed['staged']['vote'])
                self.assertTrue((await session.call_tool('take_segment',{'expected_version':self.d.version})).isError)
                with self.assertRaises(ValueError):self.d.execute_agent({'action':'local_director_polls','enabled':True},self.d.version)

    async def test_voice_page_id_can_stage_registered_second_page_without_ui_reselection(self):
        self.do('arm',enabled=True)
        self.do('page_register',id='one',name='First page',url='https://example.org/one')
        self.do('page_register',id='two',name='Second page',url='https://example.org/two')
        self.do('page_select',id='one')
        second=next(item for item in self.d.agent_state()['page_catalog'] if item['id']=='two')
        choice={'id':second['id'],'revision':second['revision']}
        params=StdioServerParameters(command=sys.executable,args=[str(ROOT/'director_mcp.py'),'--port',str(self.server.server_port)],env={})
        async with stdio_client(params) as (r,w):
            async with ClientSession(r,w) as session:
                await session.initialize()
                before=copy.deepcopy(self.sim.inputs);geometry=self.d.native.fingerprint(self.sim.program)
                bank=self.d.program_bank;payload=copy.deepcopy(self.d.banks[bank])
                staged=self.decode(await session.call_tool('stage_selected_page',{'expected_version':self.d.version,**choice}))
                self.assertEqual(staged['staged_page'],choice)
                self.assertEqual(staged['selected_page']['id'],'one')
                self.assertEqual(self.sim.inputs,before)
                self.decode(await session.call_tool('preview_segment',{'expected_version':self.d.version,'target':'obs'}))
                self.assertEqual(self.d.native.fingerprint(self.sim.program),geometry)
                self.assertEqual(self.sim.inputs['Director / Page '+bank],before['Director / Page '+bank])
                self.assertEqual(self.d.banks[bank],payload)
                ready=self.d.render('bank-'+self.d.native.prepared['bank'])
                self.d.preview_ack(self.d.stage_id);self.d.bank_ack(self.d.native.prepared['bank'],ready['id'],ready['serial'],'obs')
                self.assertTrue((await session.call_tool('take_segment',{'expected_version':self.d.version})).isError)
                self.do('approve_agent_take')
                taken=self.decode(await session.call_tool('take_segment',{'expected_version':self.d.version}))
                self.assertEqual(taken['program_page'],choice)
                self.assertEqual(taken['selected_page']['id'],'one')
                self.do('page_register',id='two',name='Replaced',url='https://example.org/replaced')
                self.assertTrue((await session.call_tool('stage_selected_page',{'expected_version':self.d.version,**choice})).isError)
                current=self.d.pages.catalog()[1]
                self.do('page_remove',id='two')
                self.assertTrue((await session.call_tool('stage_selected_page',{'expected_version':self.d.version,'id':'two','revision':current['revision']})).isError)
                self.assertTrue((await session.call_tool('stage_selected_page',{'expected_version':self.d.version,'id':'unknown','revision':'none'})).isError)
                self.assertTrue((await session.call_tool('read_selected_material',{'id':'twitch-story','revision':'unselected'})).isError)

    async def test_real_stdio_tools_author_full_compositions_and_respect_human_arm_and_render_gates(self):
        params=StdioServerParameters(command=sys.executable,args=[str(ROOT/'director_mcp.py'),'--port',str(self.server.server_port)],env={})
        async with stdio_client(params) as (r,w):
            async with ClientSession(r,w) as session:
                initialized=await session.initialize()
                self.assertIn('brief spoken plan',initialized.instructions)
                self.assertIn('explicitly approve',initialized.instructions)
                self.assertIn('Undo that means undo_camera_layout',initialized.instructions)
                names={t.name for t in (await session.list_tools()).tools}
                self.assertEqual(names,{'director_status','draft_composition','revise_composition','preview_segment','take_segment','restore_segment','segment_action','undo_camera_layout','read_selected_material','stage_selected_page','stage_bound_content','stage_visual_poll','control_visual_poll'})
                status=self.decode(await session.call_tool('director_status',{}))
                self.assertNotIn('password',json.dumps(status));self.assertNotIn('catalog',status)
                self.assertTrue((await session.call_tool('read_selected_material',{'id':'twitch-story','revision':'unselected'})).isError)
                self.do('material_select',id='twitch-story')
                material=self.d.state()['selected_material']
                reference=self.decode(await session.call_tool('read_selected_material',material))
                self.assertIn('streamer direction',reference['content'])
                status=self.decode(await session.call_tool('director_status',{}))
                original={'name':'Client-authored geometry','duration':7,'elements':[
                    {'id':'headline','kind':'text','text':'An authored idea','x':220,'y':600,'w':1300,'h':110,'size':80,'motion':'rise'},
                    *[{'id':f'orb{i}','kind':'circle','x':330+i*430,'y':200+i*35,'w':45+i*15,'h':45+i*15,'color':'#0047ff','motion':'orbit'} for i in range(3)]]}
                draft=self.decode(await session.call_tool('draft_composition',{'expected_version':status['version'],'composition':original,'mode':'live','layout':'pip'}))
                self.assertEqual(draft['staged']['composition']['elements'][2]['x'],760)
                before=self.sim.program
                refused=await session.call_tool('preview_segment',{'expected_version':draft['version'],'target':'obs'})
                self.assertTrue(refused.isError);self.assertEqual(before,self.sim.program)
                # Human-only arm is simulated here through the controller fixture, never an MCP tool.
                self.do('arm',enabled=True)
                self.do('checkpoint')  # Full-show anchor is independent of later camera-layout undo.
                status=self.decode(await session.call_tool('director_status',{}))
                preview=self.decode(await session.call_tool('preview_segment',{'expected_version':status['version'],'target':'obs'}))
                self.d.preview_ack(self.d.stage_id)
                refused=await session.call_tool('take_segment',{'expected_version':preview['version']})
                self.assertTrue(refused.isError);self.assertEqual(before,self.sim.program)
                bank=self.d.native.prepared['bank'];value=self.d.render('bank-'+bank)
                self.d.bank_ack(bank,value['id'],value['serial'],'obs')  # Explicit simulated renderer.
                self.assertTrue((await session.call_tool('take_segment',{'expected_version':self.d.version})).isError)
                self.assertFalse(self.d.agent_state()['agent_take_approved'])
                with self.assertRaises(ValueError):self.d.execute_agent({'action':'approve_agent_take'},self.d.version)
                self.do('approve_agent_take')  # Explicit simulated operator decision; never a renderer ACK.
                taken=self.decode(await session.call_tool('take_segment',{'expected_version':self.d.version}))
                self.assertEqual(taken['program']['composition']['elements'][0]['text'],'An authored idea')
                revised=copy.deepcopy(original);revised['elements'][0]['text']='Revised by the trusted client';revised['elements'][1]['x']=450
                result=self.decode(await session.call_tool('revise_composition',{'expected_version':taken['version'],'composition':revised}))
                self.assertFalse(result['previewed']);self.assertEqual(result['staged']['composition']['elements'][1]['x'],450)
                self.assertTrue((await session.call_tool('take_segment',{'expected_version':result['version']})).isError)
                self.assertTrue((await session.call_tool('segment_action',{'expected_version':result['version'],'action':'arm','enabled':True})).isError)
                bad=copy.deepcopy(original);bad['elements'][0]['html']='<script>bad</script>'
                self.assertTrue((await session.call_tool('draft_composition',{'expected_version':result['version'],'composition':bad})).isError)
                with self.assertRaises(ValueError):self.d.execute_agent({'action':'connect','password':'not-a-real-secret'},self.d.version)
                with self.assertRaises(ValueError):self.d.execute_agent({'action':'stage_patch','fields':{'media':'../private'}},self.d.version)
                paused=self.decode(await session.call_tool('segment_action',{'expected_version':self.d.version,'action':'pause','paused':True}))
                self.assertTrue(paused['paused'])
                self.decode(await session.call_tool('segment_action',{'expected_version':paused['version'],'action':'pause','paused':False}))
                prior_layout=self.d.native.bound_layout()['geometry']
                drafted=self.decode(await session.call_tool('draft_composition',{'expected_version':self.d.version,'composition':revised,'mode':'live','layout':'side-by-side'}))
                self.decode(await session.call_tool('preview_segment',{'expected_version':drafted['version'],'target':'obs'}))
                self.d.preview_ack(self.d.stage_id)
                bank=self.d.native.prepared['bank'];value=self.d.render('bank-'+bank)
                self.d.bank_ack(bank,value['id'],value['serial'],'obs')
                self.assertTrue((await session.call_tool('take_segment',{'expected_version':self.d.version})).isError)
                self.do('approve_agent_take')
                self.decode(await session.call_tool('take_segment',{'expected_version':self.d.version}))
                payloads=copy.deepcopy(self.d.banks);program=copy.deepcopy(self.d.program)
                scenes=(self.sim.program,self.sim.preview)
                undone=self.decode(await session.call_tool('undo_camera_layout',{'expected_version':self.d.version}))
                self.assertFalse(undone['can_undo_camera_layout'])
                self.assertEqual(self.d.native.bound_layout()['geometry'],prior_layout)
                self.assertEqual((self.sim.program,self.sim.preview),scenes)
                self.assertEqual(self.d.banks,payloads);self.assertEqual(self.d.program,program)
                self.assertFalse(self.d._review_ready());self.assertFalse(self.d._agent_approved())
                self.assertTrue((await session.call_tool('undo_camera_layout',{'expected_version':self.d.version})).isError)
                self.do('page_register',id='reference-page',name='Approved public page',url='https://example.org/article')
                self.do('page_select',id='reference-page')
                page=self.d.state()['selected_page']
                source=copy.deepcopy(self.sim.inputs['Content'])
                staged=self.decode(await session.call_tool('stage_selected_page',{'expected_version':self.d.version,**page}))
                self.assertNotIn('https://example.org',json.dumps(staged))
                old_scene=self.sim.program;old_geometry=self.d.native.fingerprint(old_scene)
                self.decode(await session.call_tool('preview_segment',{'expected_version':self.d.version,'target':'obs'}))
                self.assertEqual(self.d.native.fingerprint(old_scene),old_geometry)
                bank=self.d.native.prepared['bank'];value=self.d.render('bank-'+bank)
                self.d.preview_ack(self.d.stage_id);self.d.bank_ack(bank,value['id'],value['serial'],'obs')
                self.assertTrue((await session.call_tool('take_segment',{'expected_version':self.d.version})).isError)
                self.do('approve_agent_take')
                taken=self.decode(await session.call_tool('take_segment',{'expected_version':self.d.version}))
                self.assertEqual(taken['program_page'],page);self.assertFalse(taken['external_page_load_verified'])
                self.assertEqual(self.sim.inputs['Content'],source)
                self.decode(await session.call_tool('stage_bound_content',{'expected_version':self.d.version}))
                self.decode(await session.call_tool('preview_segment',{'expected_version':self.d.version,'target':'obs'}))
                bank=self.d.native.prepared['bank'];value=self.d.render('bank-'+bank)
                self.d.preview_ack(self.d.stage_id);self.d.bank_ack(bank,value['id'],value['serial'],'obs')
                self.do('approve_agent_take')
                self.decode(await session.call_tool('take_segment',{'expected_version':self.d.version}))
                self.assertEqual(self.sim.inputs['Content'],source)
                restore=asyncio.create_task(session.call_tool('restore_segment',{'expected_version':self.d.version}))
                while not restore.done():
                    await asyncio.sleep(.02)
                    for bank in ('A','B'):
                        value=self.d.render('bank-'+bank)
                        self.d.bank_ack(bank,value['id'],value['serial'],'obs')
                restored=self.decode(await restore)
                self.assertEqual(restored['program']['mode'],'starting')
                self.assertEqual(self.sim.program,before)
                print('PASS actual MCP initialize/list_tools/call_tool: full arbitrary geometry authored and revised; OBS/render/privilege gates enforced. OBS is simulated; no model calls.')

if __name__=='__main__':unittest.main()
