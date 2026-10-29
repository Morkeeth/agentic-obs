"""Short local audio -> whisper.cpp -> official MCP client -> browser display.

No cloud speech service. Files exist only in a disposable local directory.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parent
MODEL = Path(os.environ.get('OBS_WHISPER_MODEL', str(Path.home()/'Models/whisper/ggml-large-v3-turbo.bin')))
AUDIO_LOCK = threading.Lock()

def readiness():
    ready = MODEL.is_file() and bool(shutil.which('whisper-cli')) and bool(shutil.which('ffmpeg'))
    return {'ready': ready, 'local_only': True, 'max_seconds': 15,
            'detail': 'Local transcription ready' if ready else 'Install whisper.cpp and a local model before using audio'}

async def _send(text, event_id):
    port=os.environ.get('AGENTIC_OBS_PORT')
    if port!='8878':
        raise ValueError('Set AGENTIC_OBS_PORT explicitly; no audio cue sent')
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    env = dict(os.environ)
    async with stdio_client(StdioServerParameters(command=sys.executable, args=[str(ROOT/'live_mcp.py')], env=env)) as (r,w):
        async with ClientSession(r,w) as session:
            await session.initialize()
            target=await session.call_tool('display_status', {})
            observed=json.loads(next(c.text for c in target.content if c.type=='text'))
            if observed.get('connector_port')!=int(port):
                raise ValueError('MCP display target did not match this audio connector; no cue sent')
            result = await session.call_tool('ingest_transcript', {'text':text, 'event_id':event_id, 'final':True})
            if result.isError:
                raise ValueError('Transcript was received, but its director cue was not understood')
            return json.loads(next(c.text for c in result.content if c.type=='text'))

def process_audio(data, event_id):
    if not readiness()['ready']:
        raise ValueError(readiness()['detail'])
    if not AUDIO_LOCK.acquire(blocking=False):
        raise ValueError('Local transcriber is busy; retry this clip when it finishes')
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix='agentic-obs-audio-') as td:
            folder=Path(td); raw=folder/'input.audio'; wav=folder/'voice.wav'; output=folder/'transcript'
            raw.write_bytes(data)
            converted=subprocess.run([shutil.which('ffmpeg'),'-v','error','-threads','1','-protocol_whitelist','file,pipe','-i',str(raw),'-t','15.1','-ar','16000','-ac','1','-c:a','pcm_s16le',str(wav)],capture_output=True,timeout=30)
            if converted.returncode: raise ValueError('This file could not be decoded as audio')
            import wave
            with wave.open(str(wav)) as w:
                duration=w.getnframes()/w.getframerate()
            if duration>15: raise ValueError('Choose an audio clip of15seconds or less')
            # Silence is not sent to the recognizer: suppress false transcript hallucinations.
            import audioop
            with wave.open(str(wav)) as w: rms=audioop.rms(w.readframes(w.getnframes()),2)
            if rms<40:
                return {'outcome':'silence; display unchanged','transcript':'','local_only':True,'transport':'no MCP call needed'}
            cmd=[shutil.which('whisper-cli'),'-m',str(MODEL),'-f',str(wav),'-t','1','-p','1','-l','en','-nt','-otxt','-of',str(output),'-bo','1','-bs','1']
            asr=subprocess.run(cmd,capture_output=True,timeout=120)
            if asr.returncode or not output.with_suffix('.txt').exists():raise ValueError('Local transcription failed; no display action was taken')
            text=' '.join(output.with_suffix('.txt').read_text().split())
            result=asyncio.run(_send(text,event_id))
            return {'outcome':result.get('outcome'),'state':result.get('state'),'transcript':text,
                    'local_only':True,'command_result':result,'transport':'whisper.cpp -> MCP ingest_transcript -> '+('native OBS preview' if 'after' in result else 'local display'),
                    'audio_sha256':hashlib.sha256(data).hexdigest(),'duration_s':duration,
                    'latency_s':round(time.monotonic()-started,3)}
    except subprocess.TimeoutExpired:
        raise ValueError('Local audio processing timed out; no display action was taken')
    finally:
        AUDIO_LOCK.release()
