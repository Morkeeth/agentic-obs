#!/usr/bin/env python3
"""Loopback director. No credential discovery; API voice requires explicit opt-in."""
import argparse
import json
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs

from director import Conflict, Director
from director_obs import ObsError
from director_voice import LocalVoice
from director_realtime import RealtimeDirector

ASSETS = Path(__file__).resolve().parent/'director_web'
FILES = {'/': ('index.html', 'text/html'), '/index.html': ('index.html', 'text/html'),
         '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css'),
         '/overlay.html': ('overlay.html', 'text/html'), '/render.js': ('render.js', 'text/javascript'),
         '/overlay.css': ('overlay.css', 'text/css')}
FILES.update({'/voice.html': ('voice.html', 'text/html'),
              '/voice-ptt.js': ('voice-ptt.js', 'text/javascript')})

FILES.update({f'/fixture-{name}.html': (f'fixture-{name}.html', 'text/html') for name in ('camera','content')})

FILES.update({f'/base-{mode}.html': (f'base-{mode}.html', 'text/html') for mode in ('starting','brb','ending')})


def make_server(port=8880, director=None, voice=None, realtime=None, realtime_key=None):
    if type(port) is not int or port in (4455, 8877, 8878, 8879) or not (port == 0 or 1024 <= port <= 65535):
        raise ValueError('Choose a free loopback HTTP port; existing OBS/controller ports are reserved')
    director = director or Director(port=port)
    voice = voice or LocalVoice()
    realtime = realtime or RealtimeDirector(director, realtime_key)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def setup(self):
            super().setup()
            self.connection.settimeout(10)
        def log_message(self, *args): pass
        def local(self, write=False):
            actual_port = self.server.server_port
            hosts = (f'127.0.0.1:{actual_port}', f'localhost:{actual_port}')
            origins = tuple('http://'+v for v in hosts)
            origin = self.headers.get('Origin')
            return self.headers.get('Host') in hosts and (origin in origins if write else origin is None or origin in origins)
        def send(self, value, status=200, content_type='application/json', attachment=None):
            data = json.dumps(value, ensure_ascii=False).encode() if content_type == 'application/json' else value if isinstance(value, bytes) else value.encode()
            self.send_response(status)
            for k, v in {'Content-Type': content_type+'; charset=utf-8', 'Content-Length': str(len(data)),
                         'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                         'Referrer-Policy': 'no-referrer', 'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'self'"}.items():
                self.send_header(k, v)
            if attachment: self.send_header('Content-Disposition', f'attachment; filename="{attachment}"')
            self.end_headers()
            self.wfile.write(data)
        def do_GET(self):
            if not self.local(): return self.send({'error': 'Loopback host/origin required'}, 403)
            path = urlsplit(self.path)
            try:
                if path.path == '/api/chat-poll': return self.send(director.poll_context())
                if path.path == '/api/operator-setup': return self.send(director.operator_setup_state())
                if path.path == '/api/participation': return self.send(director.participation_state())
                if path.path == '/api/agent-state': return self.send(director.agent_state())
                if path.path == '/api/state': return self.send(director.state())
                if path.path == '/api/health': return self.send({'build': 'expanded-director-1', 'pid': os.getpid(), 'port': self.server.server_port})
                if path.path == '/api/render': return self.send(director.render(parse_qs(path.query).get('channel', ['program'])[0]))
                if path.path == '/api/obs': return self.send(director.probe())
                if path.path == '/api/voice': return self.send(voice.status())
                if path.path == '/api/realtime': return self.send(realtime.status())
                if path.path == '/api/markers.csv': return self.send(director.markers_csv(), content_type='text/csv', attachment='director-local-markers.csv')
                if path.path == '/api/inputs':
                    with director.lock:
                        if not director.native: raise ValueError('Connect OBS first')
                        return self.send({'inputs': director.native.inputs()})
                if path.path in FILES:
                    filename, mime = FILES[path.path]
                    return self.send((ASSETS/filename).read_bytes(), content_type=mime)
                return self.send({'error': 'Not found'}, 404)
            except (ValueError, ObsError) as exc: return self.send({'error': str(exc)}, 400)
            except Exception: return self.send({'error': 'Local read failed'}, 500)
        def do_POST(self):
            if not self.local(write=True):
                self.close_connection = True
                return self.send({'error': 'Use the local controller origin for mutations'}, 403)
            try:
                size = int(self.headers.get('Content-Length', '0'))
                path = urlsplit(self.path).path
                if not 0 < size <= (3_000_000 if path in ('/api/audio', '/api/realtime-turn') else 131072): raise ValueError('Request too large or empty')
                raw = self.rfile.read(size)
                if len(raw) != size: raise ValueError('Incomplete request')
                if path == '/api/realtime-turn': return self.send(realtime.turn(raw))
                if path == '/api/audio':
                    event_id = self.headers.get('X-Event-Id', '')
                    if not 1 <= len(event_id) <= 100: raise ValueError('Audio event ID required')
                    result = voice.transcribe(raw)
                    result['delivery'] = director.transcript(result['text'], event_id, True) if result['text'] else {'result': 'silence ignored'}
                    return self.send(result)
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json': raise ValueError('JSON required')
                data = json.loads(raw)
                if not isinstance(data, dict): raise ValueError('Expected an object')
                if path == '/api/realtime-stop':
                    if data: raise ValueError('Empty stop contract required')
                    realtime.close()
                    return self.send({'stopped': True})
                if path == '/api/selected-material':
                    if set(data)!={'id','revision'}: raise ValueError('Selected material ID/revision required')
                    return self.send(director.read_selected_material(data['id'],data['revision']))
                if path == '/api/operator-setup':
                    if set(data) != {'expected','command'}: return self.send({'error':'Operator setup contract refused'},400)
                    try:return self.send(director.operator_setup_action(data['command'],data['expected']))
                    except Conflict:return self.send({'error':'Operator setup changed; refresh before acting'},409)
                    except (ValueError,ObsError,TypeError,KeyError):return self.send({'error':'Operator setup not confirmed; refresh and inspect'},400)
                if path == '/api/participation':
                    if set(data) != {'expected','command'}: raise ValueError('Exact participation version/command required')
                    return self.send(director.participation_action(data['command'],data['expected']))
                if path == '/api/operator-review':
                    if set(data) != {'expected','review','operation'}: raise ValueError('Exact human review contract required')
                    return self.send(director.operator_review(data['review'],data['expected'],data['operation']))
                if path == '/api/agent':
                    if set(data) != {'expected','command'}: raise ValueError('Expected version and bounded command')
                    return self.send(director.execute_agent(data['command'],data['expected']))
                if path == '/api/action':
                    if set(data) != {'expected', 'command'}: raise ValueError('Expected version and command')
                    return self.send(director.execute(data['command'], data['expected']))
                if path == '/api/rendered':
                    if set(data) not in ({'bank', 'id', 'serial', 'renderer', 'renderer_instance'}, {'bank', 'id', 'serial', 'renderer', 'renderer_instance', 'warm_epoch'}): raise ValueError('Bank render contract required')
                    if not isinstance(data['renderer_instance'], str): raise ValueError('Renderer document identity required')
                    return self.send(director.bank_ack(data['bank'], data['id'], data['serial'], data['renderer'], data.get('warm_epoch'), data['renderer_instance']))
                if path == '/api/previewed':
                    if set(data) != {'stage_id'}: raise ValueError('Expected stage ID')
                    return self.send(director.preview_ack(data['stage_id']))
                if path == '/api/chat-vote':
                    return self.send(director.ingest_vote(data))
                if path == '/api/chat-request':
                    return self.send(director.enqueue_request(data))
                if path == '/api/audience':
                    if set(data) - {'voter', 'message', 'cue'} or ('cue' in data) == ('message' in data): raise ValueError('Fixed cue or numeric vote required')
                    return self.send(director.audience(data.get('voter', 'fixed-cue'), data.get('message'), data.get('cue')))
                if path == '/api/transcript':
                    if set(data) != {'text', 'event_id', 'final'}: raise ValueError('Final transcript contract required')
                    return self.send(director.transcript(data['text'], data['event_id'], data['final']))
                return self.send({'error': 'Not found'}, 404)
            except Conflict as exc: return self.send({'error': str(exc)}, 409)
            except ObsError as exc: return self.send({'error': str(exc)}, 503)
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                # Validation strings are authored here; never echo bodies, passwords or OBS replies.
                message = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError) else 'Malformed action'
                return self.send({'error': message}, 400)
            except Exception: return self.send({'error': 'Local operation failed; refresh state and inspect before retrying'}, 500)

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    director.port = server.server_port
    server.director = director
    server.realtime = realtime
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8880)
    parser.add_argument('--voice-model', type=Path, help='Explicit project-local whisper.cpp model; no discovery')
    parser.add_argument('--realtime-voice', action='store_true', help='Explicitly enable OpenAI API speech using server-side OPENAI_API_KEY; billed API, not ChatGPT subscription')
    args = parser.parse_args()
    key = os.environ.get('OPENAI_API_KEY') if args.realtime_voice else None
    if args.realtime_voice and not key: parser.error('OPENAI_API_KEY is required for explicit --realtime-voice; no credential discovery/fallback')
    server = make_server(args.port, voice=LocalVoice(args.voice_model), realtime_key=key)
    print(f'Expanded director listening http://127.0.0.1:{server.server_port} PID {os.getpid()} (foreground; OBS not connected)', flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        server.realtime.close()
        server.director.close()
        server.server_close()

if __name__ == '__main__': main()
