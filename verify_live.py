import asyncio,json,sys,time,uuid,urllib.request,urllib.error
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
from playwright.async_api import async_playwright
ROOT=Path(__file__).resolve().parent
run_id=uuid.uuid4().hex
proof={'kind':'Actual official MCP client plus browser clickthrough; typed transcript, not microphone audio','steps':[]}
def get():return json.load(urllib.request.urlopen('http://127.0.0.1:8874/api/state'))
def record(name,**v):proof['steps'].append({'name':name,**v})
async def run():
 async with stdio_client(StdioServerParameters(command=sys.executable,args=[str(ROOT/'live_mcp.py')])) as (r,w):
  async with ClientSession(r,w) as c:
   await c.initialize();ts=await c.list_tools();record('MCP initialize/list_tools',tools=[t.name for t in ts.tools]);assert len(ts.tools)==6
   s=await c.call_tool('display_status',{});assert not s.isError
   x=await c.call_tool('set_display',{'title':'The toast experiment','subtitle':'Three attempts. One toaster.','accent':'lime'});assert not x.isError;assert get()['display']['title']=='The toast experiment';record('Agent MCP call changed real browser state',revision=get()['revision'])
   before=get()['revision']
   for eid,final,text in [('interim',False,'Director, reveal TOO EARLY'),('normal',True,'Today we are talking about toast')]:
    x=await c.call_tool('ingest_transcript',{'event_id':run_id+eid,'final':final,'text':text});assert not x.isError;assert get()['revision']==before
   record('Interim and ordinary speech do not change display')
   x=await c.call_tool('ingest_transcript',{'event_id':run_id+'cue-final','text':'The test is complete. Director, reveal TOAST ACHIEVED'});assert not x.isError;rev=get()['revision'];assert get()['display']['cue']=='TOAST ACHIEVED'
   await c.call_tool('ingest_transcript',{'event_id':run_id+'cue-final','text':'Director, show RETRY'});assert get()['revision']==rev;record('Final transcript applied once; duplicate retry unchanged',revision=rev)
   await c.call_tool('pause_display',{'paused':True});await c.call_tool('ingest_transcript',{'event_id':run_id+'paused','text':'Director, show SHOULD NOT APPEAR'});assert get()['revision']==rev;record('Pause blocks transcript updates')
   await c.call_tool('pause_display',{'paused':False});bad=await c.call_tool('set_display',{'layout':'invented'});assert bad.isError;assert get()['revision']==rev;record('Invalid tool fields rejected without display change')
   obs=await c.call_tool('probe_obs',{});assert not obs.isError;record('Actual OBS probe',observed=get()['obs'])
   async with async_playwright() as p:
    browser=await p.chromium.launch(headless=True);page=await browser.new_page(viewport={'width':1450,'height':1050});await page.goto('http://127.0.0.1:8874/');await page.wait_for_selector('#events .event');await page.screenshot(path=str(ROOT/'LIVE-01-MCP.png'),full_page=True)
    await page.locator('#transcript').fill('And now our next attempt. Director, show A second slice');await page.locator('#send').click();await page.wait_for_timeout(800)
    frame=page.frames[1];assert await frame.locator('#title').inner_text()=='A second slice';record('Actual browser final-transcript click updated iframe',title=await frame.locator('#title').inner_text());await page.screenshot(path=str(ROOT/'LIVE-02-TRANSCRIPT.png'),full_page=True)
    await page.get_by_role('button',name='Countdown 20s',exact=True).click();await page.wait_for_timeout(800);t1=await frame.locator('#timer').inner_text();await page.wait_for_timeout(1100);t2=await frame.locator('#timer').inner_text();assert int(t2)<int(t1);record('Actual browser countdown advances',first=t1,second=t2);await page.screenshot(path=str(ROOT/'LIVE-03-COUNTDOWN.png'),full_page=True)
    await page.get_by_role('button',name='Reveal',exact=True).click();await page.wait_for_timeout(700);assert await frame.locator('#cueText').inner_text()=='TOAST ACHIEVED';await page.screenshot(path=str(ROOT/'LIVE-04-REVEAL.png'),full_page=True)
    await page.get_by_role('button',name='Undo display',exact=True).click();await page.wait_for_timeout(700);assert await frame.locator('#cueText').inner_text()=='Up next';record('Browser undo restores real prior display')
    await browser.close()
   await c.call_tool('set_display',{'title':'The toast experiment','subtitle':'Three attempts. One toaster.','cue':'TOAST ACHIEVED','seconds':0})
 for host,origin in [('evil.test','http://evil.test'),('127.0.0.1:8874','http://evil.test')]:
  q=urllib.request.Request('http://127.0.0.1:8874/api/display',data=b'{"fields":{"title":"bad"}}',headers={'Host':host,'Origin':origin})
  try:urllib.request.urlopen(q);raise AssertionError('Cross-origin accepted')
  except urllib.error.HTTPError as e:assert e.code==403
 record('Cross-origin and hostile Host rejected')
 proof['final_state']=get();proof['microphone']='UNVERIFIED; no audio captured; tested actual typed transcript event path';proof['obs_rendering']='UNVERIFIED; no listener available; no profiles mutated';Path('LIVE-VERIFICATION.json').write_text(json.dumps(proof,indent=2));print(json.dumps(proof,indent=2))
asyncio.run(run())
