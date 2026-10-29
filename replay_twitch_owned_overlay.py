"""Real EventSub adapter -> actual owned HTTP overlay controller. No browser, OBS or Twitch account."""
import asyncio
import json
from pathlib import Path
import subprocess
import sys
from websockets.asyncio.server import serve
import fake_twitch as ft
from twitch_eventsub import Config, StreamAgentSink, offline_endpoints, run
from mock_eventsub import Controller

async def main(out):
    ctl=Controller();sink=StreamAgentSink('http://127.0.0.1:8881')
    with (out/'controller.log').open('w') as log:
        proc=subprocess.Popen([sys.executable,'mock_controller.py'],stdout=log,stderr=subprocess.STDOUT)
        (out/'started.json').write_text(json.dumps({'owned_pid':proc.pid,'endpoint':'http://127.0.0.1:8881','no_browser':True}))
        print('OWNED_PID='+str(proc.pid),flush=True)
        try:
            for _ in range(50):
                try:before=ctl.request('/status');break
                except OSError:await asyncio.sleep(.1)
            assert before['planner']=='rules' and not any(before['inputs'].values())
            assert not before['models']['codex']['enabled'] and before['models']['codex']['calls']==0
            # Explicit, independent input enabling. Transport forwarding is separately enabled below.
            ctl.request('/input',{'source':'chat','on':True})
            cfg=Config(ft.CLIENT_ID,ft.BROADCASTER,ft.BROADCASTER,{'rw-hydrate':'Director show Hydrate!'})
            with ft.FakeHTTP() as http:
                handler,seen=await ft.scenario(http)
                async with serve(handler,'127.0.0.1',8883):
                    adapter=await asyncio.wait_for(run(cfg,offline_endpoints(),lambda:ft.TOKEN,sink,enabled=True),40)
            after=ctl.request('/status')
            assert after['counters']['accepted']==4,after['counters']
            assert [x['kind'] for x in after['log'] if x.get('result')=='shown']==['emoji_burst','popup','clear','popup']
            assert after['models']['codex']['calls']==0 and not after['models']['codex']['enabled']
            assert not adapter.enabled
            ctl.request('/input',{'source':'chat','on':False})
            assert sink('Director party')['shown'] is False
            assert all(not v for v in ctl.request('/status')['inputs'].values())
            assert ft.TOKEN not in json.dumps(adapter.trace)
            proof={'before':before,'after':after,'trace':adapter.trace,'server':seen,'http_requests':http.requests,
                   'inputs_at_end':ctl.request('/status')['inputs'],'socket_client_frames':seen['inbound_frames'],
                   'no_twitch_or_oauth':True,'no_browser_or_obs':True,'limitations':['No pixel/DOM/OBS/viewer evidence','UI still says CHAT SIMULATOR','Fake Twitch endpoints; live auth/delivery not tested']}
            (out/'proof.json').write_text(json.dumps(proof,indent=2))
            print(json.dumps({'accepted':after['counters']['accepted'],'codex_calls':after['models']['codex']['calls'],'inputs_at_end':proof['inputs_at_end'],'connections':seen['connections']}))
        finally:
            proc.terminate();proc.wait(timeout=5)
            (out/'cleanup.json').write_text(json.dumps({'owned_pid':proc.pid,'exit':proc.returncode,'stopped':True}))
if __name__=='__main__':
    out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=False);asyncio.run(main(out))
