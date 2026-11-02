"""Local streamer workspace. Default is synthetic and account-free."""
import argparse
import base64
import binascii
import json
import os
from pathlib import Path
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from streamer import Show, Refused
from obs import RehearsalNative, ObsAdapter, ObsSocket
from transport import CodexDirector, VoiceSession, Whisper, RUNTIME
from visuals import VisualLibrary, PreviewVisuals

WEB = Path(__file__).resolve().parent / 'web'

def server_wire(show):return getattr(show.native,'wire',None)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def reply(self, value, status=200):
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(data)))
        self.end_headers(); self.wfile.write(data)
    def _local(self, mutation=False):
        origin = f'http://127.0.0.1:{self.server.server_port}'
        if self.headers.get('Host') != origin.removeprefix('http://'):
            raise PermissionError('Use the loopback workspace URL')
        if mutation and self.headers.get('Origin') != origin:
            raise PermissionError('Same-origin workspace request required')
    def do_GET(self):
        try:
            self._local()
            if self.path == '/api/frames':
                if not hasattr(self.server.show.native,'frames'): return self.reply({'synthetic':True})
                return self.reply(self.server.show.native.frames())
            if self.path == '/api/twitch':return self.reply(self.server.show.twitch.snapshot())
            if self.path == '/api/library':return self.reply(self.server.show.live.assets.catalog() if self.server.show.live and self.server.show.live.assets else [])
            if self.path.startswith('/library/'):
                parts=self.path.split('/')
                if len(parts) not in (3,4) or (len(parts)==4 and parts[3]!='thumbnail'):return self.reply({'error':'Unknown library resource'},404)
                library=self.server.show.live.assets if self.server.show.live else None
                if library is None:return self.reply({'error':'Library unavailable'},404)
                file=library.path(parts[2],thumbnail=len(parts)==4);payload=file.read_bytes()
                self.send_response(200);self.send_header('Content-Type',{'.mp4':'video/mp4','.mp3':'audio/mpeg','.jpg':'image/jpeg','.png':'image/png','.cube':'text/plain'}.get(file.suffix,'application/octet-stream'));self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload);return
            if self.path == '/api/catalog': return self.reply(self.server.show.visuals.library.catalog())
            if self.path.startswith('/asset/') and self.path.endswith('.png'):
                ident=self.path.removeprefix('/asset/').removesuffix('.png')
                payload=self.server.show.visuals.library.path(ident).read_bytes()
                self.send_response(200);self.send_header('Content-Type','image/png');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload);return
            if self.path == '/api/state': return self.reply(self.server.show.state())
            paths = {'/':('index.html','text/html'), '/app.js':('app.js','text/javascript'), '/ptt.js':('ptt.js','text/javascript'), '/monitor.js':('monitor.js','text/javascript'), '/continuous.js':('continuous.js','text/javascript'), '/speech.js':('speech.js','text/javascript'), '/music.js':('music.js','text/javascript'), '/overlay/twitch':('chat.html','text/html'), '/chat.js':('chat.js','text/javascript'), '/chat.css':('chat.css','text/css'), '/style.css':('style.css','text/css')}
            if self.path not in paths: return self.reply({'error':'Unknown route'},404)
            filename,mime = paths[self.path]
            data = (WEB/filename).read_bytes()
            self.send_response(200); self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(data)))
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; media-src 'self' blob:; img-src 'self' data:; frame-ancestors 'none'")
            self.end_headers(); self.wfile.write(data)
        except PermissionError as exc: self.reply({'error':str(exc)},403)
        except Exception: self.reply({'error':'Native state unavailable; inspect connection'},502)
    def do_POST(self):
        try:
            self._local(mutation=True)
            if self.headers.get('Content-Type','').split(';')[0] != 'application/json':
                return self.reply({'error':'JSON required'},415)
            size = int(self.headers.get('Content-Length','0'))
            if not 1 <= size <= 6_000_000: return self.reply({'error':'Body size refused'},413)
            data = json.loads(self.rfile.read(size))
            if not isinstance(data,dict): raise ValueError('Object required')
            show,voice = self.server.show,self.server.voice
            path = self.path
            if path == '/api/direct':
                if data.get('source','typed')!='typed':raise Refused('Use the microphone voice route for spoken directions')
                result = show.operator_direction(data.get('text'), 'typed')
            elif path == '/api/twitch/connect':result=show.twitch.connect(data.get('channel'))
            elif path == '/api/twitch/bandwidth-test':
                if not server_wire(show):raise Refused('Connect native OBS before preparing Twitch ingest')
                from stream_test import StreamTest
                result=StreamTest(server_wire(show)).prepare()
            elif path == '/api/twitch/commands':result=show.twitch.commands.configure(data.get('enabled'))
            elif path == '/api/twitch/disconnect':show.twitch.stop();result=show.twitch.snapshot()
            elif path == '/api/library/use':
                if not show.live or not show.live.assets:raise Refused('Approved library unavailable')
                asset=show.live.assets.assets.get(data.get('id'))
                if not asset:raise Refused('Choose an indexed asset')
                kind=asset['type'];ident=asset['id']
                cue={'camera':'close up' if 'close' in asset['tags'] else 'switch to the wide shot','music':'play music','lut':'make it warmer' if ident=='warm' else 'cool look' if ident=='cool' else 'cinematic look','clip':'play the '+ident+' clip','animation':'play the '+ident,'border':'add a border','overlay':'lower third Agentic Streamer'}.get(kind)
                if not cue:raise Refused('This asset has no stage action')
                result=show.apply_plan({'operator_cue':cue,'source':'typed'})
            elif path == '/api/visual': result = show.visuals.command(**data)
            elif path == '/api/image': result = show.visuals.library.add_image(data.get('name','Selected image'),base64.b64decode(data.get('image',''),validate=True))
            elif path == '/api/page': result = show.visuals.library.add_page(data.get('url'))
            elif path == '/api/enable': result = show.enable()
            elif path == '/api/disable': voice.cancel(); result = show.disable()
            elif path == '/api/stage':
                if show.live:
                    show.apply_plan({'operator_cue':'lower third '+str(data.get('title','')),'source':'typed'})
                    result=show.state()
                else:result=show.stage(data.get('title'))
            elif path == '/api/clear':
                if show.live:
                    show.apply_plan({'operator_cue':'clear preview','source':'typed'});result=show.state()
                else:result=show.clear()
            elif path == '/api/restore':
                if show.live:
                    show.apply_plan({'operator_cue':'restore preview','source':'typed'});result=show.state()
                else:result=show.restore()
            elif path == '/api/voice/start': result = {'token':voice.start()}
            elif path == '/api/voice/cancel': result = voice.cancel()
            elif path == '/api/voice/finish':
                start = time.monotonic()
                audio = base64.b64decode(data.get('audio',''),validate=True)
                result = voice.finish(audio, data.get('token',''),apply=True)
                result['latency_ms'] = round((time.monotonic()-start)*1000,1)
                result['latency_scope'] = 'release request through ASR, director and preview readback; excludes browser speech playback'
            else: return self.reply({'error':'Unknown route'},404)
            self.reply(result)
        except PermissionError as exc: self.reply({'error':str(exc)},403)
        except (BrokenPipeError,ConnectionResetError):pass
        except Refused as exc: self.reply({'error':str(exc)},409)
        except (ValueError,TypeError,binascii.Error): self.reply({'error':'Malformed request'},400)
        except Exception:
            self.server.show.disable()
            self.reply({'error':'Transport failed; preview control disabled; inspect native state'},502)

def make_server(show, port=60212, transcribe=None):
    server = ThreadingHTTPServer(('127.0.0.1',port), Handler)
    if not show.visuals: PreviewVisuals(show,VisualLibrary(RUNTIME/'assets'))
    from twitch_chat import TwitchChat
    if show.twitch is None:show.twitch=TwitchChat()
    from chat_commands import ChatCommands
    if show.twitch.commands is None:show.twitch.commands=ChatCommands(show)
    server.show = show
    server.voice = VoiceSession(show, transcribe or Whisper(os.environ.get('STREAM_WHISPER_MODEL','/not-configured'),port=os.environ.get('STREAM_WHISPER_PORT')))
    return server

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=60212)
    parser.add_argument('--obs',action='store_true')
    parser.add_argument('--camera-scene',action='append',help='Explicit camera scene allowlist, repeat for multiple cameras')
    parser.add_argument('--live',action='store_true',help='Independent camera/overlay preview banks and explicit spoken local takes')
    parser.add_argument('--obs-port',type=int,default=4455)
    parser.add_argument('--staging',default='Staging')
    parser.add_argument('--graphics',default='graphics')
    parser.add_argument('--director',choices=('rehearsal','codex'),default='rehearsal')
    args = parser.parse_args()
    wire = ObsSocket(args.obs_port,os.environ.get('OBS_PASSWORD','')) if args.obs else None
    native = ObsAdapter(wire,args.staging,args.graphics) if wire else RehearsalNative()
    show = Show(native,args.staging,args.graphics,CodexDirector() if args.director == 'codex' else None)
    server = make_server(show,args.port)
    if args.live:
        if not wire:raise Refused('Live composition requires a real OBS connection')
        from live import LiveStudio
        from live_obs import LiveObs
        from media_library import AssetLibrary
        assets=AssetLibrary(Path(__file__).resolve().parent/'assets/library/index.json',RUNTIME/'licensed-media/index.json')
        cameras=args.camera_scene or ['Camera']
        from computer import BrowserDirector
        from browser_window import BrowserWindow
        import tempfile
        def launch_browser():return BrowserWindow.launch(Path(tempfile.mkdtemp(prefix='dedicated-browser-',dir=RUNTIME)),port=0,headless=True)
        show.browser=BrowserDirector(launch_browser)
        show.live=LiveStudio(LiveObs(wire,RUNTIME/'live',show.visuals.library,cameras,assets,port=server.server_port),show.visuals.library.slides,cameras,assets,show.twitch.snapshot)
    print(json.dumps({'url':f'http://127.0.0.1:{server.server_port}', 'native':'OBS' if wire else 'synthetic rehearsal', 'director':show.director.name}),flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        show.disable(); show.twitch.stop(); server.server_close()
        if show.browser and show.browser.window:show.browser.window.close()
        if wire: wire.close()

if __name__ == '__main__': main()
