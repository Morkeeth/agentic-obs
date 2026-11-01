"""Official MCP Python SDK stdio adapter. Start live_server.py separately."""
import json, urllib.request, urllib.error, os
from mcp.server.fastmcp import FastMCP
mcp=FastMCP('Agentic OBS local display')
def api(path,data=None):
    if path not in {'state','display','transcript','arm','undo','obs','native'}:raise ValueError('This endpoint is not exposed through MCP')
    port=os.environ.get('AGENTIC_OBS_PORT')
    if port!='8878':
        raise ValueError('Set AGENTIC_OBS_PORT explicitly; refusing an implicit display target')
    if data is not None:
        state=api('state')
        if state.get('connector_port')!=8878 or state.get('build_tag')!='native-program-27oct':raise ValueError('Native build identity mismatch; no mutation sent')
    req=urllib.request.Request('http://127.0.0.1:'+port+'/api/'+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=4) as r:return json.load(r)
    except urllib.error.HTTPError as e:raise ValueError(e.read().decode())
@mcp.tool()
def display_status()->dict:
    """Read current browser display, final transcripts, revision and OBS connection."""
    return api('state')
@mcp.tool()
def set_display(title:str|None=None,subtitle:str|None=None,layout:str|None=None,accent:str|None=None,cue:str|None=None,seconds:int|None=None)->dict:
    """Update the live browser overlay. Layout speaker/focus/break; accent lime/pink/white. Never starts broadcasting."""
    return api('display',{'source':'mcp','fields':{k:v for k,v in locals().items() if v is not None}})
@mcp.tool()
def ingest_transcript(text:str,event_id:str,final:bool=True)->dict:
    """Ingest final/interim speech. Only explicit 'director, …' cues change displays. Reuse event_id on retry for deduplication."""
    return api('transcript',{'source':'transcript','text':text,'event_id':event_id,'final':final})
@mcp.tool()
def pause_display(paused:bool=True)->dict:
    """Pause or resume automatic display changes."""
    return api('arm',{'armed':not paused})
@mcp.tool()
def undo_display()->dict:
    """Restore previous browser display."""
    return api('undo',{})
@mcp.tool()
def probe_obs()->dict:
    """Read-only local OBS WebSocket connection check; no profile, scene or broadcast mutation."""
    return api('obs',{})
@mcp.tool()
def native_preview_command(text:str)->dict:
    """Control owned native preview/program scenes and save/replay bounded transforms. Program requires explicit session enable; never starts or stops outputs."""
    return api('native',{'text':text})
if __name__=='__main__':mcp.run(transport='stdio')
